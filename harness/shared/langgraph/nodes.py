"""LangGraph node functions for the MangoMAS orchestration graph.

Each function wraps an existing orchestrator method as a LangGraph node.
Node contracts:

1. Accept ``(state: MangoState)`` or ``(state: MangoState, config: RunnableConfig)``
2. Return ``dict`` (partial state update) — never mutate state in-place
3. Wrap side effects in ``try/except``, write failures to ``errors`` channel
4. No side effects before ``interrupt()`` (re-execution hazard)

Phase 1 implements the 3 active nodes (planner, implementer, verifier) as thin
wrappers around ``MangoMASOrchestrator.execute_agent``. The remaining 7 nodes
are stubs that return minimal state updates for topology validation.
"""

from __future__ import annotations

import logging
from typing import Any

# Re-exported for backwards compatibility and prompt builder discovery (DEC-058 / R-HR-5)
from harness.shared.agent_prompts import (  # noqa: F401
    PLANNER_PROMPT_TEMPLATE,
    REASONER_PROMPT_TEMPLATE,
    VERIFIER_PROMPT_TEMPLATE,
)
from harness.shared.governance.verdict import BLOCKED, FAILED, VERIFIED
from harness.shared.langgraph.node_executors import (
    _get_configurable,
    evaluation_node,
    implementer_node,
    peer_reviewer_node,
    planner_node,
    security_reviewer_node,
    shadow_planner_node,
)
from harness.shared.langgraph.node_reasons import (
    CLARIFY_COUNT,
    QUALITY_GATE_REASON,
    REASON_ERROR,
    REASON_INCONCLUSIVE,
    REASON_TESTS_FAILED,
    RETRYABLE_REASONS,
    _conclusive,
    _nonneg_int_count,
    _quality_gate_reason,
)
from harness.shared.langgraph.policy import GraphPolicy
from harness.shared.langgraph.state import MangoState

logger = logging.getLogger(__name__)


# ── Gate/routing nodes ───────────────────────────────────────


def plan_gate_node(state: MangoState, config=None, **_kwargs: Any) -> dict[str, Any]:
    """Plan gate: compares shadow divergence against ``GraphPolicy.plan_divergence_threshold``.

    The threshold comes from ``config["configurable"]["policy"]`` when the
    caller supplies one (the same mechanism ``orchestrator`` already uses
    above), falling back to ``GraphPolicy()``'s built-in default (0.35) —
    numerically identical to the literal this replaces — otherwise. Phase 1:
    ``shadow_planner_node`` always reports 0.0 divergence ("No real
    comparison yet"), so this always passes today regardless of the
    threshold; real divergence computation is Phase 5 scope, not this fix.
    """
    configurable = _get_configurable(config, _kwargs)
    policy: GraphPolicy = configurable.get("policy") or GraphPolicy()
    divergence = state.get("plan_divergence", 0.0)
    logger.info("plan_gate_node: divergence=%.3f threshold=%.3f", divergence, policy.plan_divergence_threshold)
    return {
        "gate_status": {
            **state.get("gate_status", {}),
            "plan_gate": "pass" if divergence <= policy.plan_divergence_threshold else "fail",
        },
    }


def quality_gate_node(state: MangoState) -> dict[str, Any]:
    """Quality gate: grades the run on errors, evidence, and test outcomes.

    Three things withhold a pass, and the gate records which one did so
    ``_route_quality_gate`` can tell a retryable failure from a terminal one:

    * a **blocking** error in the ``errors`` channel (R-LGH-1) — an error from
      the observation plane is recorded and ignored, because INV-16 requires an
      observation-mode producer's failure to leave the incumbent path
      unaffected;
    * an **inconclusive** verification result (R-LGH-2);
    * a **failing** suite, which is the case this gate always handled.
    """
    revision_count = state.get("revision_count", 0)
    reason = _quality_gate_reason(state)
    passes = reason is None

    logger.info(
        "quality_gate_node: revision_count=%d passes=%s reason=%s",
        revision_count,
        passes,
        reason or "-",
    )
    gate_status = {
        **state.get("gate_status", {}),
        "quality_gate": "pass" if passes else "fail",
    }
    if passes:
        gate_status.pop(QUALITY_GATE_REASON, None)
    else:
        gate_status[QUALITY_GATE_REASON] = reason
    return {
        "gate_status": gate_status,
        "verdict": VERIFIED if passes else FAILED,
    }


# ── Interrupt nodes ──────────────────────────────────────────


def clarify_node(state: MangoState) -> dict[str, Any]:
    """Clarify node: pauses for human input when plan gate fails.

    Phase 1 stub: returns immediately. Phase 3 will add ``interrupt()``.

    Counting the visits is not stub behaviour, it is the cycle's only bound.
    ``clarify_node`` writes ``plan_gate: "pass"`` and ``plan_gate_node``
    immediately recomputes that key from ``plan_divergence``, which nothing in
    the cycle changes — so with a real divergence the two nodes hand the run
    back and forth until the framework's own recursion ceiling raises
    ``GraphRecursionError``. ``_route_plan_gate`` reads this counter to leave
    for ``escalate`` at the bound instead (R-LGH-5).
    """
    gate_status = state.get("gate_status", {})
    attempts = gate_status.get(CLARIFY_COUNT, 0) + 1
    logger.info("clarify_node: stub (no interrupt in Phase 1), attempt=%d", attempts)
    return {
        "gate_status": {
            **gate_status,
            "plan_gate": "pass",  # After clarification, gate passes
            CLARIFY_COUNT: attempts,
        },
    }


def escalate_node(state: MangoState) -> dict[str, Any]:
    """Escalate node: terminal interrupt sink when quality gate is exhausted.

    Phase 1 stub: returns immediately. Phase 3 will add ``interrupt()``.
    """
    logger.info("escalate_node: stub (no interrupt in Phase 1)")
    return {
        "verdict": BLOCKED,
    }


__all__ = [
    "CLARIFY_COUNT",
    "QUALITY_GATE_REASON",
    "REASON_ERROR",
    "REASON_INCONCLUSIVE",
    "REASON_TESTS_FAILED",
    "RETRYABLE_REASONS",
    "_conclusive",
    "_nonneg_int_count",
    "_quality_gate_reason",
    "clarify_node",
    "escalate_node",
    "evaluation_node",
    "implementer_node",
    "peer_reviewer_node",
    "plan_gate_node",
    "planner_node",
    "quality_gate_node",
    "security_reviewer_node",
    "shadow_planner_node",
]
