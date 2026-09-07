"""What a name provably holds at one point in a function.

This is the analysis half of the approval-flag scan. ``authority_call_sites``
asks the questions -- *is the mapping this call hands the broker one the calling
function built?* -- and this module answers them. Nothing here knows what a
broker is, what ``human_approved`` means, or what a witness looks like; every
function below answers one question about source: **what does this name hold
when control reaches this point, and can that be shown?**

The two halves are one deliverable (R-GEA-2) and were split because together
they exceed ``limits.size_budget_lines`` in ``governance-policy.json``. The seam
is the one NS-39 item 4 named rather than a line count: the resolver is the part
a reader must trust for the security property, so it sits in a module short
enough to read end to end, and the reporting half is left free to say what a
resolved mapping *means*.

**Absence is the safe state.** Every entry point here returns either a value it
can prove or the reason it cannot -- never a silent default. "Cannot show" must
read as "reports", never as "passes", because a resolver that answers *unknown*
and *fine* with the same value turns an unverified property into a verified one
for free. That is also why the refusal vocabulary -- :class:`AuthorityGraphError`
and :class:`EmptyDerivationError` -- is declared in this module rather than
above it: it is the lowest of the three, so ``authority_call_sites`` and
``authority_graph`` both import the vocabulary downwards and the dependency
between the three cannot cycle.

**Position and parameters are the two halves the first version got wrong**, and
each let it report *clean* on code that is not. It read every assignment in a
body regardless of where the assignment sat, so a literal written *after* a
broker call laundered the value passed *to* it; and it read a parameter as
merely unbound rather than as the caller's own value. :func:`_runs_before` and
:func:`_parameter_names` are those two halves, each naming the shape it refuses
(DEC-065).

**A name can also hold the broker method itself.** ``invoke =
broker.execute_command`` binds a callable, not a mapping, and the reporting half
needs to know it: a call through ``invoke`` is a broker call under another name.
:meth:`Scope.bind` records such a name in :attr:`Scope.aliases` and the
expression it consumed in :attr:`Scope.alias_values`, which is how the reporting
half tells a *followed* reference from one that leaves.

Spec: ``docs/specs/graph-engineering-adoption.md`` (R-GEA-2, R-GEA-4, C-GEA-1,
C-GEA-2). Standard library only; C-GEA-1 forbids a new dependency and there is
nothing here a dependency would do better.
"""

from __future__ import annotations

import ast
import logging
from collections.abc import Iterator
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)

#: The broker door the agent path goes through. ``_policy_decision`` is
#: deliberately absent: it receives the context as a *parameter*, which is the
#: PDP's own plumbing rather than a caller constructing one, and flagging it
#: would report the design as a defect on every run.
BROKER_ENTRY_POINTS = frozenset({"execute_command"})

#: Methods that add a key to a mapping already bound to a name. A name they are
#: called on is treated as unreadable rather than re-analysed: ``update`` can
#: merge a caller-supplied mapping, which is precisely the shape being hunted.
KEY_ADDING_METHODS = frozenset({"update", "setdefault"})

#: Where a statement sits: one ``(id(owner), field, index)`` step per nesting
#: level from the function body down. Two statements share a block when their
#: paths agree on every step but the last -- the only case in which source order
#: is also execution order. Without it a binding answers "what is this name
#: assigned *somewhere*" when the question is "what does it hold *here*".
Position = tuple[tuple[int, str, int], ...]

#: What owns a :class:`Scope`. A ``lambda`` and a ``class`` body are absent
#: deliberately: neither gets a scope, so a call inside one resolves nothing.
ScopeOwner = ast.Module | ast.FunctionDef | ast.AsyncFunctionDef

#: The AST field shapes holding a statement list. ``except`` handlers and
#: ``match`` cases are here because they are *not* ``ast.stmt``: read as
#: expression fields their assignments go unrecorded, so a name rebound only in
#: an ``except`` branch looks singly-bound and the resolver hands back the
#: ``try`` branch's literal as the value at the call.
_BLOCK_KINDS = (ast.stmt, ast.excepthandler, ast.match_case)

#: Statements that open a binding scope of their own. The visitor gives each
#: its own :class:`Scope`; a binding credited to the enclosing function is how
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


