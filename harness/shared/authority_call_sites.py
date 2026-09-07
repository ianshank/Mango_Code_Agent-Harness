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

Why so little is treated as readable: a name resolves only when it is bound
exactly once, in the same function, *at a position that must already have run
when the broker call does*, to a dict display whose keys are all string
literals. A parameter, a call result, a ``**`` spread, a name bound twice, a
name a ``.update()`` was called on, a name assigned only inside an ``if``, a
``for``, or a ``try`` -- each is reported rather than analysed further.

Position and parameters are the two halves the first version got wrong, and
each let it report *clean* on code that is not. It read every assignment in a
body regardless of where the assignment sat, so a literal written *after* a
broker call laundered the value passed *to* it; and it read a parameter as
merely unbound rather than as the caller's own value. An unsound scan reporting
zero witnesses is worse than no scan: it turns "unverified" into "verified"
without doing the work. :func:`_runs_before` and :func:`_parameter_names` are
those two halves, each naming the shape it refuses.

Fail-closed means over-reporting, and the shape that must *not* over-report is
the live call site: ``execute_run_command`` forwards ``**kwargs`` built two
lines above and extended by ``kwargs["timeout"]`` inside an ``if``. A
conditional subscript with a *literal* key widens the key set by at most that
key, so it is read; a conditional *rebinding* is not. A scan that failed on
correct code gets switched off.

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
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path
from typing import NamedTuple

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

#: Where a statement sits: one ``(id(owner), field, index)`` step per nesting
#: level from the function body down. Two statements share a block when their
#: paths agree on every step but the last -- the only case in which source order
#: is also execution order. Without it a binding answers "what is this name
#: assigned *somewhere*" when the question is "what does it hold *here*".
_Position = tuple[tuple[int, str, int], ...]

#: What owns a :class:`_Scope`. A ``lambda`` and a ``class`` body are absent
#: deliberately: neither gets a scope, so a call inside one resolves nothing.
_ScopeOwner = ast.Module | ast.FunctionDef | ast.AsyncFunctionDef

#: The AST field shapes holding a statement list. ``except`` handlers and
#: ``match`` cases are here because they are *not* ``ast.stmt``: read as
#: expression fields their assignments go unrecorded, so a name rebound only in
#: an ``except`` branch looks singly-bound and the resolver hands back the
#: ``try`` branch's literal as the value at the call.
_BLOCK_KINDS = (ast.stmt, ast.excepthandler, ast.match_case)

#: Statements that open a binding scope of their own. The visitor gives each
#: its own :class:`_Scope`; a binding credited to the enclosing function is how
#: a forwarded mapping comes to look like a dict literal.
_NESTED_SCOPES = (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)


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


class _Binding(NamedTuple):
    """One assignment, with the block position at which it takes effect."""

    value: ast.expr
    position: _Position


@dataclass
class _Scope:
    """What one function binds, as far as this analysis can read it.

    Absence is the safe state: a name with no binding here -- a loop variable, a
    ``with ... as`` target, a walrus, an import -- resolves to nothing and is
    reported. Presence in ``parameters`` is *worse*: the caller chose that value.
    """

    name: str
    parameters: set[str] = field(default_factory=set)
    bindings: dict[str, _Binding] = field(default_factory=dict)
    extra_keys: dict[str, dict[str, ast.expr]] = field(default_factory=dict)
    tainted: set[str] = field(default_factory=set)
    positions: dict[int, _Position] = field(default_factory=dict)


def _literal_key(node: ast.expr | None) -> str | None:
    """The string a dict key or subscript is, or ``None`` when it is not one.

    ``None`` covers both a ``**`` spread inside a dict display (whose key node
    *is* ``None``) and a computed key, and both mean the same thing here: the
    key set cannot be read, so the mapping is not closed.
    """
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    return None


def _parameter_names(owner: _ScopeOwner) -> set[str]:
    """Every name the signature binds, ``*args`` and ``**kwargs`` included.

    A parameter is caller-controlled by definition, and the property is "no
    *caller* can supply ``human_approved``" (DEC-065). Reading an unbound name
    as merely unreadable reads the same as unknown-and-fine, so
    ``run(broker, cmd, context)`` forwarding its own ``context`` read clean.
    """
    if isinstance(owner, ast.Module):
        return set()
    args = owner.args
    named = {arg.arg for arg in (*args.posonlyargs, *args.args, *args.kwonlyargs)}
    return named | {arg.arg for arg in (args.vararg, args.kwarg) if arg is not None}


