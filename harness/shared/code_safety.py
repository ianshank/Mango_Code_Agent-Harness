"""Decide, from a module's own parse tree, whether it names a prohibited symbol.

``execute_generate_code`` already parses every generated Python file with
``ast.parse`` to answer "does it parse", and then throws the tree away
(``docs/reports/2026-DEEP-PEER-REVIEW-GRAPH-ENGINEERING.md`` §4.2). The same
tree answers a second question the policy has been declaring all along and
nothing has been asking: does this file reach one of ``governance-policy.json``
-> ``synthesis.prohibited_imports``? Asking it at the write door is the only
place in the system where that defect is stopped *before* bytes reach disk,
rather than after ``make ci`` goes red and a repair cycle is spent (R-GEA-3,
``docs/specs/graph-engineering-adoption.md`` D-4).

The analysis lives here rather than inside ``tool_executors`` for two reasons.
That module is a protected path, where a four-line diff is a cheap review and a
sixty-line one is not. And the next write door needing this judgement should
call a function rather than copy one -- three copies of a containment check
being three chances for one of them to drift, which is why
``_resolve_in_workspace`` was extracted in the first place.

This module is the policy half: which keys are read, what makes a list unusable,
and how a refusal is worded. Reading Python -- what an expression names, and
whether that name falls under an entry -- is ``code_symbols``, which never opens
a policy file. Both halves are quoted in a denial an author has to act on, so
both are kept small enough to review whole (``limits.size_budget_lines``).

Two policy keys, not one, because two questions gate a write. ``POLICY_KEY``
says what is forbidden; ``PYTHON_SUFFIX_KEY`` says which writes are asked at
all, and a target the second fails to name is never judged by the first --
which is why an unreadable value of either raises rather than defaulting.
"""

from __future__ import annotations

import ast
import logging
from collections.abc import Sequence
from pathlib import Path

from harness.shared.code_symbols import BUILTINS_NAMESPACE, ProhibitedSymbol, symbol_findings
from harness.shared.policy_loader import POLICY_PATH, PolicyError, load_policy, policy_file_is_absent

#: Where the prohibition is declared. Named once so the raised errors, the
#: denial text and the reader all spell the policy address the same way.
POLICY_SECTION = "synthesis"
POLICY_KEY = "prohibited_imports"

#: The sibling key naming the suffixes that make a generated target Python, and
#: so which writes are judged against ``POLICY_KEY`` at all. It lives beside the
#: list it arms, not in ``policy_loader``, whose accessors are the numeric blocks.
PYTHON_SUFFIX_KEY = "python_write_suffixes"

#: Used only when *no* policy file exists -- the adopter case
#: ``policy_file_is_absent`` exists to keep working. A policy that is present
#: and has lost the key raises instead: substituting a plausible default would
#: silently narrow a security check to whatever this constant says
#: (``policy_loader._Section``). ``.pyi`` is excluded on purpose; the policy
#: rationale carries why.
DEFAULT_PYTHON_WRITE_SUFFIXES = frozenset({".py", ".pyw"})

logger = logging.getLogger(__name__)


class ProhibitedSymbolPolicyError(PolicyError):
    """The policy cannot arm this check, so no write may be judged by it.

    Raised rather than degraded into "nothing is prohibited" (R-GEA-4). A
    missing key, an empty list, or a list holding something that is not a string
    all make :func:`prohibited_symbol_findings` return ``[]`` for every input --
    a check that cannot fail, which is worse than an absent check because it
    converts an open question into a false assurance. The same holds for the
    suffix list, one question earlier: a write nobody calls Python is a write
    nobody checks.

    A ``PolicyError`` because that is what it is, and because a call site already
    catching the ``policy_loader`` failures should not need a second name to keep
    failing closed. Still its own class, so a caller that wants *this* refusal
    rather than "the file did not parse" can say so.
    """


def _validated_symbols(entries: object, origin: str) -> tuple[str, ...]:
    """Reject every shape of the prohibited list that could deny nothing.

    Three separate refusals rather than one, because the three causes need
    different repairs: a key that was never added, a key that was emptied, and a
    key holding a value of the wrong type.
    """
    if not isinstance(entries, (list, tuple)):
        raise ProhibitedSymbolPolicyError(
            f"{origin} must be a list of strings, got {type(entries).__name__}; "
            "a prohibition that cannot be read is not a prohibition that permits everything"
        )
    if not entries:
        raise ProhibitedSymbolPolicyError(
            f"{origin} is empty; an empty prohibition passes every input, which is a check "
            "that cannot fail rather than a policy that allows everything (R-GEA-4)"
        )
    symbols = tuple(entry.strip() for entry in entries if isinstance(entry, str) and entry.strip())
    if len(symbols) != len(entries):
        raise ProhibitedSymbolPolicyError(f"{origin} must hold only non-empty strings, got {list(entries)!r}")
    return symbols