def names_entry_point(expr: ast.expr) -> bool:
    """Whether ``expr`` reads a broker entry point by name.

    True for ``broker.execute_command`` and for a bare ``execute_command``,
    whether the expression is being called, bound to a name, or handed to
    something else -- the three cases the reporting half has to tell apart. The
    match is on the *final* name only: this analysis does not know which object
    a receiver holds, and a rule that demanded one would miss the receiver it
    could not name rather than the call it could.
    """
    if isinstance(expr, ast.Attribute):
        return expr.attr in BROKER_ENTRY_POINTS
    return isinstance(expr, ast.Name) and expr.id in BROKER_ENTRY_POINTS


def _literal_key(node: ast.expr | None) -> str | None:
    """The string a dict key or subscript is, or ``None`` when it is not one.

    ``None`` covers both a ``**`` spread inside a dict display (whose key node
    *is* ``None``) and a computed key, and both mean the same thing here: the
    key set cannot be read, so the mapping is not closed.
    """
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    return None


@dataclass(frozen=True)
class Binding:
    """One assignment, with the block position at which it takes effect.

    The position is half the value: a binding without one answers "is this name
    assigned to a literal *somewhere* in this function", which is the question
    the unsound first version asked and the reason its zero carried no
    information. Frozen because a recorded binding is evidence about a point in
    the source; rebinding a name records a *second* :class:`Binding` and taints
    the name rather than editing the first.
    """

    value: ast.expr
    position: Position


@dataclass
class Scope:
    """What one function binds, as far as this analysis can read it.

    Absence is the safe state: a name with no binding here -- a loop variable, a
    ``with ... as`` target, a walrus, an import -- resolves to nothing and is
    reported. Presence in :attr:`parameters` is *worse*: the caller chose that
    value, and reading it as merely unreadable reads the same as
    unknown-and-fine.

    :attr:`positions` maps ``id(node)`` to the block the node's statement sits
    in, and :attr:`alias_values` holds ``id(expr)`` for consumed alias
    right-hand sides. Both key on identity rather than equality because two
    textually identical expressions are two different points in the source, and
    it is the point that is being asked about.
    """

    name: str
    parameters: set[str] = field(default_factory=set)
    bindings: dict[str, Binding] = field(default_factory=dict)
    extra_keys: dict[str, dict[str, ast.expr]] = field(default_factory=dict)
    tainted: set[str] = field(default_factory=set)
    positions: dict[int, Position] = field(default_factory=dict)
    #: Names this function binds to a broker entry point itself. A call through
    #: one is a broker call site under another name.
    aliases: set[str] = field(default_factory=set)
    #: ``id(expr)`` of every reference an alias binding consumed, so the
    #: reporting half can tell ``invoke = broker.execute_command`` -- followed --
    #: from ``register(broker.execute_command)``, which leaves this scan.
    alias_values: set[int] = field(default_factory=set)

    def bind(self, name: str, value: ast.expr, position: Position) -> None:
        """Record ``name = value``, taken to hold from ``position`` onwards.

        A rebound name is tainted rather than overwritten: which of two values
        reaches the call is a flow question this analysis does not answer, and
        answering it by keeping the last one seen is how a literal assigned
        after a broker call came to stand in for the mapping the broker was
        handed.

        A name bound to the broker method itself is also recorded as an alias.
        That binding is fail-closed by design: it counts wherever it sits, under
        an ``if`` or after the call, because the question an alias raises is
        "could this name be the method here", and a *maybe* is a yes.
        """
        if name in self.bindings:
            self.tainted.add(name)
        self.bindings[name] = Binding(value=value, position=position)
        if names_entry_point(value):
            self.aliases.add(name)
            self.alias_values.add(id(value))

    def bind_key(self, name: str, key: str | None, value: ast.expr) -> None:
        """Record ``name[key] = value``. A key this analysis cannot read taints.

        A literal-key subscript assignment is kept whatever its position: it
        widens the key set by at most that one key wherever it sits, which is
        what lets ``kwargs["timeout"] = timeout`` under an ``if`` -- correct
        code, at the one live call site -- resolve instead of reporting. A
        computed key could be any key, including the flag, so it taints.
        """
        if key is None:
            self.tainted.add(name)
            return
        self.extra_keys.setdefault(name, {})[key] = value


def _parameter_names(owner: ScopeOwner) -> set[str]:
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


def _runs_before(binding: Position, call: Position) -> bool:
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