def _runs_before(binding: _Position, call: _Position) -> bool:
    """Whether ``binding`` is guaranteed to have run by the time ``call`` runs.

    True only when the two paths agree on every enclosing block down to one
    they both sit *directly* in, and the binding comes first there. A binding
    nested deeper -- in an ``if``, a ``for``, a ``try`` -- is skipped on some
    path, and one later in a loop body reaches the call on the next iteration.
    With no position at all, a literal assigned *after* a broker call was read
    as the value passed *to* it.
    """
    for depth, (bound, called) in enumerate(zip(binding, call, strict=False)):
        if bound[:2] != called[:2]:
            return False
        if bound[2] != called[2]:
            return bound[2] < called[2] and depth == len(binding) - 1
    return False


def _mutated_name(node: ast.AST) -> str | None:
    """The name a key-adding method is called on, if this node is such a call."""
    if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
        return None
    if node.func.attr not in KEY_ADDING_METHODS or not isinstance(node.func.value, ast.Name):
        return None
    return node.func.value.id


def _record_target(scope: _Scope, target: ast.expr, value: ast.expr, position: _Position) -> None:
    """Record one assignment target. Unreadable shapes are simply not recorded.

    A rebound name is tainted: which value reaches the call is a flow question
    this analysis does not answer. ``name[key] = value`` with a literal key is
    kept whatever its position -- it widens the key set by at most that key
    wherever it sits -- and a computed key taints instead.
    """
    if isinstance(target, ast.Name):
        if target.id in scope.bindings:
            scope.tainted.add(target.id)
        scope.bindings[target.id] = _Binding(value=value, position=position)
    elif isinstance(target, ast.Subscript) and isinstance(target.value, ast.Name):
        key = _literal_key(target.slice)
        if key is None:
            scope.tainted.add(target.value.id)
        else:
            scope.extra_keys.setdefault(target.value.id, {})[key] = value


def _read_block(parent: ast.AST, field_name: str, body: list[ast.AST], prefix: _Position, scope: _Scope) -> None:
    """Index one statement list: what each statement binds, and where it sits.

    Every node in a non-block field inherits its statement's position, which is
    how a broker call buried in a ``return`` or an ``if`` test is later placed
    relative to the assignments around it. A ``lambda`` is not walked into: it
    binds names of its own and gets no :class:`_Scope`. A shape with no readable
    target -- tuple unpacking, ``with ... as``, a walrus -- is left unrecorded,
    so the name stays unbound and is reported.
    """
    for index, statement in enumerate(body):
        if isinstance(statement, _NESTED_SCOPES):
            continue
        position = (*prefix, (id(parent), field_name, index))
        if isinstance(statement, ast.Assign):
            for target in statement.targets:
                _record_target(scope, target, statement.value, position)
        elif isinstance(statement, ast.AnnAssign) and statement.value is not None:
            _record_target(scope, statement.target, statement.value, position)
        elif isinstance(statement, ast.AugAssign) and isinstance(statement.target, ast.Name):
            scope.tainted.add(statement.target.id)
        for name, value in ast.iter_fields(statement):
            if isinstance(value, list) and value and isinstance(value[0], _BLOCK_KINDS):
                _read_block(statement, name, value, position, scope)
                continue
            stack = [item for item in (value if isinstance(value, list) else [value]) if isinstance(item, ast.AST)]
            while stack:
                node = stack.pop()
                if isinstance(node, (*_NESTED_SCOPES, ast.Lambda)):
                    continue
                scope.positions[id(node)] = position
                mutated = _mutated_name(node)
                if mutated is not None:
                    scope.tainted.add(mutated)
                stack.extend(ast.iter_child_nodes(node))


def _binding_at(name: str, scope: _Scope, at: _Position | None) -> tuple[ast.expr | None, str]:
    """The value ``name`` provably holds at ``at``, or ``None`` and why not.

    Every branch but the last is a refusal naming the rule that refused, in
    order of severity: a parameter is not an unhandled shape, it is the hole.
    """
    binding = scope.bindings.get(name)
    if name in scope.parameters:
        reason = f"`{name}` is a parameter of {scope.name}, so its value is the caller's"
    elif name in scope.tainted:
        reason = f"`{name}` is rebound or mutated in {scope.name}"
    elif binding is None:
        reason = f"`{name}` is not bound to a dict literal in {scope.name}"
    elif at is None or not _runs_before(binding.position, at):
        reason = f"`{name}`'s binding in {scope.name} is not guaranteed to have run at this call"
    else:
        logger.debug("Resolved `%s` in %s: its one binding precedes this call unconditionally", name, scope.name)
        return binding.value, ""
    logger.debug("Tainted `%s` in %s: %s", name, scope.name, reason)
    return None, reason


