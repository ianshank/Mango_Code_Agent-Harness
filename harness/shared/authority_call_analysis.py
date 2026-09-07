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
merely unbound rather than as the caller's own value.
:func:`block_positions.runs_before` and :func:`_parameter_names` are those two
halves, each naming the shape it refuses (DEC-065). The first of them lives one
module down: it is a question about the shape of a source file rather than about
a name, and ``block_positions`` imports ``ast`` alone, so the edge to it cannot
be the upward one the split forbids.

**A name can also hold the broker method itself.** ``invoke =
broker.execute_command`` binds a callable, not a mapping, and the reporting half
needs to know it: a call through ``invoke`` is a broker call under another name.
:meth:`Scope.bind` records such a name in :attr:`Scope.aliases` and the
expression it consumed in :attr:`Scope.alias_values`, which is how the reporting
half tells a *followed* reference from one that leaves. The method has a second
spelling, and :func:`names_entry_point` reads both: a *literal*
``getattr(broker, "execute_command")`` names it as decidably as the dot does.

**A mapping can also leave without being rebound.** Handing a tracked name to a
call that is not the one under analysis puts the object itself in a callee this
scan does not read, and adding a key to it is what that callee is free to do.
:attr:`Scope.escaped` is that state, filled by :meth:`Scope.escape_arguments`.
Which calls are modelled is not decidable here -- an alias can be bound one
``def`` out -- so the reporting half, which enumerates the sites, is what calls
it.

Spec: ``docs/specs/graph-engineering-adoption.md`` (R-GEA-2, R-GEA-4, C-GEA-1,
C-GEA-2). Standard library only; C-GEA-1 forbids a new dependency and there is
nothing here a dependency would do better.
"""

from __future__ import annotations

import ast
import logging
from dataclasses import dataclass, field

from harness.shared.block_positions import BLOCK_KINDS, NESTED_SCOPES, Position, own_nodes, runs_before

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

#: How Python spells "read the attribute this string names". A language fact
#: rather than a policy value -- ``getattr`` is what CPython calls the
#: two-argument form of ``a.b`` -- so naming it here duplicates no
#: ``governance-policy.json`` key and states no threshold. ``code_symbols``
#: reads the same spelling and is deliberately not shared with: it resolves the
#: *root* of a chain through the file's imports to compare it against a policy
#: list, and returns nothing when the base does not resolve, which is right for
#: a write door and fail-open here -- ``getattr(get_broker(), "execute_command")``
#: would leave the enumeration. This rule reads the leaf and never the base.
REFLECTIVE_ACCESSOR = "getattr"

#: What owns a :class:`Scope`. A ``lambda`` and a ``class`` body are absent
#: deliberately: neither gets a scope, so a call inside one resolves nothing.
ScopeOwner = ast.Module | ast.FunctionDef | ast.AsyncFunctionDef


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


def _final_name(expr: ast.expr) -> str | None:
    """The last name in a ``Name``/``Attribute`` chain, or ``None`` for anything else.

    Only the last, because this analysis does not know which object a receiver
    holds: ``self._broker.execute_command`` and ``broker.execute_command`` ask
    the same question, and a rule that demanded a particular receiver would miss
    the one it could not name rather than the call it could.
    """
    if isinstance(expr, ast.Attribute):
        return expr.attr
    return expr.id if isinstance(expr, ast.Name) else None


def names_entry_point(expr: ast.expr) -> bool:
    """Whether ``expr`` reads a broker entry point, dotted or reflectively.

    True for ``broker.execute_command``, for a bare ``execute_command``, and for
    ``getattr(broker, "execute_command")`` -- whether the expression is being
    called, bound to a name, or handed to something else, the three cases the
    reporting half has to tell apart. The match is on the final name
    (:func:`_final_name`), of the reference and of the accessor alike.

    **A literal key and a computed key are two different questions, and DEC-065
    answered only one of them.** ``getattr(broker, chosen)`` has no name in the
    source to match and stays out of scope, because deciding it would mean
    knowing what ``broker`` holds -- the one thing this analysis refuses to
    guess, so the same rule would fire on every ``getattr(self, name)`` in the
    repository, and a check that fires on correct code gets switched off. A
    *string literal* is statically decidable, that argument does not reach it,
    and reading it as unmatchable produced no call **and no reference**: silently
    absent on a real corpus while the direct sites kept the non-empty guard
    green. The residual left is narrower and named: an accessor reached under
    another name (``from builtins import getattr as g``) resolves through import
    bindings, which is a question about modules rather than about what a name
    holds at a point, and nothing here builds them.
    """
    if _final_name(expr) in BROKER_ENTRY_POINTS:
        return True
    if not isinstance(expr, ast.Call) or _final_name(expr.func) != REFLECTIVE_ACCESSOR:
        return False
    # Two arguments or more: `getattr(broker, "execute_command", None)` reaches
    # the same method as the two-argument form.
    return len(expr.args) > 1 and _literal_key(expr.args[1]) in BROKER_ENTRY_POINTS


def _literal_key(node: ast.expr | None) -> str | None:
    """The string a dict key, a subscript, or a ``getattr`` key is, or ``None``.

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
    #: Names handed to a call this scan does not model. The callee holds the
    #: mapping itself and may add a key to it, so the name stops being readable
    #: here -- the same conclusion :attr:`tainted` reaches by a different route,
    #: kept apart so a refusal can say which one happened.
    escaped: set[str] = field(default_factory=set)

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

    def escape_arguments(self, call: ast.Call) -> None:
        """Record every name ``call`` receives as an argument as escaped.

        The mutation rules above read the *shapes* that add a key --
        ``.update()``, a subscript, a rebinding -- and a helper is none of them
        while doing exactly the same thing: ``add_approval(context, value)``
        hands the callee the object, and this scan does not read the callee.

        Direct arguments only. ``f(**context)`` and ``f(*context)`` build a fresh
        dict and a fresh tuple out of the mapping and hand the callee *those*, so
        neither can reach the caller's object -- and tainting them would fire on
        ``execute_run_command``'s own ``**kwargs`` forwarding, which is correct
        code. A name nested inside an argument (``f({"c": context})``) is a
        stated residual rather than a closed one, for the symmetric reason:
        chasing it would report every mapping mentioned anywhere in a call.
        """
        for argument in (*call.args, *(keyword.value for keyword in call.keywords if keyword.arg is not None)):
            if isinstance(argument, ast.Name):
                self.escaped.add(argument.id)


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


def _mutated_name(node: ast.AST) -> str | None:
    """The name a key-adding method is called on, if this node is such a call."""
    if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
        return None
    if node.func.attr not in KEY_ADDING_METHODS or not isinstance(node.func.value, ast.Name):
        return None
    return node.func.value.id


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
        if isinstance(statement, NESTED_SCOPES):
            continue
        position = (*prefix, (id(parent), field_name, index))
        _record_statement(scope, statement, position)
        for name, value in ast.iter_fields(statement):
            if isinstance(value, list) and value and isinstance(value[0], BLOCK_KINDS):
                _read_block(statement, name, value, position, scope)
                continue
            for node in own_nodes(value):
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
    elif name in scope.escaped:
        reason = f"`{name}` is handed to a call {scope.name} does not model, which could add a key to it"
    elif binding is None:
        reason = f"`{name}` is not bound to a dict literal in {scope.name}"
    elif at is None or not runs_before(binding.position, at):
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
    "REFLECTIVE_ACCESSOR",
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
