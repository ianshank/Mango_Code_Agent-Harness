"""LangGraph node functions for the MangoMAS orchestration graph.

Each function wraps an existing orchestrator method as a LangGraph node.
Node contracts:

1. Accept ``(state: MangoState)`` or ``(state: MangoState, config: RunnableConfig)``
2. Return ``dict`` (partial state update) — never mutate state in-place
3. Wrap side effects in ``try/except``, write failures to ``errors`` channel
4. No side effects before ``interrupt()`` (re-execution hazard)

Phase 1 implements the 3 active nodes (planner, implementer, verifier) as thin
wrappers around ``MangoMASOrchestrator.execute_agent``.  The remaining 7 nodes
are stubs that return minimal state updates for topology validation.
"""

from __future__ import annotations

import logging
import traceback
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from harness.shared.mango_mas_orchestrator import MangoMASOrchestrator

from harness.shared.agent_prompts import (
    PLANNER_PROMPT_TEMPLATE,
    REASONER_PROMPT_TEMPLATE,
    VERIFIER_PROMPT_TEMPLATE,
)
from harness.shared.governance.verdict import BLOCKED, FAILED, VERIFIED
from harness.shared.langgraph.decorators import budgeted, with_authority
from harness.shared.langgraph.errors import blocking_error, error_record
from harness.shared.langgraph.policy import GraphPolicy
from harness.shared.langgraph.state import MangoState
from harness.shared.meta_tools import format_gaps_for_planner, load_open_gaps

#: ``gate_status`` keys this module writes beside the per-gate outcomes.
#: ``quality_gate_reason`` tells ``_route_quality_gate`` *why* the gate failed,
#: so a deterministic failure escalates instead of consuming revision budget;
#: ``clarify_count`` bounds the plan_gate/clarify cycle. Both live in the
#: existing dict channel rather than as new channels, so ``CHANNEL_COUNT``
#: (INV-LG-1) is unchanged (C-LGH-2).
QUALITY_GATE_REASON = "quality_gate_reason"
CLARIFY_COUNT = "clarify_count"

#: Why ``quality_gate_node`` withheld a pass.
REASON_ERROR = "error"
REASON_INCONCLUSIVE = "inconclusive"
REASON_TESTS_FAILED = "tests_failed"

#: The only reason a revision can fix, and therefore the only one that may
#: spend revision budget. Stated as the *retryable* set rather than the
#: terminal one so that a new reason is terminal until someone argues
#: otherwise — the first version listed the terminal reason instead, and
#: ``REASON_INCONCLUSIVE`` fell through to the retry loop by omission.
#:
#: A failing suite is retryable because the implementer is handed the failure
#: message and can act on it. The other two are not: ``errors`` is an
#: ``operator.add`` accumulator no node clears, so the record that failed the
#: gate is still there next pass; and an inconclusive result means the
#: verification path produced no evidence, which nothing inside the loop can
#: change. Retrying either spends a write-capable revision per attempt to
#: reach the same terminal (R-LGH-3, R-LGH-8).
RETRYABLE_REASONS = frozenset({REASON_TESTS_FAILED})

logger = logging.getLogger(__name__)


def _get_configurable(config: Any = None, kwargs: dict[str, Any] | None = None) -> dict[str, Any]:
    """Helper to extract configurable dict whether passed positionally or via kwargs."""
    if isinstance(config, dict):
        cfg = config.get("configurable", {})
        if isinstance(cfg, dict):
            return dict(cfg)
    if config is not None and hasattr(config, "get"):
        cfg = config.get("configurable", {})
        if isinstance(cfg, dict):
            return dict(cfg)
    if kwargs and "configurable" in kwargs:
        cfg = kwargs.get("configurable", {})
        if isinstance(cfg, dict):
            return dict(cfg)
    return {}


# ── Active nodes (wrap existing orchestrator methods) ────────


@with_authority("planner", may_write=False)
def planner_node(state: MangoState, config=None, **_kwargs: Any) -> dict[str, Any]:
    """Planner agent: generates a plan from the task description.

    Wraps ``MangoMASOrchestrator.execute_agent("planner", ...)``.
    Phase 1: returns a stub plan.  Phase 2: uses real orchestrator.
    """
    try:
        task = state.get("task", "")
        logger.info("planner_node: generating plan for task=%s...", task[:80])

        configurable = _get_configurable(config, _kwargs)
        orchestrator: MangoMASOrchestrator | None = configurable.get("orchestrator")

        if orchestrator:
            open_gaps = format_gaps_for_planner(load_open_gaps(orchestrator.workspace_dir))
            planner_prompt = PLANNER_PROMPT_TEMPLATE.format(task=task, open_gaps=open_gaps)
            plan = orchestrator.execute_agent("planner", planner_prompt, tools=[])
        else:
            plan = f"[PLAN] Analyse and implement: {task[:200]}"

        return {
            "plan": plan,
            "revision_count": state.get("revision_count", 0),
        }
    except Exception as exc:  # noqa: BLE001
        logger.error("planner_node failed: %s", exc)
        return {"errors": [error_record("planner", exc, traceback.format_exc())]}


