"""A derived, never-persisted view of the authorization chain.

Two questions about that chain could not be answered mechanically before this
module, and both are path questions rather than table lookups.

**Which of the two grant surfaces is a reachability answer about?**
Each active role has two, and they deliberately disagree: ``allowed_actions``
decides *tool exposure*, while ``EXECUTION_IDENTITY`` decides what the broker
asks the PDP about. ``planner`` holds ``spec_write`` and executes as
``orchestrator``, which lacks it; ``verifier`` holds ``review_write`` and
``security_scan`` and executes as ``test-eval``, which lacks both. A query that
does not name a surface would get a confident answer to the other question, so
:class:`Surface` has no default and an unnamed surface raises (R-GEA-2b,
finding S-5).

**Can agent-controlled input reach ``policy_decision.decide``'s ``human_approved``?**
That half lives in ``authority_call_sites`` -- the two together exceed
``limits.size_budget_lines`` -- and :func:`approval_flag_reachability` is
re-exported here so R-GEA-2's named module carries the whole API.

Nothing here is stored, cached, or written. The authorization graph is
*derived* -- a pure function of ``agent-policy.json`` and three mappings in
``agent_authority`` -- and a persisted copy of derived governance state is a
cache whose staleness has a security consequence: the stored graph says one
thing while the broker enforces another. Every query recomputes from the same
functions the broker calls: :func:`agent_authority.allowed_actions` for the
tool-exposure surface and :func:`policy_decision.decide` for the execution
identity. Restating either here would be a second implementation that agrees
with the enforced one only until one of them changes.

That also keeps the dependency one-way (C-GEA-2): the graph reads the
governance layer, and ``test_governance_layer_does_not_import_the_graph``
asserts the reverse edge is never added. A governance module importing this one
would put a derived view underneath the thing it derives from.

Every empty derivation raises. An empty role set, action set, tool set, or edge
set makes every property over it *vacuously* true, which is the defect this
repository keeps finding in its own gates (R-GEA-4).

Spec: ``docs/specs/graph-engineering-adoption.md`` (R-GEA-2, R-GEA-2b, R-GEA-4,
C-GEA-1, C-GEA-2). Standard library and first-party imports only: C-GEA-1
forbids a new dependency, so there is no ``networkx`` here and the traversal is
two nested loops over a graph with a dozen nodes.
"""

from __future__ import annotations

import enum
import logging
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from harness.shared import agent_authority
from harness.shared.authority_call_sites import (
    APPROVAL_FLAG,
    ApprovalWitness,
    AuthorityGraphError,
    EmptyDerivationError,
    approval_flag_reachability,
)
from harness.shared.governance.policy_decision import decide

logger = logging.getLogger(__name__)


class Surface(enum.Enum):
    """Which grant surface a reachability query is about.

    The two disagree by design, so there is no sensible default; see the module
    docstring for the ``planner``/``spec_write`` and ``verifier``/``review_write``
    pairs that a single-surface query answers wrongly (R-GEA-2b, finding S-5).
    """

    #: What ``allowed_actions`` exposes to the model: the union over every
    #: canonical role the active role maps to, minus each role's approval-gated
    #: actions. This filters the advertised tool schema, and the dispatcher
    #: re-asks it before running a handler.
    TOOL_EXPOSURE = "tool_exposure"

    #: What the broker asks the PDP about: the single canonical role in
    #: ``EXECUTION_IDENTITY``, evaluated by ``decide`` with no human approval.
    EXECUTION_IDENTITY = "execution_identity"


class UnnamedSurfaceError(AuthorityGraphError):
    """A query did not name a :class:`Surface`.

    Raised rather than defaulted. Picking a surface here would answer a
    different question than the caller asked, and return it with no marker that
    a choice had been made.
    """


