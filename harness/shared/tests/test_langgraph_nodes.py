"""Tests for harness/shared/langgraph/nodes.py.

Verifies each node function:
- Returns a dict (partial state update)
- Contains the correct keys for its channel responsibilities
- Handles exceptions by writing to the errors channel
- Integrates with configurable orchestrator
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from harness.shared.governance.verdict import VERIFIED, Verdict
from harness.shared.langgraph.nodes import (
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
from harness.shared.langgraph.state import DEFAULT_STATE, MangoState

pytestmark = pytest.mark.langgraph


class TestGetConfigurableHelper:
    """Verifies configurable extraction helper for various RunnableConfig inputs."""

    def test_extract_from_dict_config(self) -> None:
        cfg = {"configurable": {"orchestrator": "orch1"}}
        res = _get_configurable(cfg)
        assert res == {"orchestrator": "orch1"}

    def test_extract_from_object_with_get(self) -> None:
        class FakeConfig:
            def get(self, key: str, default: object = None) -> object:
                if key == "configurable":
                    return {"orchestrator": "orch2"}
                return default

        res = _get_configurable(FakeConfig())  # type: ignore[arg-type]
        assert res == {"orchestrator": "orch2"}

    def test_extract_from_kwargs(self) -> None:
        res = _get_configurable(None, {"configurable": {"orchestrator": "orch3"}})
        assert res == {"orchestrator": "orch3"}

    def test_extract_empty_when_missing(self) -> None:
        assert _get_configurable(None, None) == {}
        assert _get_configurable({}, {}) == {}


class TestPlannerNode:
    def test_returns_plan(self) -> None:
        result = planner_node({**DEFAULT_STATE, "task": "Fix the bug"})
        assert isinstance(result, dict)
        assert "plan" in result
        assert "Fix the bug" in result["plan"]

    def test_empty_task(self) -> None:
        result = planner_node({**DEFAULT_STATE})
        assert isinstance(result, dict)
        assert "plan" in result

    def test_planner_with_orchestrator(self) -> None:
        mock_orch = MagicMock()
        mock_orch.execute_agent.return_value = "Custom Generated Plan"
        config = {"configurable": {"orchestrator": mock_orch}}

        result = planner_node({**DEFAULT_STATE, "task": "Custom Task"}, config=config)
        assert result["plan"] == "Custom Generated Plan"
        mock_orch.execute_agent.assert_called_once()

    def test_planner_exception_handling(self) -> None:
        mock_orch = MagicMock()
        mock_orch.execute_agent.side_effect = RuntimeError("Planner failed")
        config = {"configurable": {"orchestrator": mock_orch}}

        result = planner_node({**DEFAULT_STATE, "task": "Crash"}, config=config)
        assert "errors" in result
        assert result["errors"][0]["node"] == "planner"
        assert "Planner failed" in result["errors"][0]["error"]


class TestShadowPlannerNode:
    def test_returns_shadow_plan_and_divergence(self) -> None:
        result = shadow_planner_node({**DEFAULT_STATE, "task": "Refactor"})
        assert isinstance(result, dict)
        assert "shadow_plan" in result
        assert "plan_divergence" in result
        assert isinstance(result["plan_divergence"], float)

    def test_shadow_planner_exception_handling(self) -> None:
        bad_state = MagicMock()
        bad_state.get.side_effect = RuntimeError("Bad state")
        result = shadow_planner_node(bad_state)
        assert "errors" in result
        assert result["errors"][0]["node"] == "shadow_planner"


class TestImplementerNode:
    def test_returns_patches_and_increments_revision(self) -> None:
        result = implementer_node({**DEFAULT_STATE, "plan": "do stuff", "revision_count": 2})
        assert isinstance(result, dict)
        assert "patches" in result
        assert isinstance(result["patches"], list)
        assert len(result["patches"]) >= 1
        assert result["revision_count"] == 3

    def test_increments_tool_budget(self) -> None:
        result = implementer_node({**DEFAULT_STATE, "tool_budget_used": 5})
        assert result["tool_budget_used"] == 6

    def test_implementer_with_orchestrator(self) -> None:
        mock_orch = MagicMock()
        mock_orch.execute_agent.return_value = "def foo(): pass"
        config = {"configurable": {"orchestrator": mock_orch}}

        result = implementer_node({**DEFAULT_STATE, "plan": "Write code"}, config=config)
        assert result["patches"][0]["new_text"] == "def foo(): pass"
        mock_orch.execute_agent.assert_called_once()

    def test_implementer_exception_handling(self) -> None:
        mock_orch = MagicMock()
        mock_orch.execute_agent.side_effect = RuntimeError("Implementer error")
        config = {"configurable": {"orchestrator": mock_orch}}

        result = implementer_node({**DEFAULT_STATE, "plan": "Crash"}, config=config)
        assert "errors" in result
        assert result["errors"][0]["node"] == "implementer"


class TestTestEvalNode:
    def test_returns_test_results_stub(self) -> None:
        result = evaluation_node({**DEFAULT_STATE})
        assert isinstance(result, dict)
        assert "test_results" in result
        assert isinstance(result["test_results"], list)

    def test_eval_with_orchestrator_pass(self) -> None:
        mock_orch = MagicMock()
        mock_orch.execute_agent.return_value = "Tests all passed"
        mock_orch._harness_verdict.return_value = Verdict(
            status=VERIFIED,
            reason="",
            termination_reason="",
            command="make test-python",
            exit_code=0,
        )
        config = {"configurable": {"orchestrator": mock_orch}}

        state: MangoState = {
            **DEFAULT_STATE,
            "patches": [{"file": "f.py", "old_text": "", "new_text": "code", "agent": "nemotron-reasoner"}],
            "plan": "sample plan",
        }
        result = evaluation_node(state, config=config)
        assert result["test_results"][0]["passed"] == 1
        assert result["test_results"][0]["failed"] == 0

    def test_eval_with_orchestrator_fail_and_no_patches(self) -> None:
        mock_orch = MagicMock()
        mock_orch.execute_agent.return_value = "Tests failed"
        mock_orch._harness_verdict.return_value = Verdict(
            status="FAILED",
            reason="test error",
            termination_reason="",
            command="make test-python",
            exit_code=1,
        )
        config = {"configurable": {"orchestrator": mock_orch}}

        state: MangoState = {
            **DEFAULT_STATE,
            "patches": [],
            "plan": "sample plan without patches",
        }
        result = evaluation_node(state, config=config)
        assert result["test_results"][0]["passed"] == 0
        assert result["test_results"][0]["failed"] == 1

    def test_eval_exception_handling(self) -> None:
        mock_orch = MagicMock()
        mock_orch.execute_agent.side_effect = RuntimeError("Eval error")
        config = {"configurable": {"orchestrator": mock_orch}}

        result = evaluation_node({**DEFAULT_STATE}, config=config)
        assert "errors" in result
        assert result["errors"][0]["node"] == "test_eval"


class TestPlanGateNode:
    def test_passes_when_divergence_low(self) -> None:
        result = plan_gate_node({**DEFAULT_STATE, "plan_divergence": 0.1})
        assert result["gate_status"]["plan_gate"] == "pass"

    def test_fails_when_divergence_high(self) -> None:
        result = plan_gate_node({**DEFAULT_STATE, "plan_divergence": 0.5})
        assert result["gate_status"]["plan_gate"] == "fail"

    def test_threshold_is_035(self) -> None:
        pass_result = plan_gate_node({**DEFAULT_STATE, "plan_divergence": 0.35})
        fail_result = plan_gate_node({**DEFAULT_STATE, "plan_divergence": 0.36})
        assert pass_result["gate_status"]["plan_gate"] == "pass"
        assert fail_result["gate_status"]["plan_gate"] == "fail"


class TestQualityGateNode:
    def test_passes_in_stub(self) -> None:
        result = quality_gate_node({**DEFAULT_STATE})
        assert result["gate_status"]["quality_gate"] == "pass"
        assert result["verdict"] == "VERIFIED"


class TestClarifyNode:
    def test_returns_gate_pass(self) -> None:
        result = clarify_node({**DEFAULT_STATE})
        assert result["gate_status"]["plan_gate"] == "pass"


class TestEscalateNode:
    def test_returns_blocked_verdict(self) -> None:
        result = escalate_node({**DEFAULT_STATE})
        assert result["verdict"] == "BLOCKED"


class TestReviewerNodes:
    def test_peer_reviewer_returns_findings(self) -> None:
        result = peer_reviewer_node({**DEFAULT_STATE})
        assert "findings" in result
        assert len(result["findings"]) >= 1
        assert result["findings"][0]["agent"] == "peer_reviewer"

    def test_security_reviewer_returns_findings(self) -> None:
        result = security_reviewer_node({**DEFAULT_STATE})
        assert "findings" in result
        assert len(result["findings"]) >= 1
        assert result["findings"][0]["agent"] == "security_reviewer"


class TestNodeContract:
    """Every node must return a dict (never None or mutate state)."""

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
    def test_returns_dict(self, node_fn: object) -> None:
        result = node_fn({**DEFAULT_STATE, "task": "test task"})  # type: ignore[operator]
        assert isinstance(result, dict), f"{getattr(node_fn, '__name__', str(node_fn))} did not return a dict"

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
    def test_does_not_mutate_input(self, node_fn: object) -> None:
        """Nodes must not mutate the input state dict."""
        original_state = {**DEFAULT_STATE, "task": "test task"}
        state_before = dict(original_state)
        node_fn(original_state)  # type: ignore[operator]
        assert original_state == state_before, (
            f"{getattr(node_fn, '__name__', str(node_fn))} mutated input state"
        )