@with_authority("planner", may_write=False)
def shadow_planner_node(state: MangoState, config=None, **_kwargs: Any) -> dict[str, Any]:
    """Shadow planner: generates an independent plan for divergence comparison.

    Runs a cheaper/different model.  Phase 1: returns a stub shadow plan.
    """
    try:
        task = state.get("task", "")
        logger.info("shadow_planner_node: generating shadow plan...")
        return {
            "shadow_plan": f"[SHADOW] Alternative approach: {task[:200]}",
            "plan_divergence": 0.0,  # No real comparison yet
        }
    except Exception as exc:  # noqa: BLE001
        logger.error("shadow_planner_node failed: %s", exc)
        return {"errors": [error_record("shadow_planner", exc, traceback.format_exc())]}


@with_authority("nemotron-reasoner", may_write=True)
@budgeted("tool_budget_used")
def implementer_node(state: MangoState, config=None, **_kwargs: Any) -> dict[str, Any]:
    """Implementer (nemotron-reasoner): applies patches to implement the plan.

    Wraps ``MangoMASOrchestrator.execute_agent("nemotron-reasoner", ...)``.
    Phase 2: Uses the real orchestrator to generate implementations.
    """
    try:
        from harness.shared.policy_loader import max_tool_calls_per_task
        from harness.shared.tool_budget import ToolBudget

        revision = state.get("revision_count", 0)
        plan = state.get("plan", "")
        logger.info("implementer_node: implementing plan (revision=%d)...", revision)

        configurable = _get_configurable(config, _kwargs)
        orchestrator: MangoMASOrchestrator | None = configurable.get("orchestrator")

        if orchestrator:
            reasoner_prompt = REASONER_PROMPT_TEMPLATE.format(plan=plan)
            test_results = state.get("test_results", [])
            last_result = test_results[-1] if test_results else {}
            prior_failed = _nonneg_int_count(last_result.get("failed")) if isinstance(last_result, dict) else None
            if (
                prior_failed is not None
                and prior_failed > 0
                and isinstance(last_result, dict)
                and last_result.get("message")
            ):
                reasoner_prompt += (
                    f"\n\nPREVIOUS TEST FAILURE (Revision {revision}):\n"
                    f"{last_result.get('message')}\n"
                    "Please analyze the failure and fix the implementation."
                )
            # Build a shared budget initialised from the cumulative state counter so
            # the per-task limit is enforced across all revisions, not per-revision.
            budget_limit = max_tool_calls_per_task()
            already_used = state.get("tool_budget_used", 0)
            task_budget = ToolBudget(limit=budget_limit, used=already_used)
            code_output = orchestrator.execute_agent("nemotron-reasoner", reasoner_prompt, budget=task_budget)
            patches = [{"file": "implemented", "old_text": "", "new_text": code_output, "agent": "nemotron-reasoner"}]
            new_budget_used = task_budget.used
        else:
            patches = [{"file": "stub.py", "old_text": "", "new_text": "# implemented", "agent": "implementer"}]
            new_budget_used = state.get("tool_budget_used", 0) + 1

        return {
            "patches": patches,
            "revision_count": revision + 1,
            "tool_budget_used": new_budget_used,
        }
    except Exception as exc:  # noqa: BLE001
        logger.error("implementer_node failed: %s", exc)
        return {"errors": [error_record("implementer", exc, traceback.format_exc())]}


@with_authority("verifier", may_write=False)
def evaluation_node(state: MangoState, config=None, **_kwargs: Any) -> dict[str, Any]:
    """Test evaluator: runs the verification suite.

    Wraps ``VerificationRunner.run()`` and the verifier agent.
    Phase 1: returns a stub result. Phase 2: uses real orchestrator.
    """
    try:
        logger.info("evaluation_node: running verification...")

        configurable = _get_configurable(config, _kwargs)
        orchestrator: MangoMASOrchestrator | None = configurable.get("orchestrator")

        if orchestrator:
            # Extract code_output produced by the implementer node from patches
            patches = state.get("patches", [])
            last_patch = patches[-1] if patches else {}
            code_output = last_patch.get("new_text", "") if isinstance(last_patch, dict) else ""
            if not code_output:
                code_output = f"Implemented plan: {state.get('plan', '')[:200]}"

            prompt = VERIFIER_PROMPT_TEMPLATE.format(code_output=code_output)
            verification = orchestrator.execute_agent("verifier", prompt)

            # Use real test runner if configured
            verdict = orchestrator._harness_verdict()
            passed = 1 if verdict.is_pass else 0
            failed = 0 if verdict.is_pass else 1

            test_results = [
                {
                    "suite": "pytest",
                    "passed": passed,
                    "failed": failed,
                    "skipped": 0,
                    "message": verification,
                }
            ]
        else:
            test_results = [{"suite": "pytest", "passed": 0, "failed": 0, "skipped": 0}]

        return {
            "test_results": test_results,
        }
    except Exception as exc:  # noqa: BLE001
        logger.error("evaluation_node failed: %s", exc)
        return {"errors": [error_record("test_eval", exc, traceback.format_exc())]}


