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
from typing import Any, Optional

try:
    from langchain_core.runnables import RunnableConfig
    from langgraph.graph import END, START, StateGraph
except ImportError:  # pragma: no cover
    END = "__end__"  # type: ignore[assignment]
    START = "__start__"  # type: ignore[assignment]
    StateGraph = None  # type: ignore[assignment, misc]
    RunnableConfig = dict  # type: ignore[assignment, misc]

#: ``RunnableConfig`` is imported at *runtime*, not under ``TYPE_CHECKING``, and
#: the spelling of the annotations below is load-bearing rather than cosmetic.
#: LangGraph injects ``config`` into a node or router only when the parameter is
#: annotated ``RunnableConfig`` / ``Optional[RunnableConfig]`` or left
#: unannotated (``KWARGS_CONFIG_KEYS`` in ``langgraph._internal._runnable``);
#: any other annotation — ``Any``, as these two routers carried — is skipped
#: with a ``UserWarning`` and the parameter simply never arrives. That is why
#: R-LPW-4's policy wiring passed its unit tests, which call the routers
#: directly, and did nothing through the compiled graph. ``X | None`` is *not*
#: one of the accepted spellings under PEP 563, which is what the ``UP045``
#: suppressions below are for, and ``test_config_injection_contract`` fails if
#: any of these signatures drifts back out of the accepted set.

