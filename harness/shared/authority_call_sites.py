"""The call-site half of the authority graph: can agent input reach the approval flag?

``policy_decision.decide`` takes ``human_approved``, the single argument that
turns a high-risk DENY into an ALLOW. ``broker.py`` sources it from the
``context`` mapping with an identity check
(``context.get("human_approved", False) is True``, deliberately not truthiness,
because ``bool("false")`` is ``True``), and
``tool_executors.execute_run_command`` builds that mapping as a *literal dict*
holding ``agent_id`` alone. So the agent path cannot reach the flag.

**The property is real, it holds by construction, and nothing asserted it.**
``ExecutionBroker.execute_command`` accepts a caller-supplied ``Mapping``,
forwarding one through ``**kwargs`` is a one-line edit, and no test in this
repository would have gone red (report finding S-2). This module makes the
guarantee machine-checked: R-GEA-2 states that the graph's nodes are *the call
sites that construct a broker context*, and its edge of interest is a value not
literal in the constructing function reaching ``context["human_approved"]``.

Why an AST scan rather than a runtime probe: the property is about what the
source *permits*, not about what one execution did. A runtime test can only
show that the flag was not set on the paths it happened to drive, which is the
same evidence the repository already had.

Why so little is treated as readable: a name is resolved only when it is bound
exactly once, in the same function, to a dict display whose keys are all string
literals. A parameter, a call result, a ``**`` spread, a name bound twice, a
name a ``.update()`` was called on -- each is reported rather than analysed
further. Fail-closed here means over-reporting, and the one shape that must
*not* over-report is the one live call site: ``execute_run_command`` forwards
``**kwargs`` built two lines above, so the scan resolves that binding instead of
flagging every ``**``. A scan that failed on correct code would be switched off.

This module is separate from ``authority_graph`` only because the two halves
together exceed ``limits.size_budget_lines`` in ``governance-policy.json``.
They are one deliverable: ``authority_graph`` re-exports
:func:`approval_flag_reachability`, so R-GEA-2's named module carries the API,
and the shared refusal vocabulary (:class:`AuthorityGraphError` and
:class:`EmptyDerivationError`) is declared here, in the lower of the two, so the
dependency between them runs one way and cannot cycle.

Spec: ``docs/specs/graph-engineering-adoption.md`` (R-GEA-2, R-GEA-4, C-GEA-1,
C-GEA-2). Standard library and first-party imports only.
"""

from __future__ import annotations

import ast
import logging
from collections.abc import Iterable, Iterator
from dataclasses import dataclass, field
from pathlib import Path

logger = logging.getLogger(__name__)

#: The key whose value the broker reads as a human signature. Named once so the
#: scan, the witness messages, and the tests cannot drift from ``broker.py``.
APPROVAL_FLAG = "human_approved"

#: The broker door the agent path goes through. ``_policy_decision`` is
#: deliberately absent: it receives the context as a *parameter*, which is the
#: PDP's own plumbing rather than a caller constructing one, and flagging it
#: would report the design as a defect on every run.
BROKER_ENTRY_POINTS = frozenset({"execute_command"})

#: The name of ``ExecutionBroker.execute_command``'s mapping parameter.
CONTEXT_PARAMETER = "context"

#: Methods that add a key to a mapping already bound to a name. A name they are
#: called on is treated as unreadable rather than re-analysed: ``update`` can
#: merge a caller-supplied mapping, which is precisely the shape being hunted.
KEY_ADDING_METHODS = frozenset({"update", "setdefault"})


class AuthorityGraphError(ValueError):
    """Base for every refusal the authority graph makes. Callers catch one name."""


class EmptyDerivationError(AuthorityGraphError):
    """A derived set came back empty (R-GEA-4).

    An empty node, edge, or call-site set is a broken extractor, not a satisfied
    property: every assertion over it holds for the reason that nothing was
    inspected. This repository has been bitten by that shape three times --
    DEC-024, DEC-052, and a traceability gate that read 6 requirement IDs out of
    412 while printing ``passed``.
    """


@dataclass(frozen=True)
class ApprovalWitness:
    """One call site at which the approval flag could reach the PDP.

    A witness names the site so a failure says *which* call opened the path
    rather than that some call did. ``expression`` is the unparsed source of the
    argument blamed, which is what a reader needs in order to fix it.
    """

    path: str
    line: int
    function: str
    expression: str
    reason: str


@dataclass
class _Scope:
    """What one function binds, as far as this analysis can read it.

    Absence is the safe state: a name with no binding here -- a parameter, a
    loop variable, a ``with ... as`` target, an import -- resolves to nothing
    and is reported. Only a name bound exactly once to a dict literal in this
    function is treated as readable, which is what makes a forwarded mapping a
    witness rather than an unhandled case.
    """

    name: str
    bindings: dict[str, ast.expr] = field(default_factory=dict)
    extra_keys: dict[str, dict[str, ast.expr]] = field(default_factory=dict)
    tainted: set[str] = field(default_factory=set)

    def bind(self, name: str, value: ast.expr) -> None:
        """Record ``name = value``. A rebound name is tainted: which value
        reaches the call is a flow question this analysis does not answer."""
        if name in self.bindings:
            self.tainted.add(name)
        self.bindings[name] = value

    def bind_key(self, name: str, key: str | None, value: ast.expr) -> None:
        """Record ``name[key] = value``. A non-literal key taints the name."""
        if key is None:
            self.tainted.add(name)
            return
        self.extra_keys.setdefault(name, {})[key] = value


