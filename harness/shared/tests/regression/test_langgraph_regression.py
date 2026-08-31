"""AQA & Regression tests for the LangGraph StateGraph engine.

Pins critical runtime invariants and prevents regressions across:
1. Node calling conventions (positional vs keyword RunnableConfig).
2. Input state immutability across node boundaries.
3. 12-channel accumulator list-concatenation vs LWW semantics.
4. Fail-open error isolation and recording to errors channel.
5. Plan gate divergence boundary condition precision (0.35 threshold).
6. Safe fallback and feature detection behavior.
"""

from __future__ import annotations

import copy
from typing import Any
from unittest.mock import MagicMock

import pytest

from harness.shared.governance.verdict import VERIFIED, Verdict
from harness.shared.langgraph.decorators import budgeted, with_authority
from harness.shared.langgraph.graph import build_graph
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
from harness.shared.langgraph.state import (
    ACCUMULATOR_CHANNELS,
    CHANNEL_COUNT,
    DEFAULT_STATE,
    LWW_CHANNELS,
    MangoState,
)


class TestLangGraphNodeInvocationRegression:
    """Pins node calling conventions so LangGraph engine invocation cannot regress."""

    @pytest.mark.parametrize(
        "node_fn",
        [
            planner_node,
            shadow_planner_node,
            implementer_node,
            evaluation_node,
        ],
    )
    def test_node_accepts_single_positional_state(self, node_fn: Any) -> None:
        """Nodes must accept fn(state) without TypeError."""
        state = copy.deepcopy(DEFAULT_STATE)
        result = node_fn(state)
        assert isinstance(result, dict)

    @pytest.mark.parametrize(
        "node_fn",
        [
            planner_node,
            shadow_planner_node,
            implementer_node,
            evaluation_node,
        ],
    )
    def test_node_accepts_two_positional_args(self, node_fn: Any) -> None:
        """Nodes must accept fn(state, config) as LangGraph executes positionally."""
        state = copy.deepcopy(DEFAULT_STATE)
        config = {"configurable": {"test_key": "val"}}
        result = node_fn(state, config)
        assert isinstance(result, dict)

    @pytest.mark.parametrize(
        "node_fn",
        [
            planner_node,
            shadow_planner_node,
            implementer_node,
            evaluation_node,
        ],
    )
    def test_node_accepts_keyword_config(self, node_fn: Any) -> None:
        """Nodes must accept fn(state, config=config, **kwargs)."""
        state = copy.deepcopy(DEFAULT_STATE)
        config = {"configurable": {"test_key": "val"}}
        result = node_fn(state, config=config, extra_param="ignored")
        assert isinstance(result, dict)


class TestLangGraphStateImmutabilityRegression:
    """Pins that nodes do not mutate incoming state dictionaries in-place."""

    @pytest.mark.parametrize(
        "node_fn",
        [
            planner_node,
            shadow_planner_node,
            implementer_node,
            evaluation_node,
            plan_gate_node,
            quality_gate_node,
            clarify_node,
            escalate_node,
            peer_reviewer_node,
            security_reviewer_node,
        ],
    )
    def test_node_does_not_mutate_state(self, node_fn: Any) -> None:
        """State before node execution must equal state after node execution."""
        state = copy.deepcopy(DEFAULT_STATE)
        state["task"] = "sample regression task"
        state["plan"] = "sample plan"
        state["revision_count"] = 1
        state["patches"] = [{"file": "sample.py", "old_text": "", "new_text": "pass", "agent": "test"}]
        original_snapshot = copy.deepcopy(state)

        _ = node_fn(state)

        assert state == original_snapshot, f"Node {node_fn.__name__} mutated state in-place"


class TestLangGraphChannelReducersRegression:
    """Pins that 12-channel state categorisation and reducer rules remain invariant."""

    def test_channel_count_and_disjointness(self) -> None:
        """Accumulator and LWW channels must partition the full channel set."""
        assert len(ACCUMULATOR_CHANNELS) + len(LWW_CHANNELS) == CHANNEL_COUNT
        assert CHANNEL_COUNT == 12
        assert ACCUMULATOR_CHANNELS.isdisjoint(LWW_CHANNELS)

    def test_state_graph_accumulation_over_turns(self) -> None:
        """StateGraph compiled execution must accumulate patches and findings."""
        graph = build_graph()
        initial_state: MangoState = {
            "task": "Test accumulation",
            "patches": [{"file": "init.py", "old_text": "", "new_text": "# init", "agent": "setup"}],
        }

        output = graph.invoke(initial_state)

        # Output must contain original patch plus newly generated patches
        patches = output.get("patches", [])
        assert len(patches) >= 2
        assert patches[0]["file"] == "init.py"
        assert output.get("gate_status", {}).get("quality_gate") == "pass"
        assert output.get("verdict") == "VERIFIED"


