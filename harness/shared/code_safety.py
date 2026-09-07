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

**The defect this prevents is a checker that decides two of five entries.** The
policy key is called ``prohibited_imports``, and the obvious reading of that
name is a walk over ``ast.Import`` / ``ast.ImportFrom``. Its five entries span
three shapes: ``subprocess`` and ``importlib`` are importable modules;
``os.system`` and ``shutil.rmtree`` are attribute targets reachable through a
bare ``import os``; and ``__import__`` is a builtin that no import statement
ever names. An import-only checker passes the last three in silence, reporting
success against a policy it is not enforcing -- the vacuity failure arriving
through the front door.

Single-module decidable by construction (C-GEA-3): everything below reads the
one ``ast.Module`` it is handed plus the policy file. Nothing consults a
repository-wide index, an import graph, or any other file, because a write door
that depends on a stale index denies valid writes.
"""

from __future__ import annotations

import ast
import logging
from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from pathlib import Path

from harness.shared.policy_loader import POLICY_PATH, load_policy

#: Where the prohibition is declared. Named once so the raised errors, the
#: denial text and the reader all spell the policy address the same way.
POLICY_SECTION = "synthesis"
POLICY_KEY = "prohibited_imports"

logger = logging.getLogger(__name__)


class ProhibitedSymbolPolicyError(ValueError):
    """The prohibited-symbol list cannot be used, so no write may be judged by it.

    Raised rather than degraded into "nothing is prohibited" (R-GEA-4). A
    missing key, an empty list, or a list holding something that is not a string
    all make :func:`prohibited_symbol_findings` return ``[]`` for every input --
    a check that cannot fail, which is worse than an absent check because it
    converts an open question into a false assurance.
    """


@dataclass(frozen=True)
class ProhibitedSymbol:
    """One prohibited reference, in the terms the denial has to report.

    ``policy_entry`` is the ``governance-policy.json`` string that matched;
    ``reference`` is what the module actually wrote (``o.system`` under
    ``import os as o``). Both are carried because a denial echoing only the
    policy entry sends the author hunting for a name their source does not
    contain, and one echoing only the reference never names the rule.
    """

    policy_entry: str
    reference: str
    lineno: int


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


def _matched_entry(resolved: str, prohibited: Sequence[str]) -> str | None:
    """The prohibited entry ``resolved`` falls under, most specific first.

    Dotted prefixes match because prohibiting a package and then admitting its
    submodules decides nothing: ``importlib.util`` is ``importlib``, and
    ``subprocess.run`` is ``subprocess``.
    """
    matches = [entry for entry in prohibited if resolved == entry or resolved.startswith(f"{entry}.")]
    return max(matches, key=len) if matches else None


def _star_bindings(module: str, prohibited: Sequence[str]) -> dict[str, str]:
    """What ``from <module> import *`` puts in scope that the policy prohibits.

    A star import binds names this module never spells, so the prohibited
    attributes of the imported module are bound on its behalf. Without it
    ``from os import *`` followed by ``system(...)`` is the one-line bypass.
    """
    bound: dict[str, str] = {}
    for entry in prohibited:
        head, _, attribute = entry.rpartition(".")
        if attribute and head == module:
            bound[attribute] = entry
    return bound


def _import_bindings(tree: ast.Module, prohibited: Sequence[str]) -> dict[str, str]:
    """Map every name the module binds by import to the dotted symbol it stands for.

    This is what turns ``import os as o`` followed by ``o.system(...)`` into the
    policy entry ``os.system``. Without it a checker sees an attribute on a local
    name and decides nothing, which is two of the five entries lost to a rename.
    """
    bindings: dict[str, str] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                # `import a.b` binds `a`; `import a.b as x` binds `x` to `a.b`.
                bindings[alias.asname or alias.name.split(".")[0]] = (
                    alias.name if alias.asname else alias.name.split(".")[0]
                )
        # A relative import (`node.level`) cannot name a top-level distribution,
        # so `from . import subprocess` is a sibling module and not this one.
        elif isinstance(node, ast.ImportFrom) and node.module and not node.level:
            for alias in node.names:
                if alias.name == "*":
                    bindings.update(_star_bindings(node.module, prohibited))
                else:
                    bindings[alias.asname or alias.name] = f"{node.module}.{alias.name}"
    logger.debug("resolved %d import binding(s): %s", len(bindings), bindings)
    return bindings


def _dotted_name(node: ast.expr) -> str | None:
    """The dotted spelling of a ``Name``/``Attribute`` chain, or ``None``.

    ``None`` for anything rooted in a call, subscript or literal (``f().system``):
    resolving those needs values this module does not have, and guessing is how a
    single-module check starts wanting a repository-wide index (C-GEA-3).
    """
    parts: list[str] = []
    current: ast.expr = node
    while isinstance(current, ast.Attribute):
        parts.append(current.attr)
        current = current.value
    if not isinstance(current, ast.Name):
        return None
    parts.append(current.id)
    return ".".join(reversed(parts))


def _maximal_references(tree: ast.Module) -> Iterator[tuple[int, str]]:
    """Yield ``(lineno, dotted)`` for the longest read of each name chain.

    Longest, because ``os.system`` contains ``os``: reporting both would name the
    module twice for one call and bury the entry that actually matched. Reads
    only, because ``subprocess = 1`` binds a local of that name rather than
    reaching the module.
    """
    nested = {id(node.value) for node in ast.walk(tree) if isinstance(node, ast.Attribute)}
    for node in ast.walk(tree):
        if not isinstance(node, (ast.Name, ast.Attribute)) or id(node) in nested:
            continue
        if not isinstance(node.ctx, ast.Load):
            continue
        dotted = _dotted_name(node)
        if dotted is not None:
            yield node.lineno, dotted


def _import_findings(tree: ast.Module, prohibited: Sequence[str]) -> list[ProhibitedSymbol]:
    """Findings for names the module imports outright.

    Reported at the import even when the name is never used: an unused
    prohibited import is still a prohibited import, and the write door judges the
    file's contents rather than its reachable behaviour.
    """
    findings: list[ProhibitedSymbol] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names = [alias.name for alias in node.names]
        elif isinstance(node, ast.ImportFrom) and node.module and not node.level:
            names = [node.module, *(f"{node.module}.{a.name}" for a in node.names if a.name != "*")]
        else:
            continue
        for name in names:
            entry = _matched_entry(name, prohibited)
            if entry is not None:
                findings.append(ProhibitedSymbol(entry, name, node.lineno))
    return findings


def _reference_findings(
    tree: ast.Module, prohibited: Sequence[str], bindings: dict[str, str]
) -> list[ProhibitedSymbol]:
    """Findings for names the module *reads*, resolved through its own imports.

    An unbound head resolves to itself, which is what catches ``__import__``: the
    builtin no import statement ever names, and one of the three shapes an
    import-only checker passes in silence.
    """
    findings: list[ProhibitedSymbol] = []
    for lineno, dotted in _maximal_references(tree):
        head, _, rest = dotted.partition(".")
        resolved = f"{bindings.get(head, head)}.{rest}" if rest else bindings.get(head, head)
        entry = _matched_entry(resolved, prohibited)
        if entry is not None:
            findings.append(ProhibitedSymbol(entry, dotted, lineno))
    return findings


def prohibited_symbol_findings(tree: ast.Module, prohibited: Sequence[str]) -> list[ProhibitedSymbol]:
    """Every reference in ``tree`` reaching one of ``prohibited``, in source order.

    Takes an already-parsed module rather than source text, deliberately: the
    write door holds the tree, and a second ``ast.parse`` would ask the same
    question twice with two chances to answer it differently (R-GEA-3).

    ``prohibited`` is re-validated here rather than trusted from the caller, so
    a direct caller that assembles its own list fails closed on the same three
    shapes :func:`load_prohibited_symbols` refuses.
    """
    symbols = _validated_symbols(prohibited, "prohibited symbol list")
    bindings = _import_bindings(tree, symbols)
    found = [*_import_findings(tree, symbols), *_reference_findings(tree, symbols, bindings)]

    # One entry, one line: `from subprocess import run` matches the `subprocess`
    # entry through both the module and the qualified alias, and a denial that
    # says so twice reads as two defects.
    seen: set[tuple[str, int]] = set()
    unique: list[ProhibitedSymbol] = []
    for finding in sorted(found, key=lambda item: (item.lineno, item.policy_entry)):
        if (finding.policy_entry, finding.lineno) not in seen:
            seen.add((finding.policy_entry, finding.lineno))
            unique.append(finding)
    logger.debug("prohibited-symbol scan produced %d finding(s): %s", len(unique), unique)
    return unique


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
    "POLICY_KEY",
    "POLICY_SECTION",
    "ProhibitedSymbol",
    "ProhibitedSymbolPolicyError",
    "load_prohibited_symbols",
    "prohibited_symbol_denial",
    "prohibited_symbol_findings",
]