def _literal_key(node: ast.expr | None) -> str | None:
    """The string a dict key or subscript is, or ``None`` when it is not one.

    ``None`` covers both a ``**`` spread inside a dict display (whose key node
    *is* ``None``) and a computed key, and both mean the same thing here: the
    key set cannot be read, so the mapping is not closed.
    """
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    return None


def _own_statements(owner: ast.AST) -> Iterator[ast.AST]:
    """Yield what ``owner`` contains without descending into a nested scope.

    A nested ``def`` gets its own :class:`_Scope` from the visitor, so walking
    into one here would attribute its bindings to the enclosing function -- and
    a binding attributed to the wrong scope is how a forwarded mapping comes to
    look like a dict literal.
    """
    stack = list(ast.iter_child_nodes(owner))
    while stack:
        node = stack.pop()
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Lambda)):
            continue
        yield node
        stack.extend(ast.iter_child_nodes(node))


def _mutated_name(node: ast.AST) -> str | None:
    """The name a key-adding method is called on, if this node is such a call."""
    if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
        return None
    if node.func.attr not in KEY_ADDING_METHODS or not isinstance(node.func.value, ast.Name):
        return None
    return node.func.value.id


def _record_target(scope: _Scope, target: ast.expr, value: ast.expr) -> None:
    """Record one assignment target. Unreadable shapes are simply not recorded."""
    if isinstance(target, ast.Name):
        scope.bind(target.id, value)
    elif isinstance(target, ast.Subscript) and isinstance(target.value, ast.Name):
        scope.bind_key(target.value.id, _literal_key(target.slice), value)


def _scope_for(owner: ast.AST, name: str) -> _Scope:
    """Read the bindings of one function (or the module) into a :class:`_Scope`."""
    scope = _Scope(name=name)
    for node in _own_statements(owner):
        if isinstance(node, ast.Assign):
            for target in node.targets:
                _record_target(scope, target, node.value)
        elif isinstance(node, ast.AnnAssign) and node.value is not None:
            _record_target(scope, node.target, node.value)
        elif isinstance(node, ast.AugAssign) and isinstance(node.target, ast.Name):
            scope.tainted.add(node.target.id)
        else:
            mutated = _mutated_name(node)
            if mutated is not None:
                scope.tainted.add(mutated)
    return scope


def _mapping_entries(expr: ast.expr, scope: _Scope) -> tuple[dict[str, ast.expr] | None, str]:
    """The key/value entries ``expr`` provably has, or ``None`` and why not.

    "Provably" is narrow on purpose: a dict display whose keys are all string
    constants, optionally reached through one name bound once in this function
    and extended by literal-key subscript assignment. Anything else returns
    ``None``, because the analysis cannot show the mapping does not carry the
    flag -- and "cannot show" must read as "reports", never as "passes".
    """
    extra: dict[str, ast.expr] = {}
    target = expr
    if isinstance(expr, ast.Name):
        if expr.id in scope.tainted or expr.id not in scope.bindings:
            return None, f"`{ast.unparse(expr)}` is not bound to a dict literal in {scope.name}"
        target = scope.bindings[expr.id]
        extra = scope.extra_keys.get(expr.id, {})
    if not isinstance(target, ast.Dict):
        return None, f"`{ast.unparse(target)}` is not a dict literal"

    entries: dict[str, ast.expr] = {}
    for key, value in zip(target.keys, target.values, strict=True):
        literal = _literal_key(key)
        if literal is None:
            return None, f"`{ast.unparse(target)}` carries a key this analysis cannot read"
        entries[literal] = value
    entries.update(extra)
    return entries, ""


def _context_reason(expr: ast.expr, scope: _Scope) -> str | None:
    """Why ``expr`` could carry the approval flag into the broker, or ``None``."""
    entries, reason = _mapping_entries(expr, scope)
    if entries is None:
        return f"the broker context is not literal here: {reason}, so a caller could supply {APPROVAL_FLAG!r}"
    if APPROVAL_FLAG in entries:
        return f"the broker context names {APPROVAL_FLAG!r} directly"
    return None


def _spread_reason(expr: ast.expr, scope: _Scope) -> str | None:
    """Why a ``**`` argument could carry the approval flag, or ``None``.

    ``execute_run_command`` forwards its arguments this way today, with a dict
    literal built two lines above, so the spread is resolved rather than
    reported. The mutation this guards against is the same call growing a
    ``context`` it did not build.
    """
    entries, reason = _mapping_entries(expr, scope)
    if entries is None:
        return f"the call forwards `**{ast.unparse(expr)}`, a mapping it did not build here: {reason}"
    if APPROVAL_FLAG in entries:
        return f"the forwarded arguments name {APPROVAL_FLAG!r} directly"
    context = entries.get(CONTEXT_PARAMETER)
    if context is None:
        return None
    return _context_reason(context, scope)


