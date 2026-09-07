"""What symbols does this parse tree name, and which of them fall under a list.

The half of the prohibited-symbol check that reads Python rather than policy.
``code_safety`` answers "does ``governance-policy.json`` forbid this module";
everything here answers the question underneath it -- "what does this expression
name" -- against a list of dotted entries it is handed and never loads. The seam
is where the two questions stop sharing evidence: nothing below reads a policy
file, and nothing in ``code_safety`` walks an ``ast`` node.

Split out when the two halves together passed ``limits.size_budget_lines``. That
budget is not a formatting rule: the module it splits is the one a write door
calls before every generated write, and a 600-line file where a reviewer must
hold both "which JSON key" and "which AST shape" in their head at once is how a
resolution bug ships looking like a policy decision.

**The defect this prevents is a checker that decides two of five entries.** The
policy key is called ``prohibited_imports``, and the obvious reading of that
name is a walk over ``ast.Import`` / ``ast.ImportFrom``. Its five entries span
three shapes: ``subprocess`` and ``importlib`` are importable modules;
``os.system`` and ``shutil.rmtree`` are attribute targets reachable through a
bare ``import os``; and ``__import__`` is a builtin that no import statement
ever names. An import-only checker passes the last three in silence, reporting
success against a policy it is not enforcing -- the vacuity failure arriving
through the front door.

The same entry has a second spelling, and matching it is why :func:`_spellings`
exists: every builtin is also an attribute of the ``builtins`` module, so
``builtins.__import__("os")`` reaches ``__import__`` through a name the bare
entry neither equals nor prefixes. A checker that compares prefixes alone is
one ``import builtins`` away from deciding nothing about that entry.

**The second defect this prevents is a bypass one builtin wide.**
``os.system(...)`` and ``getattr(os, "system")(...)`` reach the same attribute,
and only the first is an ``ast.Attribute``: a checker reading attribute chains
alone sees ``getattr`` and ``os``, neither of which any entry names, and writes
the file -- ``getattr(builtins, "__import__")("os")`` past the same door. A
reflective read with a literal key is therefore resolved to the name it computes
and matched exactly as a direct reference is, through the same bindings and the
same ``builtins`` normalisation. A key the module *computes* is judged by a
deliberately narrower rule, for a reason :func:`_computed_key_findings` states.

Single-module decidable by construction (C-GEA-3): everything below reads the
one ``ast.Module`` it is handed plus the list it is passed. Nothing consults a
repository-wide index, an import graph, or any other file, because a write door
that depends on a stale index denies valid writes.
"""

from __future__ import annotations

import ast
import logging
from collections.abc import Iterator, Sequence
from dataclasses import dataclass

#: The namespace that gives every builtin a second, dotted spelling. This is a
#: language fact rather than a policy value -- ``builtins`` is what CPython
#: calls the module holding ``__import__``, in the same sense that
#: ``encoding="utf-8"`` is a fact and not a threshold -- so naming it here
#: duplicates no ``governance-policy.json`` key and states no limit.
BUILTINS_NAMESPACE = "builtins"

#: The builtin that writes an attribute lookup as a string. Another language
#: fact rather than a policy value, on the same footing as
#: ``BUILTINS_NAMESPACE``: ``getattr`` is what CPython calls the two-argument
#: form of ``a.b``, so naming it here duplicates no key and states no limit.
REFLECTIVE_ACCESSOR = "getattr"

#: How a denial spells a key it cannot read. The line and the base are what the
#: author has to act on; inventing an attribute name would be a guess.
COMPUTED_KEY = "<computed>"

logger = logging.getLogger(__name__)


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


def _spellings(resolved: str) -> tuple[str, ...]:
    """``resolved`` plus the equivalent name a prefix comparison would miss.

    **The defect this prevents is a two-line detour through ``builtins``.**
    ``import builtins`` then ``builtins.__import__("os")``, and ``from builtins
    import __import__ as load`` then ``load("os")``, both resolve to
    ``builtins.__import__`` -- a name that is neither equal to the
    ``__import__`` entry nor prefixed by it, so a prefix-only comparison let
    either one past the one entry the policy declares *because* no import
    statement names it. Stripping the namespace is general rather than a case
    for ``__import__``: it holds for every builtin a future entry might name.

    The inverse -- a module that binds its own ``builtins`` and reads an
    attribute off it -- is denied by the same rule. That is the direction a
    write door errs in: a denial an author can read and rename around costs one
    cycle, while admitting the bypass costs the check.
    """
    prefix = f"{BUILTINS_NAMESPACE}."
    return (resolved, resolved[len(prefix) :]) if resolved.startswith(prefix) else (resolved,)