# ── Gate/routing nodes ───────────────────────────────────────


def plan_gate_node(state: MangoState, config=None, **_kwargs: Any) -> dict:
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


def _nonneg_int_count(value: object) -> int | None:
    """Return ``value`` when it is a non-boolean, non-negative int; else ``None``.

    ``bool`` is a subclass of ``int``, so ``True`` must be rejected explicitly:
    otherwise ``{"passed": True, "failed": 0}`` would look like a green suite.
    """
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    if value < 0:
        return None
    return value


def _conclusive(latest: object) -> bool:
    """Whether a ``test_results`` entry is evidence that a suite actually ran.

    ``passed == failed == 0`` is the shape ``evaluation_node`` returns on its
    no-orchestrator path, and grading it by ``failed > 0`` alone made zero
    executed tests indistinguishable from a green suite. DEC-024 makes an
    absence of evidence a non-pass, so it is graded as one (R-LGH-2).

    Both ``passed`` and ``failed`` MUST be present and MUST be non-boolean,
    non-negative integers before either is summed. A malformed or incomplete
    row (negative counts, strings, booleans, missing keys) is inconclusive,
    never a raise and never a vacuous pass (Copilot review on PR #87).
    """
    if not isinstance(latest, dict):
        return False
    if "passed" not in latest or "failed" not in latest:
        logger.debug(
            "test_results row inconclusive: missing passed/failed keys (keys=%s)",
            sorted(latest.keys()),
        )
        return False
    passed = _nonneg_int_count(latest.get("passed"))
    failed = _nonneg_int_count(latest.get("failed"))
    if passed is None or failed is None:
        logger.debug(
            "test_results row inconclusive: malformed counts passed=%r failed=%r",
            latest.get("passed"),
            latest.get("failed"),
        )
        return False
    return passed + failed > 0


def _quality_gate_reason(state: MangoState) -> str | None:
    """Why the quality gate withholds a pass, or ``None`` when it grants one."""
    if blocking_error(state.get("errors", [])) is not None:
        return REASON_ERROR
    test_results = state.get("test_results", [])
    latest = test_results[-1] if test_results else None
    if not _conclusive(latest):
        return REASON_INCONCLUSIVE
    # ``_conclusive`` already proved ``latest`` is a dict with valid counts;
    # re-read through the same helper so the gate never raises on bad input.
    if not isinstance(latest, dict):
        return REASON_INCONCLUSIVE
    failed = _nonneg_int_count(latest.get("failed"))
    if failed is None:
        return REASON_INCONCLUSIVE
    if failed > 0:
        return REASON_TESTS_FAILED
    return None


def quality_gate_node(state: MangoState) -> dict:
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


def clarify_node(state: MangoState) -> dict:
    """Clarify node: pauses for human input when plan gate fails.

    Phase 1 stub: returns immediately.  Phase 3 will add ``interrupt()``.

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


def escalate_node(state: MangoState) -> dict:
    """Escalate node: terminal interrupt sink when quality gate is exhausted.

    Phase 1 stub: returns immediately.  Phase 3 will add ``interrupt()``.
    """
    logger.info("escalate_node: stub (no interrupt in Phase 1)")
    return {
        "verdict": BLOCKED,
    }


# ── Review nodes (Phase 5 fan-out) ──────────────────────────


@with_authority("verifier", may_write=False)
def peer_reviewer_node(state: MangoState) -> dict:
    """Peer reviewer: reviews patches for correctness.

    Phase 1 stub.  Phase 5 will run in parallel with security_reviewer.
    """
    logger.info("peer_reviewer_node: stub")
    return {
        "findings": [
            {
                "severity": "info",
                "message": "peer review stub",
                "agent": "peer_reviewer",
                "file": "",
                "line": 0,
            }
        ],
    }


@with_authority("verifier", may_write=False)
def security_reviewer_node(state: MangoState) -> dict[str, Any]:
    """Security reviewer: reviews patches for security issues.

    Phase 1 stub.  Phase 5 will run in parallel with peer_reviewer.
    """
    logger.info("security_reviewer_node: stub")
    return {
        "findings": [
            {
                "severity": "info",
                "message": "security review stub",
                "agent": "security_reviewer",
                "file": "",
                "line": 0,
            }
        ],
    }


__all__ = [
    "CLARIFY_COUNT",
    "QUALITY_GATE_REASON",
    "REASON_ERROR",
    "REASON_INCONCLUSIVE",
    "REASON_TESTS_FAILED",
    "RETRYABLE_REASONS",
    "clarify_node",
    "escalate_node",
    "implementer_node",
    "peer_reviewer_node",
    "plan_gate_node",
    "planner_node",
    "quality_gate_node",
    "security_reviewer_node",
    "shadow_planner_node",
    "evaluation_node",
]