@dataclass(frozen=True)
class AuthorityGraph:
    """Roles, actions, and tools on one surface, with the edges between them.

    Derived on every call and thrown away. ``role_actions`` is the authoritative
    answer for the surface -- for ``TOOL_EXPOSURE`` it is
    ``agent_authority.allowed_actions`` itself, so a change there moves this
    graph rather than leaving it to be restated and to drift.
    """

    surface: Surface
    #: active role -> the canonical roles it traverses on this surface.
    role_edges: Mapping[str, tuple[str, ...]]
    #: active role -> the actions it reaches on this surface.
    role_actions: Mapping[str, frozenset[str]]
    #: canonical role -> the actions ``decide`` allows it with no human approval.
    grant_edges: Mapping[str, frozenset[str]]
    #: action -> the tools that require it.
    action_tools: Mapping[str, frozenset[str]]
    #: every action node, including the ones no role reaches. An approval-gated
    #: action is a node with no grant edge, and that distinction is the whole of
    #: finding S-1: ``external_write`` is unreachable because an edge was
    #: subtracted, while ``destructive`` is unreachable because it was never
    #: declared and so is not a node here at all.
    actions: frozenset[str]

    @property
    def node_count(self) -> int:
        """Roles, canonical roles, actions, and tools, counted once each."""
        canonical = set(self.grant_edges)
        tools = {tool for named in self.action_tools.values() for tool in named}
        return len(self.role_edges) + len(canonical) + len(self.actions) + len(tools)

    @property
    def edge_count(self) -> int:
        """Role, grant, and tool edges, counted once each."""
        role = sum(len(canonical) for canonical in self.role_edges.values())
        grant = sum(len(granted) for granted in self.grant_edges.values())
        tool = sum(len(named) for named in self.action_tools.values())
        return role + grant + tool


def _require_surface(surface: Surface | None) -> Surface:
    """Return ``surface``, or raise if the caller did not name one."""
    if not isinstance(surface, Surface):
        raise UnnamedSurfaceError(
            f"a reachability query must name a surface ({Surface.TOOL_EXPOSURE.value} or "
            f"{Surface.EXECUTION_IDENTITY.value}); got {surface!r}. The two surfaces disagree "
            "deliberately, so a default would answer the other question."
        )
    return surface


def _declared_roles(policy: Mapping[str, object]) -> tuple[dict[str, Any], ...]:
    """The canonical role objects the authority model declares, in order.

    A model whose ``agents`` key is missing or is not a list yields none, and
    :func:`build_authority_graph` then refuses rather than deriving a graph with
    no roles in it.
    """
    agents = policy.get("agents")
    if not isinstance(agents, list):
        return ()
    return tuple(role for role in agents if isinstance(role, dict) and "id" in role)


def build_authority_graph(surface: Surface | None = None, policy_path: Path | None = None) -> AuthorityGraph:
    """Derive the authorization graph for ``surface``. Never persisted.

    Grant edges are computed by asking :func:`policy_decision.decide` -- the
    function the broker calls -- once per (canonical role, action) with
    ``human_approved=False``. Restating its three denials here would be a second
    implementation of the PDP that agrees with it only until one of them
    changes.
    """
    named = _require_surface(surface)
    policy = agent_authority.load_agent_policy(policy_path)

    active_to_canonical = agent_authority.ACTIVE_TO_CANONICAL
    if not active_to_canonical:
        raise EmptyDerivationError("the active-role mapping is empty; every reachability query would be vacuous")

    roles = _declared_roles(policy)
    if not roles:
        raise EmptyDerivationError("the authority model declares no canonical role; the extractor read nothing")
    canonical_ids = tuple(str(role["id"]) for role in roles)

    # Approval-gated actions stay in the universe on purpose: `external_write`
    # is declared by `release-auditor` and gated, and a universe that dropped it
    # would make "the verifier cannot reach `external_write`" true because the
    # action was never a node -- finding S-1's vacuity, rebuilt.
    declared = frozenset(str(action) for role in roles for action in role.get("allowed_actions", []))
    if not declared:
        raise EmptyDerivationError("the authority model declares no action; the extractor read nothing")

    tool_actions = agent_authority.TOOL_REQUIRED_ACTION
    if not tool_actions:
        raise EmptyDerivationError("no tool declares a required action; every tool would be unreachable vacuously")

    actions = declared | frozenset(tool_actions.values())
    grant_edges = {
        role_id: frozenset(a for a in actions if decide(role_id, a, policy, human_approved=False).allowed)
        for role_id in canonical_ids
    }
    if not any(grant_edges.values()):
        raise EmptyDerivationError("no canonical role is granted any action; the authority model or the PDP is broken")

    role_edges: dict[str, tuple[str, ...]] = {}
    role_actions: dict[str, frozenset[str]] = {}
    for active_role in active_to_canonical:
        if named is Surface.TOOL_EXPOSURE:
            role_edges[active_role] = tuple(active_to_canonical[active_role])
            # The live function, not a copy of its subtraction: reverting
            # `human_approval_required_for` there must move this answer.
            role_actions[active_role] = agent_authority.allowed_actions(active_role, policy_path)
        else:
            identity = agent_authority.execution_identity(active_role)
            role_edges[active_role] = (identity,)
            role_actions[active_role] = grant_edges.get(identity, frozenset())

    action_tools: dict[str, set[str]] = {}
    for tool_name, action in tool_actions.items():
        action_tools.setdefault(action, set()).add(tool_name)

    graph = AuthorityGraph(
        surface=named,
        role_edges=role_edges,
        role_actions=role_actions,
        grant_edges=grant_edges,
        action_tools={action: frozenset(names) for action, names in action_tools.items()},
        actions=actions,
    )
    logger.debug(
        "Derived the authority graph on the %s surface: %s nodes, %s edges",
        named.value,
        graph.node_count,
        graph.edge_count,
    )
    return graph