from harness.shared.langgraph.errors import blocking_error
from harness.shared.langgraph.nodes import (
    CLARIFY_COUNT,
    QUALITY_GATE_REASON,
    RETRYABLE_REASONS,
    _get_configurable,
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


def _route_plan_gate(
    state: dict,
    config: Optional[RunnableConfig] = None,  # noqa: UP045
    **kwargs: Any,
) -> str:
    """Route after plan_gate: blocking error → escalate; pass → implementer;
    fail → clarify | escalate.

    The blocking-error exit comes first and is the one that keeps a denial
    terminal in fact rather than only in verdict: it is the ``pass`` branch
    that reaches the write-capable ``implementer``, so checking after it let
    a denied planner's run write a patch and spend a revision before
    ``quality_gate`` escalated (R-LGH-3).

    The third exit is what makes the cycle terminate. ``clarify_node`` writes
    ``plan_gate: "pass"`` and ``plan_gate_node`` recomputes that key from
    ``plan_divergence`` on the way back, which nothing in the cycle changes —
    so without a bound the two nodes alternate until the framework raises
    ``GraphRecursionError``. Once clarification has been attempted
    ``policy.max_iterations`` times, an unresolved divergence escalates and the
    run ends ``BLOCKED`` (R-LGH-5).

    The cap is ``GraphPolicy.max_iterations`` read from
    ``config["configurable"]["policy"]``, the same mechanism and the same
    ``GraphPolicy()`` fallback ``_route_quality_gate`` uses, so a bare-``state``
    caller keeps the documented default.
    """
    if blocking_error(state.get("errors", [])) is not None:
        # Checked *before* the pass branch, because the pass branch is the one
        # that reaches the write-capable implementer. A denied planner records
        # its authority failure and leaves `plan_divergence` at 0.0, so the plan
        # gate passes and the run reached `implementer` — which wrote a patch
        # and spent a revision before `quality_gate` escalated it. Terminal
        # meant terminal only after a write had already happened, which is not
        # what R-LGH-3 asks for. Found by review on PR #87.
        logger.warning("plan_gate: blocking error recorded upstream; escalating before implementer")
        return "escalate"
    gate_status = state.get("gate_status", {})
    if gate_status.get("plan_gate") == "pass":
        return "implementer"
    configurable = _get_configurable(config, kwargs)
    policy: GraphPolicy = configurable.get("policy") or GraphPolicy()
    if gate_status.get(CLARIFY_COUNT, 0) >= policy.max_iterations:
        logger.warning(
            "plan_gate: divergence unresolved after %d clarification attempts; escalating",
            gate_status.get(CLARIFY_COUNT, 0),
        )
        return "escalate"
    return "clarify"


def _route_quality_gate(
    state: dict,
    config: Optional[RunnableConfig] = None,  # noqa: UP045
    **kwargs: Any,
) -> str:
    """Route after quality_gate: pass → END, revision → implementer, exhausted → escalate.

    The revision cap comes from ``GraphPolicy.max_iterations`` via
    ``config["configurable"]["policy"]`` when the caller supplies one — the
    same mechanism ``nodes.py`` already uses to thread ``orchestrator``
    through node calls. With no policy supplied, falls back to
    ``GraphPolicy()``'s built-in default (10), numerically identical to the
    literal this replaces, so bare-``state`` callers see unchanged behavior.
    """
    gate_status = state.get("gate_status", {})
    if gate_status.get("quality_gate") == "pass":
        return str(END)
    reason = gate_status.get(QUALITY_GATE_REASON)
    if reason is not None and reason not in RETRYABLE_REASONS:
        # Only a failing suite is worth another revision. A blocking error and an
        # absence of evidence are both terminal, and retrying either spends a
        # *write-capable* revision per attempt to reach the same `escalate` — an
        # inconclusive run wrote five patches under `max_iterations=5` and
        # produced five identical `passed=0, failed=0` rows before stopping
        # (R-LGH-8; found by review on PR #87).
        logger.warning("quality_gate failed with terminal reason %r; escalating without retry", reason)
        return "escalate"
    configurable = _get_configurable(config, kwargs)
    policy: GraphPolicy = configurable.get("policy") or GraphPolicy()
    revision_count = state.get("revision_count", 0)
    if revision_count < policy.max_iterations:
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
        Graph configuration. Defaults to ``GraphPolicy.from_governance_json()``
        if not provided — reads recursion/concurrency/divergence tuning from
        ``governance-policy.json`` rather than the bare dataclass defaults.
    checkpointer:
        LangGraph checkpointer for durable state. Defaults to ``None``
        (no checkpointing — suitable for unit tests).

    Returns
    -------
    CompiledGraph
        The compiled, ready-to-invoke graph.
    """
    if policy is None:
        policy = GraphPolicy.from_governance_json()

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
        {"implementer": "implementer", "clarify": "clarify", "escalate": "escalate"},
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


def runtime_config(
    policy: GraphPolicy | None = None,
    **configurable: Any,
) -> RunnableConfig:
    """Build the ``RunnableConfig`` an invocation of this graph runs under.

    ``docs/specs/langgraph-policy-wiring.md`` (R-LPW-4, R-LPW-5) made
    ``_route_quality_gate`` and ``plan_gate_node`` read their thresholds from
    ``config["configurable"]["policy"]`` — but no producer of that key was ever
    written, so every caller took the ``GraphPolicy()`` fallback and ran on
    dataclass literals while ``build_graph`` loaded the real policy and dropped
    it. This is that producer (R-LGH-4).

    Two of the three limits are the framework's, not this package's, and belong
    at invoke time rather than compile time: ``recursion_limit`` bounds the
    graph's step count (LangGraph's own default is applied otherwise, which is
    not the policy's 50), and ``max_concurrency`` bounds parallel branch
    execution. Both are read from the same ``GraphPolicy``, so
    ``governance-policy.json`` decides them.

    Parameters
    ----------
    policy:
        Configuration for this run. Defaults to
        ``GraphPolicy.from_governance_json()`` — the same default
        ``build_graph`` takes, so a caller that omits it in both places gets
        one consistent policy rather than two.
    **configurable:
        Anything else the nodes read out of ``configurable``, most commonly
        ``orchestrator=...``.
    """
    if policy is None:
        policy = GraphPolicy.from_governance_json()
    config: RunnableConfig = {
        "configurable": {"policy": policy, **configurable},
        "recursion_limit": policy.recursion_limit,
        "max_concurrency": policy.max_concurrency,
    }
    return config


#: Expected node count for topology tests.
EXPECTED_NODE_COUNT = 10


__all__ = [
    "EXPECTED_NODE_COUNT",
    "build_graph",
    "runtime_config",
]
