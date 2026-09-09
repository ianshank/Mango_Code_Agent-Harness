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

**An enumeration is only as sound as its membership test.** This scan reports
on the call sites it finds, so a call it does not *recognise* is not a clean
site -- it is an absent one, and absence reads exactly like safety. The first
version recognised a call only by the final attribute name of its callee, so one
line walked past it: bind ``invoke = broker.execute_command``, call ``invoke``,
and the site was never enumerated while the non-empty-scan guard went on passing
on the strength of the five direct sites. Two rules close it. A name this
function binds to the method is an *alias*, and a call through it is a call site
analysed like any other (:meth:`authority_call_analysis.Scope.bind`). A
reference to the method that is **not** called here -- handed to a function,
returned, stored on an object or in a container -- is reported where it leaves,
because it is called somewhere this scan cannot see with a context it cannot
read. Both rules read the reflective spelling too: ``getattr(broker,
"execute_command")`` is the method under a string literal, and a scan that could
not match it found *no call and no reference* for that line rather than a site
it read clean. What is deliberately not chased is a method fetched by a
*computed* name (``getattr(broker, chosen)``): there is no name in the source to
match, and :func:`authority_call_analysis.names_entry_point` states why the two
halves of that sentence are different questions.

**A mapping can leave without being rebound.** The key-adding rules read the
shapes that mutate a name in place -- ``.update()``, a subscript, a rebinding --
and a plain helper is none of them while doing the same thing:
``add_approval(context, value)`` hands the callee the object, and the callee is
not read here. So a tracked name handed to a call this scan does not model is
recorded as escaped (:meth:`authority_call_analysis.Scope.escape_arguments`).
The call *under analysis* is not such a call, and the exemption is decided here
rather than in the analysis half for a reason the closure case shows: ``invoke``
can be bound one ``def`` out, and only :class:`_BrokerCallSites`, which holds the
whole scope stack, can tell that call from an unmodelled one.

Why so little is treated as readable: :func:`authority_call_analysis.mapping_entries`
resolves a name only when it is bound exactly once, in the same function, *at a
position that must already have run when the broker call does*, to a dict
display whose keys are all string literals. A parameter, a call result, a ``**``
spread, a name bound twice, a name a ``.update()`` was called on, a name
assigned only inside an ``if``, a ``for``, or a ``try`` -- each is reported
rather than analysed further. An unsound scan reporting zero witnesses is worse
than no scan: it turns "unverified" into "verified" without doing the work.

Fail-closed means over-reporting, and the shape that must *not* over-report is
the live call site: ``execute_run_command`` forwards ``**kwargs`` built two
lines above and extended by ``kwargs["timeout"]`` inside an ``if``. A
conditional subscript with a *literal* key widens the key set by at most that
key, so it is read; a conditional *rebinding* is not. The alias rule is drawn as
narrowly for the same reason: only a name bound to the method *itself* is
followed, because treating every call through a local name as a broker call
would report every call in the repository. A scan that failed on correct code
gets switched off.

This module is the reporting half of one deliverable. The analysis half is
``authority_call_analysis`` -- "what does this name provably hold here" -- and
it is the lowest of the three modules, so the shared refusal vocabulary
(:class:`AuthorityGraphError`, :class:`EmptyDerivationError`) is declared there
and imported here and by ``authority_graph``, which re-exports
:func:`approval_flag_reachability` so R-GEA-2's named module carries the API.
The dependency runs one way through the three and cannot cycle. The split
itself is forced by ``limits.size_budget_lines`` in ``governance-policy.json``
and taken on the seam NS-39 item 4 named.