class TestLangGraphErrorIsolationRegression:
    """Pins that exceptions inside active nodes fail-open to the errors channel."""

    def test_planner_exception_isolated(self) -> None:
        mock_orch = MagicMock()
        mock_orch.execute_agent.side_effect = RuntimeError("Simulated API rate limit")

        config = {"configurable": {"orchestrator": mock_orch}}
        result = planner_node(DEFAULT_STATE, config)

        assert "errors" in result
        assert len(result["errors"]) == 1
        assert result["errors"][0]["node"] == "planner"
        assert "Simulated API rate limit" in result["errors"][0]["error"]

    def test_implementer_exception_isolated(self) -> None:
        mock_orch = MagicMock()
        mock_orch.execute_agent.side_effect = RuntimeError("Simulated reasoner crash")

        config = {"configurable": {"orchestrator": mock_orch}}
        result = implementer_node(DEFAULT_STATE, config)

        assert "errors" in result
        assert len(result["errors"]) == 1
        assert result["errors"][0]["node"] == "implementer"
        assert "Simulated reasoner crash" in result["errors"][0]["error"]

    def test_evaluation_exception_isolated(self) -> None:
        mock_orch = MagicMock()
        mock_orch.execute_agent.side_effect = RuntimeError("Simulated verification crash")

        config = {"configurable": {"orchestrator": mock_orch}}
        result = evaluation_node(DEFAULT_STATE, config)

        assert "errors" in result
        assert len(result["errors"]) == 1
        assert result["errors"][0]["node"] == "test_eval"
        assert "Simulated verification crash" in result["errors"][0]["error"]


class TestLangGraphDivergenceBoundaryRegression:
    """Pins the exact plan divergence threshold at 0.35."""

    def test_exact_pass_boundary(self) -> None:
        result = plan_gate_node({**DEFAULT_STATE, "plan_divergence": 0.35})
        assert result["gate_status"]["plan_gate"] == "pass"

    def test_exact_fail_boundary(self) -> None:
        result = plan_gate_node({**DEFAULT_STATE, "plan_divergence": 0.35001})
        assert result["gate_status"]["plan_gate"] == "fail"


class TestLangGraphDecoratorsRegression:
    """Pins that authority and budget decorators enforce invariants."""

    def test_budgeted_decorator_blocks_when_exhausted(self) -> None:
        @budgeted(budget_key="tool_budget_used")
        def mock_node(state: dict[str, Any]) -> dict[str, Any]:
            return {"status": "executed"}

        # Simulate exhausted state
        state = {**DEFAULT_STATE, "tool_budget_used": 99999}
        result = mock_node(state)

        assert "errors" in result
        assert "tool budget exhausted" in result["errors"][0]["error"]

    def test_authority_decorator_allows_read_only(self) -> None:
        @with_authority(role="planner", may_write=False)
        def mock_read_node(state: dict[str, Any]) -> dict[str, Any]:
            return {"read": "success"}

        result = mock_read_node(DEFAULT_STATE)
        assert result == {"read": "success"}


class TestLangGraphMockOrchestratorLiveE2E:
    """Pins full E2E execution through LangGraph with simulated orchestrator interactions."""

    def test_full_e2e_graph_with_orchestrator(self) -> None:
        mock_orch = MagicMock()
        mock_orch.execute_agent.side_effect = [
            "# Plan: Step 1, Step 2",  # planner
            "def calculate(): return 42",  # reasoner
            "VERDICT: PASS",  # verifier
        ]
        mock_verdict = Verdict(
            status=VERIFIED,
            reason="all checks passed",
            termination_reason="",
            command="pytest test_suite.py",
            exit_code=0,
        )
        mock_orch._harness_verdict.return_value = mock_verdict

        graph = build_graph()
        config = {"configurable": {"orchestrator": mock_orch}}

        state: MangoState = {"task": "Build calculator"}
        output = graph.invoke(state, config=config)

        assert output.get("plan") == "# Plan: Step 1, Step 2"
        assert len(output.get("patches", [])) >= 1
        assert output.get("patches")[-1]["new_text"] == "def calculate(): return 42"
        assert output.get("test_results")[-1]["passed"] == 1
        assert output.get("test_results")[-1]["failed"] == 0
        assert output.get("verdict") == "VERIFIED"