def _mapping_entries(expr: ast.expr, scope: _Scope, at: _Position | None) -> tuple[dict[str, ast.expr] | None, str]:
    """The key/value entries ``expr`` provably has, or ``None`` and why not.

    "Provably" is narrow on purpose: a dict display whose keys are all string
    constants, optionally reached through one name bound once *before ``at``*
    and extended by literal-key subscript assignment. Anything else returns
    ``None``: "cannot show" must read as "reports", never "passes".
    """
    extra: dict[str, ast.expr] = {}
    target = expr
    if isinstance(expr, ast.Name):
        resolved, refusal = _binding_at(expr.id, scope, at)
        if resolved is None:
            return None, refusal
        target = resolved
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


def _context_reason(expr: ast.expr, scope: _Scope, at: _Position | None) -> str | None:
    """Why ``expr`` could carry the approval flag into the broker, or ``None``."""
    entries, reason = _mapping_entries(expr, scope, at)
    if entries is None:
        return f"the broker context is not literal here: {reason}, so a caller could supply {APPROVAL_FLAG!r}"
    if APPROVAL_FLAG in entries:
        return f"the broker context names {APPROVAL_FLAG!r} directly"
    return None


def _spread_reason(expr: ast.expr, scope: _Scope, at: _Position | None) -> str | None:
    """Why a ``**`` argument could carry the approval flag, or ``None``.

    ``execute_run_command`` forwards its arguments this way today, with a dict
    literal built two lines above, so the spread is resolved rather than
    reported. What this guards against is the same call growing a ``context`` it
    did not build -- a bag that *is* a ``**kwargs`` parameter included.
    """
    entries, reason = _mapping_entries(expr, scope, at)
    if entries is None:
        return f"the call forwards `**{ast.unparse(expr)}`, a mapping it did not build here: {reason}"
    if APPROVAL_FLAG in entries:
        return f"the forwarded arguments name {APPROVAL_FLAG!r} directly"
    context = entries.get(CONTEXT_PARAMETER)
    if context is None:
        return None
    return _context_reason(context, scope, at)


def _call_reasons(call: ast.Call, scope: _Scope) -> list[tuple[str, ast.expr]]:
    """Every way this call site could carry the flag, each with the blamed expression.

    The call's block position is looked up once and threaded down. A call with
    no position -- inside a ``lambda`` or a class body, neither of which gets a
    scope -- resolves no name at all: this analysis does not know where it runs.
    """
    at = scope.positions.get(id(call))
    found: list[tuple[str, ast.expr]] = []
    # `execute_command(command, context, ...)`: the context is the second
    # positional slot of the broker's declared signature.
    if len(call.args) > 1:
        reason = _context_reason(call.args[1], scope, at)
        if reason is not None:
            found.append((reason, call.args[1]))
    for keyword in call.keywords:
        if keyword.arg == CONTEXT_PARAMETER:
            reason = _context_reason(keyword.value, scope, at)
        elif keyword.arg is None:
            reason = _spread_reason(keyword.value, scope, at)
        else:
            continue
        if reason is not None:
            found.append((reason, keyword.value))
    return found


def _broker_aliases(node: _ScopeOwner) -> set[str]:
    """Names assigned directly from a broker entry point in this scope."""
    aliases: set[str] = set()
    for candidate in ast.walk(node):
        if isinstance(candidate, _NESTED_SCOPES):
            continue
        if not isinstance(candidate, ast.Assign) or not isinstance(candidate.value, ast.Attribute):
            continue
        if candidate.value.attr not in BROKER_ENTRY_POINTS:
            continue
        for target in candidate.targets:
            if isinstance(target, ast.Name):
                aliases.add(target.id)
    return aliases


def _is_broker_call(node: ast.Call, aliases: set[str]) -> bool:
    """Whether this call goes through a broker entry point, by name."""
    if isinstance(node.func, ast.Attribute):
        return node.func.attr in BROKER_ENTRY_POINTS
    return isinstance(node.func, ast.Name) and (node.func.id in BROKER_ENTRY_POINTS or node.func.id in aliases)


class _BrokerCallSites(ast.NodeVisitor):
    """Collect every broker call with the scope that constructs its context."""

    def __init__(self) -> None:
        self.sites: list[tuple[ast.Call, _Scope]] = []
        self._scopes: list[_Scope] = []
        self._aliases: list[set[str]] = []

    def _enter(self, node: _ScopeOwner, name: str) -> None:
        """Read one function (or the module) into a scope, then visit it."""
        scope = _Scope(name=name, parameters=_parameter_names(node))
        _read_block(node, "body", list(node.body), (), scope)
        logger.debug("Scope %s: %s parameter(s), %s binding(s)", name, len(scope.parameters), len(scope.bindings))
        self._scopes.append(scope)
        aliases = _broker_aliases(node)
        self._aliases.append(aliases)
        self.generic_visit(node)
        self._aliases.pop()
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
        if _is_broker_call(node, self._aliases[-1]):
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