def load_prohibited_symbols(policy_path: Path | None = None) -> tuple[str, ...]:
    """Read ``synthesis.prohibited_imports``, refusing any list that cannot judge.

    ``policy_path`` is optional for the same reason it is optional on every
    accessor in ``policy_loader``: a caller that must point the check at a
    temporary policy (a test, an adopter with a supplied policy) says so, and
    the default resolves to the harness policy. ``load_policy`` already raises
    on a policy that is present and unparseable; this adds the three shapes it
    has no opinion about.
    """
    section = load_policy(policy_path).get(POLICY_SECTION)
    origin = f"policy {POLICY_SECTION}.{POLICY_KEY} at {policy_path or POLICY_PATH}"
    if not isinstance(section, dict) or POLICY_KEY not in section:
        raise ProhibitedSymbolPolicyError(
            f"{origin} is missing; refusing to judge a generated module against a list that "
            "does not exist, which would admit every prohibited import"
        )
    symbols = _validated_symbols(section[POLICY_KEY], origin)
    logger.debug("loaded %d prohibited symbol(s) from %s", len(symbols), policy_path or POLICY_PATH)
    return symbols


def _validated_suffixes(entries: object, origin: str) -> frozenset[str]:
    """Reject every shape of the suffix list that could leave a write unjudged.

    Case is folded because the filesystem hands back whatever the model typed and
    ``EVIL.PYW`` is the same file as ``evil.pyw``; the leading dot is required
    because ``Path.suffix`` produces one, and an entry without it would match
    nothing while looking like it matched everything.
    """
    if not isinstance(entries, list) or not entries:
        raise ProhibitedSymbolPolicyError(
            f"{origin} must be a non-empty list, got {entries!r}; a suffix list that names nothing "
            f"leaves every generated write unchecked against {POLICY_SECTION}.{POLICY_KEY}"
        )
    for entry in entries:
        if not isinstance(entry, str) or not entry.startswith(".") or entry != entry.strip():
            raise ProhibitedSymbolPolicyError(f"{origin} entries must be dotted suffixes, got {entry!r}")
    return frozenset(entry.lower() for entry in entries)


def load_python_write_suffixes(policy_path: Path | None = None) -> frozenset[str]:
    """Read ``synthesis.python_write_suffixes``, refusing a policy that lost it.

    Which suffixes count is policy rather than a literal, because it decides
    whether a write is judged at all: pinning ``.py`` alone closes the argument
    axis (``language``, ``validate_syntax``) and leaves the filename axis open,
    and ``.pyw`` is executable Python. Absent policy file, built-in default --
    the adopter path. Present policy that lost the key, refusal: a plausible
    substitute would narrow a security check to whatever this module says.
    """
    path = POLICY_PATH if policy_path is None else policy_path
    if policy_file_is_absent(path):
        logger.debug("no policy file at %s; using built-in Python write suffixes", path)
        return DEFAULT_PYTHON_WRITE_SUFFIXES
    section = load_policy(path).get(POLICY_SECTION)
    origin = f"policy {POLICY_SECTION}.{PYTHON_SUFFIX_KEY} at {path}"
    if not isinstance(section, dict) or PYTHON_SUFFIX_KEY not in section:
        raise ProhibitedSymbolPolicyError(
            f"{origin} is missing; refusing to guess which writes are Python, which would "
            f"skip the {POLICY_SECTION}.{POLICY_KEY} check on every suffix it failed to name"
        )
    suffixes = _validated_suffixes(section[PYTHON_SUFFIX_KEY], origin)
    logger.debug("loaded %d Python write suffix(es) from %s", len(suffixes), path)
    return suffixes


def prohibited_symbol_findings(tree: ast.Module, prohibited: Sequence[str]) -> list[ProhibitedSymbol]:
    """Every reference in ``tree`` reaching one of ``prohibited``, in source order.

    Takes an already-parsed module rather than source text, deliberately: the
    write door holds the tree, and a second ``ast.parse`` would ask the same
    question twice with two chances to answer it differently (R-GEA-3).

    ``prohibited`` is re-validated here rather than trusted from the caller, so
    a direct caller that assembles its own list fails closed on the same three
    shapes :func:`load_prohibited_symbols` refuses. Validating at this boundary
    rather than inside ``code_symbols`` is what lets that half take its list as
    given: there is one door, and everything past it has already been checked.
    """
    return symbol_findings(tree, _validated_symbols(prohibited, "prohibited symbol list"))


def _describe(finding: ProhibitedSymbol) -> str:
    """One finding as the denial spells it, naming the rename when there was one."""
    if finding.reference == finding.policy_entry:
        return f"{finding.policy_entry} (line {finding.lineno})"
    return f"{finding.policy_entry} as {finding.reference} (line {finding.lineno})"


def prohibited_symbol_denial(tree: ast.Module, policy_path: Path | None = None) -> str | None:
    """Why a write door must refuse this module, or ``None`` to let it through.

    One call for a write door: load the policy, judge the tree, render the
    sentence. Composing it here is what keeps the wiring in ``tool_executors``
    -- a protected path -- to four lines, and what lets the next write door
    adopt the check without restating any of it.
    """
    findings = prohibited_symbol_findings(tree, load_prohibited_symbols(policy_path))
    if not findings:
        return None
    plural = "symbols" if len(findings) > 1 else "symbol"
    detail = "; ".join(_describe(finding) for finding in findings)
    return f"names prohibited {POLICY_SECTION}.{POLICY_KEY} {plural}: {detail}"


__all__ = [
    "BUILTINS_NAMESPACE",
    "DEFAULT_PYTHON_WRITE_SUFFIXES",
    "POLICY_KEY",
    "POLICY_SECTION",
    "PYTHON_SUFFIX_KEY",
    "ProhibitedSymbol",
    "ProhibitedSymbolPolicyError",
    "load_prohibited_symbols",
    "load_python_write_suffixes",
    "prohibited_symbol_denial",
    "prohibited_symbol_findings",
]