def _own_nodes(value: object) -> Iterator[ast.AST]:
    """Every node inside one non-block field, without entering a nested scope.

    A nested ``def`` gets its own :class:`Scope` from the visitor, so walking
    into one here would attribute its bindings to the enclosing function -- and
    a binding attributed to the wrong scope is how a forwarded mapping comes to
    look like a dict literal. A ``lambda`` is skipped for the same reason and
    gets no scope at all, so a call inside one resolves no name and is reported.
    """
    stack = [item for item in (value if isinstance(value, list) else [value]) if isinstance(item, ast.AST)]
    while stack:
        node = stack.pop()
        if isinstance(node, (*_NESTED_SCOPES, ast.Lambda)):
            continue
        yield node
        stack.extend(ast.iter_child_nodes(node))


def _record_target(scope: Scope, target: ast.expr, value: ast.expr, position: Position) -> None:
    """Record one assignment target. Unreadable shapes are simply not recorded.

    Two target shapes are readable -- a bare name and ``name[key]`` -- and each
    has a method on :class:`Scope` saying what recording it means. Everything
    else (tuple unpacking, an attribute, a starred target) is left unrecorded,
    so the name stays unbound and every question about it is answered by a
    refusal.
    """
    if isinstance(target, ast.Name):
        scope.bind(target.id, value, position)
    elif isinstance(target, ast.Subscript) and isinstance(target.value, ast.Name):
        scope.bind_key(target.value.id, _literal_key(target.slice), value)


def _record_statement(scope: Scope, statement: ast.AST, position: Position) -> None:
    """Record what one statement binds at ``position``.

    ``x += y`` taints rather than binds: the value it produces depends on what
    ``x`` already held, which is the flow question this analysis does not
    answer. ``context |= overrides`` is that shape and merges a whole mapping.
    """
    if isinstance(statement, ast.Assign):
        for target in statement.targets:
            _record_target(scope, target, statement.value, position)
    elif isinstance(statement, ast.AnnAssign) and statement.value is not None:
        _record_target(scope, statement.target, statement.value, position)
    elif isinstance(statement, ast.AugAssign) and isinstance(statement.target, ast.Name):
        scope.tainted.add(statement.target.id)


def _read_block(parent: ast.AST, field_name: str, body: list[ast.AST], prefix: Position, scope: Scope) -> None:
    """Index one statement list: what each statement binds, and where it sits.

    A statement list reached through a block field -- a body, an ``else``, an
    ``except`` handler, a ``match`` case -- is one nesting level deeper and is
    read recursively. Every node in a non-block field inherits its statement's
    position instead, which is how a broker call buried in a ``return`` or in an
    ``if`` test is later placed relative to the assignments around it.
    """
    for index, statement in enumerate(body):
        if isinstance(statement, _NESTED_SCOPES):
            continue
        position = (*prefix, (id(parent), field_name, index))
        _record_statement(scope, statement, position)
        for name, value in ast.iter_fields(statement):
            if isinstance(value, list) and value and isinstance(value[0], _BLOCK_KINDS):
                _read_block(statement, name, value, position, scope)
                continue
            for node in _own_nodes(value):
                scope.positions[id(node)] = position
                mutated = _mutated_name(node)
                if mutated is not None:
                    scope.tainted.add(mutated)


def build_scope(owner: ScopeOwner, name: str) -> Scope:
    """Read one function (or the module) into a :class:`Scope`.

    The signature is read before the body, because a parameter outranks every
    binding: a function that reassigns its ``context`` parameter to a literal is
    still reported, and that over-report is deliberate (DEC-065). No first-party
    module has the shape, and fail-closed is the only direction this may err in.
    """
    scope = Scope(name=name, parameters=_parameter_names(owner))
    _read_block(owner, "body", list(owner.body), (), scope)
    logger.debug(
        "Scope %s: %s parameter(s), %s binding(s), %s alias(es)",
        name,
        len(scope.parameters),
        len(scope.bindings),
        len(scope.aliases),
    )
    return scope


def _binding_at(name: str, scope: Scope, at: Position | None) -> tuple[ast.expr | None, str]:
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


def mapping_entries(expr: ast.expr, scope: Scope, at: Position | None) -> tuple[dict[str, ast.expr] | None, str]:
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


__all__ = [
    "BROKER_ENTRY_POINTS",
    "KEY_ADDING_METHODS",
    "AuthorityGraphError",
    "Binding",
    "EmptyDerivationError",
    "Position",
    "Scope",
    "ScopeOwner",
    "build_scope",
    "mapping_entries",
    "names_entry_point",
]