def _matched_entry(resolved: str, prohibited: Sequence[str]) -> str | None:
    """The prohibited entry ``resolved`` falls under, most specific first.

    Dotted prefixes match because prohibiting a package and then admitting its
    submodules decides nothing: ``importlib.util`` is ``importlib``, and
    ``subprocess.run`` is ``subprocess``. Every spelling of ``resolved`` is
    tried, so the ``builtins.`` namespace is not a way around the comparison.
    """
    matches = [
        entry
        for spelling in _spellings(resolved)
        for entry in prohibited
        if spelling == entry or spelling.startswith(f"{entry}.")
    ]
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


def _resolve(dotted: str, bindings: dict[str, str]) -> str:
    """``dotted`` with its head rewritten through the module's own imports.

    An unbound head resolves to itself, which is what catches ``__import__``: the
    builtin no import statement ever names, and one of the three shapes an
    import-only checker passes in silence.
    """
    head, _, rest = dotted.partition(".")
    bound = bindings.get(head, head)
    return f"{bound}.{rest}" if rest else bound


def _reflective_read(node: ast.Call, bindings: dict[str, str]) -> tuple[str, ast.expr, ast.expr] | None:
    """``(callee, base, key)`` when ``node`` reads an attribute through ``getattr``.

    Two arguments or more, because ``getattr(os, "system", None)`` reaches the
    same attribute as the two-argument form. The callee counts as written, as
    bound, or with the ``builtins.`` namespace stripped: comparing the written
    name alone is the prefix-only mistake :func:`_spellings` exists to prevent,
    one level up, and would let ``builtins.getattr(os, "system")`` and ``from
    builtins import getattr as g`` past. Keeping the written name as well denies
    a module that imports its own ``getattr``, the same inverse direction, and
    for the same reason. It is returned as the module spelled it so the denial
    quotes the line rather than a canonical form the file does not contain.
    """
    if len(node.args) < 2:
        return None
    called = _dotted_name(node.func)
    if called is None or REFLECTIVE_ACCESSOR not in {called, *_spellings(_resolve(called, bindings))}:
        return None
    return called, node.args[0], node.args[1]


def _reflective_reference(node: ast.expr, bindings: dict[str, str]) -> tuple[str, str] | None:
    """``(spelling, resolved)`` for a name chain, reading literal ``getattr`` links as attributes.

    The recursion is what makes the two spellings one check: a link resolves
    whether it was written ``a.b`` or ``getattr(a, "b")``, and attributes read
    off the result keep resolving, so ``getattr(getattr(os, "path"), "join")``
    and ``getattr(os, "system").__call__`` produce exactly the names
    ``os.path.join`` and ``os.system.__call__`` do.

    Two strings rather than one, for the reason :class:`ProhibitedSymbol` carries
    two: ``resolved`` is what the policy is compared against, and ``spelling`` is
    what the author has to find in their file -- a denial naming ``os.system``
    against a line whose text is ``getattr(os, "system")`` sends them hunting.
    """
    dotted = _dotted_name(node)
    if dotted is not None:
        return dotted, _resolve(dotted, bindings)
    if isinstance(node, ast.Attribute):
        read_off = _reflective_reference(node.value, bindings)
        return None if read_off is None else (f"{read_off[0]}.{node.attr}", f"{read_off[1]}.{node.attr}")
    if not isinstance(node, ast.Call):
        return None
    read = _reflective_read(node, bindings)
    if read is None:
        return None
    callee, base, key = read
    if not (isinstance(key, ast.Constant) and isinstance(key.value, str)):
        return None
    resolved_base = _reflective_reference(base, bindings)
    if resolved_base is None:
        return None
    spelling, resolved = resolved_base
    return f'{callee}({spelling}, "{key.value}")', f"{resolved}.{key.value}"


