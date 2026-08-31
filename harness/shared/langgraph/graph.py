"""LangGraph StateGraph builder for the MangoMAS orchestration graph.

Assembles the full graph topology:
  START → planner → [shadow_planner, plan_gate] → (conditional) → implementer
  → test_eval → quality_gate → (conditional) → END | implementer | escalate

Uses **conditional edges** for gates (visualizable in LangGraph Studio)
and reserves **Command** for interrupt-based nodes (Phase 3).

Requires ``langgraph>=1.0.10`` — gated by ``LANGGRAPH_AVAILABLE`` in ``__init__.py``.
"""

from __future__ import annotations

import logging
from typing import Any

try:
    from langgraph.graph import END, START, StateGraph
except ImportError:  # pragma: no cover
    END = "__end__"  # type: ignore[assignment]
    START = "__start__"  # type: ignore[assignment]
    StateGraph = None  # type: ignore[assignment, misc]

from harness.shared.langgraph.nodes import (
    clarify_node,
    escalate_node,
    evaluation_node,
    implementer_node,
    peer_reviewer_node,
    plan_gate_node,
    planner_node,
    quality_gate_node,
    security_reviewer_node,
    shadow_planner_node,
)
from harness.shared.langgraph.policy import GraphPolicy
from harness.shared.langgraph.state import MangoState

logger = logging.getLogger(__name__)


# ── Routing functions for conditional edges ──────────────────


def _route_plan_gate(state: dict) -> str:
    """Route after plan_gate: pass → implementer, fail → clarify."""
    gate_status = state.get("gate_status", {})
    if gate_status.get("plan_gate") == "pass":
        return "implementer"
    return "clarify"


def _route_quality_gate(state: dict) -> str:
    """Route after quality_gate: pass → END, revision → implementer, exhausted → escalate."""
    gate_status = state.get("gate_status", {})
    if gate_status.get("quality_gate") == "pass":
        return str(END)
    # Check revision count against policy max
    revision_count = state.get("revision_count", 0)
    # Default max from GraphPolicy — read from state if available
    if revision_count < 10:  # Will be overridden by policy in Phase 4
        return "implementer"
    return "escalate"


# ── Graph builder ────────────────────────────────────────────


def build_graph(
    policy: GraphPolicy | None = None,
    checkpointer: Any = None,
) -> Any:
    """Assemble and compile the MangoMAS LangGraph StateGraph.

    Parameters
    ----------
    policy:
        Graph configuration. Defaults to ``GraphPolicy()`` if not provided.
    checkpointer:
        LangGraph checkpointer for durable state. Defaults to ``None``
        (no checkpointing — suitable for unit tests).

    Returns
    -------
    CompiledGraph
        The compiled, ready-to-invoke graph.
    """
    if policy is None:
        policy = GraphPolicy()

    if StateGraph is None:
        raise RuntimeError("langgraph library is required to build StateGraph")

    builder = StateGraph(MangoState)

    # ── Add nodes ────────────────────────────────────────────
    builder.add_node("planner", planner_node)
    builder.add_node("shadow_planner", shadow_planner_node)
    builder.add_node("plan_gate", plan_gate_node)
    builder.add_node("clarify", clarify_node)
    builder.add_node("implementer", implementer_node)
    builder.add_node("peer_reviewer", peer_reviewer_node)
    builder.add_node("security_reviewer", security_reviewer_node)
    builder.add_node("test_eval", evaluation_node)
    builder.add_node("quality_gate", quality_gate_node)
    builder.add_node("escalate", escalate_node)

    # ── Add edges (topology) ────────────────────────────────
    # START → planner
    builder.add_edge(START, "planner")

    # planner → shadow_planner (parallel — Phase 5 will use Send)
    builder.add_edge("planner", "shadow_planner")

    # shadow_planner → plan_gate
    builder.add_edge("shadow_planner", "plan_gate")

    # plan_gate → (conditional) → clarify | implementer
    builder.add_conditional_edges(
        "plan_gate",
        _route_plan_gate,
        {"implementer": "implementer", "clarify": "clarify"},
    )

    # clarify → plan_gate (re-evaluate after clarification)
    builder.add_edge("clarify", "plan_gate")

    # implementer → test_eval
    builder.add_edge("implementer", "test_eval")

    # test_eval → quality_gate
    builder.add_edge("test_eval", "quality_gate")

    # quality_gate → (conditional) → END | implementer | escalate
    builder.add_conditional_edges(
        "quality_gate",
        _route_quality_gate,
        {END: END, "implementer": "implementer", "escalate": "escalate"},
    )

    # escalate → END (terminal)
    builder.add_edge("escalate", END)

    # ── Compile ─────────────────────────────────────────────
    compiled = builder.compile(
        checkpointer=checkpointer,
    )

    logger.info(
        "MangoMAS LangGraph compiled: %d nodes, recursion_limit=%d",
        len(compiled.nodes),
        policy.recursion_limit,
    )

    return compiled


#: Expected node count for topology tests.
EXPECTED_NODE_COUNT = 10


__all__ = [
    "EXPECTED_NODE_COUNT",
    "build_graph",
]