def _role_actions(graph: AuthorityGraph, active_role: str) -> frozenset[str]:
    """The role's action set on the graph's surface, or raise for an unknown role."""
    actions = graph.role_actions.get(active_role)
    if actions is None:
        raise EmptyDerivationError(
            f"{active_role!r} is not an active role, so it derives no edge. Answering 'nothing is "
            "reachable' for a name nobody declared is how a typo passes for a security property."
        )
    return actions


def reachable_actions(
    active_role: str,
    surface: Surface | None = None,
    policy_path: Path | None = None,
) -> frozenset[str]:
    """The actions ``active_role`` reaches on ``surface`` with no human approval.

    On ``TOOL_EXPOSURE`` this is ``agent_authority.allowed_actions`` verbatim; on
    ``EXECUTION_IDENTITY`` it is what ``decide`` allows the role's execution
    identity. An unknown role raises rather than returning the empty set.
    """
    graph = build_authority_graph(surface, policy_path)
    actions = _role_actions(graph, active_role)
    logger.debug(
        "Queried reachable actions for %s on the %s surface: %s",
        active_role,
        graph.surface.value,
        sorted(actions),
    )
    return actions


def paths_to(
    active_role: str,
    tool_name: str,
    surface: Surface | None = None,
    policy_path: Path | None = None,
) -> list[list[str]]:
    """Witness paths from ``active_role`` to ``tool_name`` on ``surface``.

    Each witness names every intermediate -- ``[active role, canonical role,
    action, tool]`` -- because "the reasoner can write" is a claim a reader
    cannot check, while ``["nemotron-reasoner", "implementer", "write",
    "write_file"]`` names the edge to delete if the grant is wrong. The list is
    empty when the tool is unreachable, and sorted so a test can compare it.

    A tool no mapping declares raises: ``TOOL_REQUIRED_ACTION`` withholds an
    unmapped tool, so an empty list for a misspelled name would read as "safely
    unreachable" for a tool that does not exist.
    """
    graph = build_authority_graph(surface, policy_path)
    role_actions = _role_actions(graph, active_role)
    required = [action for action, tools in graph.action_tools.items() if tool_name in tools]
    if not required:
        raise EmptyDerivationError(
            f"{tool_name!r} declares no required action, so it has no node on this graph. "
            "An unmapped tool is withheld by `tool_is_permitted`, not reachable."
        )

    paths: list[list[str]] = []
    for canonical in graph.role_edges[active_role]:
        granted = graph.grant_edges.get(canonical, frozenset())
        for action in required:
            if action in granted and action in role_actions:
                paths.append([active_role, canonical, action, tool_name])
    paths.sort()
    logger.debug(
        "Enumerated %s path(s) from %s to %s on the %s surface",
        len(paths),
        active_role,
        tool_name,
        graph.surface.value,
    )
    return paths


__all__ = [
    "APPROVAL_FLAG",
    "ApprovalWitness",
    "AuthorityGraph",
    "AuthorityGraphError",
    "EmptyDerivationError",
    "Surface",
    "UnnamedSurfaceError",
    "approval_flag_reachability",
    "build_authority_graph",
    "paths_to",
    "reachable_actions",
]