def _maximal_references(tree: ast.Module, bindings: dict[str, str]) -> Iterator[tuple[int, str, str]]:
    """Yield ``(lineno, spelling, resolved)`` for the longest read of each name chain.

    Longest, because ``os.system`` contains ``os``: reporting both would name the
    module twice for one call and bury the entry that actually matched. The base
    of a resolved reflective read is consumed by that same rule, being part of a
    longer chain exactly as the value of an ``ast.Attribute`` is, so
    ``getattr(subprocess, "run")`` is reported once, against the entry the whole
    chain matched, in the spelling the module wrote. Consuming it can never lose
    a finding: :func:`_matched_entry` matches on dotted prefixes, so whatever the
    base matched, the longer chain built from it matches too.

    Reads only, because ``subprocess = 1`` binds a local of that name rather than
    reaching the module.
    """
    consumed: set[int] = set()
    reflective: dict[int, tuple[int, str, str]] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute):
            consumed.add(id(node.value))
        elif isinstance(node, ast.Call):
            reference = _reflective_reference(node, bindings)
            if reference is not None:
                spelling, resolved = reference
                reflective[id(node)] = (node.lineno, spelling, resolved)
                consumed.add(id(node.args[0]))
    for node in ast.walk(tree):
        if id(node) in consumed:
            continue
        found = reflective.get(id(node))
        if found is not None:
            yield found
        elif isinstance(node, (ast.Name, ast.Attribute)) and isinstance(node.ctx, ast.Load):
            reference = _reflective_reference(node, bindings)
            if reference is not None:
                yield node.lineno, reference[0], reference[1]


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

    Both spellings of a read reach here, the attribute chain and the reflective
    one, because :func:`_maximal_references` resolves them to the same dotted
    name before either is compared: one matcher, one list, two ways of typing
    the same call.
    """
    findings: list[ProhibitedSymbol] = []
    for lineno, spelling, resolved in _maximal_references(tree, bindings):
        entry = _matched_entry(resolved, prohibited)
        if entry is not None:
            findings.append(ProhibitedSymbol(entry, spelling, lineno))
    return findings


def _entries_under(base: str, prohibited: Sequence[str]) -> list[str]:
    """Every prohibited entry a *computed* attribute of ``base`` could name.

    Two ways an entry sits under a base, matching the two ways
    :func:`_matched_entry` accepts a name. ``os.system`` sits under ``os`` by
    being spelled that way. And every single-segment entry sits under
    ``builtins``, because that namespace is what gives it a second spelling:
    refusing ``builtins.__import__`` while admitting ``getattr(builtins, name)``
    would leave the one entry the policy declares *because* no import statement
    names it reachable by the computed form of the detour :func:`_spellings`
    already closes.

    An entry equal to the base is deliberately absent. Reading any attribute of
    ``subprocess`` requires reading ``subprocess``, which is a finding of its own
    on that same line, and one line denied for two reasons reads as two defects.
    """
    under = [entry for entry in prohibited if entry.startswith(f"{base}.")]
    if base == BUILTINS_NAMESPACE:
        under += [entry for entry in prohibited if "." not in entry]
    return under


def _computed_key_findings(
    tree: ast.Module, prohibited: Sequence[str], bindings: dict[str, str]
) -> list[ProhibitedSymbol]:
    """Findings for ``getattr(<base>, <expression>)`` -- a key this module cannot read.

    **The defect this prevents is a check somebody switches off.** The
    fail-closed reading of an unreadable key looks like "report every one of
    them", and it is the wrong one: ``getattr(self, name)`` and
    ``getattr(obj, attr)`` are how ordinary Python reaches a field chosen at
    runtime, so a rule that fires on them denies correct code at the write door
    -- and a check that denies correct code is removed rather than satisfied,
    which costs the four literal shapes above along with this one.

    So a computed key is reported only where the list forbids something under the
    base it is read from: ``getattr(os, name)`` can reach ``os.system`` and is
    refused, while ``getattr(self, name)`` reaches nothing any entry names and
    passes. The entry is named without an attribute, because the attribute is the
    part that was never written down -- the author is being told which rule this
    line can break, not which call they made.

    The residual is stated rather than hidden: a base that does not resolve to a
    dotted name (``getattr(load(), name)``) is not judged, for the same reason
    ``f().system`` is not -- resolving it needs values a single-module check does
    not have (C-GEA-3).
    """
    findings: list[ProhibitedSymbol] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        read = _reflective_read(node, bindings)
        if read is None:
            continue
        callee, base, key = read
        if isinstance(key, ast.Constant) and isinstance(key.value, str):
            continue  # A literal key names one attribute, and _maximal_references resolved it.
        resolved_base = _reflective_reference(base, bindings)
        if resolved_base is None:
            continue
        spelling, resolved = resolved_base
        for entry in _entries_under(resolved, prohibited):
            logger.debug("a computed key on %r could name the prohibited %r", resolved, entry)
            findings.append(ProhibitedSymbol(entry, f"{callee}({spelling}, {COMPUTED_KEY})", node.lineno))
    return findings


def symbol_findings(tree: ast.Module, prohibited: Sequence[str]) -> list[ProhibitedSymbol]:
    """Every reference in ``tree`` reaching one of ``prohibited``, in source order.

    The three walks are one pass over three shapes an entry can be reached by --
    imported outright, read as a chain (dotted or reflective), or reached by a
    key the module computes -- and they are merged rather than short-circuited,
    because a module doing two of them has two defects to report.

    ``prohibited`` is taken as given: the validation that makes an unusable list
    raise instead of passing everything lives with the accessor that loads it,
    in ``code_safety``, so this half has one job and no policy opinions.
    """
    bindings = _import_bindings(tree, prohibited)
    found = [
        *_import_findings(tree, prohibited),
        *_reference_findings(tree, prohibited, bindings),
        *_computed_key_findings(tree, prohibited, bindings),
    ]

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


__all__ = [
    "BUILTINS_NAMESPACE",
    "COMPUTED_KEY",
    "REFLECTIVE_ACCESSOR",
    "ProhibitedSymbol",
    "symbol_findings",
]