Spec: ``docs/specs/graph-engineering-adoption.md`` (R-GEA-2, R-GEA-4, C-GEA-1,
C-GEA-2). Standard library and first-party imports only.
"""

from __future__ import annotations

import ast
import logging
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

from harness.shared.authority_call_analysis import (
    BROKER_ENTRY_POINTS,
    AuthorityGraphError,
    EmptyDerivationError,
    Position,
    Scope,
    ScopeOwner,
    build_scope,
    mapping_entries,
    names_entry_point,
)

logger = logging.getLogger(__name__)

#: The key whose value the broker reads as a human signature. Named once so the
#: scan, the witness messages, and the tests cannot drift from ``broker.py``.
APPROVAL_FLAG = "human_approved"

#: The name of ``ExecutionBroker.execute_command``'s mapping parameter.
CONTEXT_PARAMETER = "context"


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


def _context_reason(expr: ast.expr, scope: Scope, at: Position | None) -> str | None:
    """Why ``expr`` could carry the approval flag into the broker, or ``None``."""
    entries, reason = mapping_entries(expr, scope, at)
    if entries is None:
        return f"the broker context is not literal here: {reason}, so a caller could supply {APPROVAL_FLAG!r}"
    if APPROVAL_FLAG in entries:
        return f"the broker context names {APPROVAL_FLAG!r} directly"
    return None


def _spread_reason(expr: ast.expr, scope: Scope, at: Position | None) -> str | None:
    """Why a ``**`` argument could carry the approval flag, or ``None``.

    ``execute_run_command`` forwards its arguments this way today, with a dict
    literal built two lines above, so the spread is resolved rather than
    reported. What this guards against is the same call growing a ``context`` it
    did not build -- a bag that *is* a ``**kwargs`` parameter included.
    """
    entries, reason = mapping_entries(expr, scope, at)
    if entries is None:
        return f"the call forwards `**{ast.unparse(expr)}`, a mapping it did not build here: {reason}"
    if APPROVAL_FLAG in entries:
        return f"the forwarded arguments name {APPROVAL_FLAG!r} directly"
    context = entries.get(CONTEXT_PARAMETER)
    if context is None:
        return None
    return _context_reason(context, scope, at)


def _call_reasons(call: ast.Call, scope: Scope) -> list[tuple[str, ast.expr]]:
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


def _escape_reason(reference: ast.expr) -> str:
    """Why a reference that is read but not called here is a witness.

    The scan can read the arguments of a call it can see. A method handed on as
    a value is called elsewhere -- in a caller, a registry, a callback -- with
    arguments that are not in this function at all, so the mapping it eventually
    receives is outside what any of these rules can decide.
    """
    return (
        f"`{ast.unparse(reference)}` is read here without being called, so the broker method "
        f"leaves this scan as a value; whatever calls it may pass a context naming {APPROVAL_FLAG!r}"
    )


class _BrokerCallSites(ast.NodeVisitor):
    """Every broker call with the scope that builds its context, and every
    reference to the method that leaves this scan instead of being called."""

    def __init__(self) -> None:
        self.sites: list[tuple[ast.Call, Scope]] = []
        self.escapes: list[tuple[ast.expr, Scope]] = []
        self._scopes: list[Scope] = []
        self._called: set[int] = set()

    def _enter(self, node: ScopeOwner, name: str) -> None:
        """Read one function (or the module) into a scope, then visit it."""
        self._scopes.append(build_scope(node, name))
        self.generic_visit(node)
        self._scopes.pop()

    def _is_alias(self, name: str) -> bool:
        """Whether any scope now open binds ``name`` to a broker entry point.

        The whole stack, not just the innermost scope: a nested function closes
        over the names around it, so ``invoke = broker.execute_command`` in a
        wrapper is callable inside the ``def`` it wraps. Reading only the
        innermost scope would put that call outside the enumeration again, one
        ``def`` deeper than the bypass this rule closes.
        """
        return any(name in scope.aliases for scope in self._scopes)

    def _is_broker_call(self, node: ast.Call) -> bool:
        """Whether this call goes through a broker entry point, by name or alias."""
        if names_entry_point(node.func):
            return True
        return isinstance(node.func, ast.Name) and self._is_alias(node.func.id)

    def _record_reference(self, node: ast.expr) -> None:
        """Report a read of the broker method that this scan cannot follow.

        Three shapes are not reported, checked in the order that makes the rule
        cheapest to state: a store is not a read of the method at all; the
        callee of a call is analysed as a call site instead; and the right-hand
        side of an alias binding is followed through every call to that name.
        There is no fourth -- anything else takes the method somewhere this scan
        does not go, and is reported at the point it leaves.

        ``node`` is a name chain or the ``getattr`` call that reads one: the two
        spellings of the same reference, and the store check applies only to the
        first because a call has no context to be stored in.
        """
        if isinstance(node, (ast.Name, ast.Attribute)) and not isinstance(node.ctx, ast.Load):
            return
        if id(node) in self._called:
            return
        scope = self._scopes[-1]
        if id(node) in scope.alias_values:
            return
        if names_entry_point(node) or (isinstance(node, ast.Name) and self._is_alias(node.id)):
            self.escapes.append((node, scope))

    # The capitalised method names below are `ast.NodeVisitor`'s dispatch
    # protocol rather than this module's naming choice.
    def visit_Module(self, node: ast.Module) -> None:
        self._enter(node, "<module>")

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self._enter(node, node.name)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self._enter(node, node.name)

    def visit_Call(self, node: ast.Call) -> None:
        # Recorded before descending: `generic_visit` reaches `node.func` next,
        # and a callee must not be mistaken for a reference that escaped.
        self._called.add(id(node.func))
        if self._is_broker_call(node):
            self.sites.append((node, self._scopes[-1]))
        elif names_entry_point(node):
            # `getattr(broker, "execute_command")` is a *read* of the method
            # written as a call, so it is judged by the rule that judges
            # `broker.execute_command`, not by the one for an unmodelled call.
            self._record_reference(node)
        else:
            self._scopes[-1].escape_arguments(node)
        self.generic_visit(node)

    def visit_Name(self, node: ast.Name) -> None:
        self._record_reference(node)
        self.generic_visit(node)

    def visit_Attribute(self, node: ast.Attribute) -> None:
        self._record_reference(node)
        self.generic_visit(node)


def _witness(path: Path, at: ast.expr, scope: Scope, blamed: ast.expr, reason: str) -> ApprovalWitness:
    """One witness: where it is, which function owns it, and what to look at."""
    return ApprovalWitness(
        path=str(path),
        line=at.lineno,
        function=scope.name,
        expression=ast.unparse(blamed),
        reason=reason,
    )


def _scan_source(path: Path) -> tuple[list[ApprovalWitness], int]:
    """Witnesses and inspected-reference count for one file.

    A file that cannot be parsed raises out of ``ast.parse`` rather than being
    skipped: a skipped file is a file the property was not checked on, reported
    as a pass. The count returned is what the scan *looked at* -- calls plus
    escaping references -- because it is what the emptiness guard in
    :func:`approval_flag_reachability` is about.
    """
    tree = ast.parse(path.read_text(encoding="utf-8"))
    visitor = _BrokerCallSites()
    visitor.visit(tree)
    witnesses = [
        _witness(path, call, scope, expression, reason)
        for call, scope in visitor.sites
        for reason, expression in _call_reasons(call, scope)
    ]
    witnesses += [
        _witness(path, reference, scope, reference, _escape_reason(reference)) for reference, scope in visitor.escapes
    ]
    return witnesses, len(visitor.sites) + len(visitor.escapes)


def approval_flag_reachability(source_paths: Iterable[Path]) -> list[ApprovalWitness]:
    """Report every broker call site at which ``human_approved`` could be supplied.

    Today ``execute_run_command`` builds a dict literal holding ``agent_id``
    alone, so the result is empty -- and if that function grew a ``context``
    parameter, forwarded a ``**`` mapping it did not build, or reached the
    broker through a name bound to its method, the site would appear here by
    name, line, and expression (R-GEA-2, finding S-2).

    Raises when handed no files, or when the scanned corpus contains no broker
    call or reference at all: an empty result from an empty scan is the vacuous
    pass R-GEA-4 exists to refuse, and it is the failure mode a path-narrowing
    typo produces.
    """
    paths = [Path(source) for source in source_paths]
    if not paths:
        raise EmptyDerivationError("no source file was handed to the approval-flag scan; there is nothing to prove")

    witnesses: list[ApprovalWitness] = []
    inspected = 0
    for path in paths:
        found, seen = _scan_source(path)
        witnesses.extend(found)
        inspected += seen

    if not inspected:
        raise EmptyDerivationError(
            f"scanned {len(paths)} file(s) and found no call to, and no reference to, any of "
            f"{sorted(BROKER_ENTRY_POINTS)}; the scan inspected nothing, which is not the same "
            "as finding nothing"
        )

    logger.debug("Approval-flag scan: %s file(s), %s broker reference(s)", len(paths), inspected)
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