def _call_reasons(call: ast.Call, scope: _Scope) -> list[tuple[str, ast.expr]]:
    """Every way this call site could carry the flag, each with the blamed expression."""
    found: list[tuple[str, ast.expr]] = []
    # `execute_command(command, context, ...)`: the context is the second
    # positional slot of the broker's declared signature.
    if len(call.args) > 1:
        reason = _context_reason(call.args[1], scope)
        if reason is not None:
            found.append((reason, call.args[1]))
    for keyword in call.keywords:
        if keyword.arg == CONTEXT_PARAMETER:
            reason = _context_reason(keyword.value, scope)
        elif keyword.arg is None:
            reason = _spread_reason(keyword.value, scope)
        else:
            continue
        if reason is not None:
            found.append((reason, keyword.value))
    return found


def _is_broker_call(node: ast.Call) -> bool:
    """Whether this call goes through a broker entry point, by name."""
    if isinstance(node.func, ast.Attribute):
        return node.func.attr in BROKER_ENTRY_POINTS
    return isinstance(node.func, ast.Name) and node.func.id in BROKER_ENTRY_POINTS


class _BrokerCallSites(ast.NodeVisitor):
    """Collect every broker call with the scope that constructs its context."""

    def __init__(self) -> None:
        self.sites: list[tuple[ast.Call, _Scope]] = []
        self._scopes: list[_Scope] = []

    def _enter(self, node: ast.AST, name: str) -> None:
        self._scopes.append(_scope_for(node, name))
        self.generic_visit(node)
        self._scopes.pop()

    # The capitalised method names below are `ast.NodeVisitor`'s dispatch
    # protocol rather than this module's naming choice.
    def visit_Module(self, node: ast.Module) -> None:
        self._enter(node, "<module>")

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self._enter(node, node.name)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self._enter(node, node.name)

    def visit_Call(self, node: ast.Call) -> None:
        if _is_broker_call(node):
            self.sites.append((node, self._scopes[-1]))
        self.generic_visit(node)


def _scan_source(path: Path) -> tuple[list[ApprovalWitness], int]:
    """Witnesses and inspected call-site count for one file.

    A file that cannot be parsed raises out of ``ast.parse`` rather than being
    skipped: a skipped file is a file the property was not checked on, reported
    as a pass.
    """
    tree = ast.parse(path.read_text(encoding="utf-8"))
    visitor = _BrokerCallSites()
    visitor.visit(tree)
    witnesses = [
        ApprovalWitness(
            path=str(path),
            line=call.lineno,
            function=scope.name,
            expression=ast.unparse(expression),
            reason=reason,
        )
        for call, scope in visitor.sites
        for reason, expression in _call_reasons(call, scope)
    ]
    return witnesses, len(visitor.sites)


def approval_flag_reachability(source_paths: Iterable[Path]) -> list[ApprovalWitness]:
    """Report every broker call site at which ``human_approved`` could be supplied.

    Today ``execute_run_command`` builds a dict literal holding ``agent_id``
    alone, so the result is empty -- and if that function grew a ``context``
    parameter, or forwarded a ``**`` mapping it did not build, the site would
    appear here by name, line, and expression (R-GEA-2, finding S-2).

    Raises when handed no files, or when the scanned corpus contains no broker
    call at all: an empty result from an empty scan is the vacuous pass R-GEA-4
    exists to refuse, and it is the failure mode a path-narrowing typo produces.
    """
    paths = [Path(source) for source in source_paths]
    if not paths:
        raise EmptyDerivationError("no source file was handed to the approval-flag scan; there is nothing to prove")

    witnesses: list[ApprovalWitness] = []
    sites = 0
    for path in paths:
        found, inspected = _scan_source(path)
        witnesses.extend(found)
        sites += inspected

    if not sites:
        raise EmptyDerivationError(
            f"scanned {len(paths)} file(s) and found no call to any of {sorted(BROKER_ENTRY_POINTS)}; "
            "the scan inspected nothing, which is not the same as finding nothing"
        )

    logger.debug("Approval-flag scan: %s file(s), %s broker call site(s)", len(paths), sites)
    for witness in witnesses:
        logger.warning(
            "Approval flag reachable at %s:%s in %s: `%s` -- %s",
            witness.path,
            witness.line,
            witness.function,
            witness.expression,
            witness.reason,
        )
    return sorted(witnesses, key=lambda witness: (witness.path, witness.line, witness.expression))


__all__ = [
    "APPROVAL_FLAG",
    "BROKER_ENTRY_POINTS",
    "CONTEXT_PARAMETER",
    "ApprovalWitness",
    "AuthorityGraphError",
    "EmptyDerivationError",
    "approval_flag_reachability",
]
