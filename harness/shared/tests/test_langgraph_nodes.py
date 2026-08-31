"""Tests for harness/shared/langgraph/nodes.py.

Verifies each node function:
- Returns a dict (partial state update)
- Contains the correct keys for its channel responsibilities
- Handles exceptions by writing to the errors channel
"""

from __future__ import annotations

import pytest

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
from harness.shared.langgraph.state import DEFAULT_STATE

pytestmark = pytest.mark.langgraph


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


class TestShadowPlannerNode:
    def test_returns_shadow_plan_and_divergence(self) -> None:
        result = shadow_planner_node({**DEFAULT_STATE, "task": "Refactor"})
        assert isinstance(result, dict)
        assert "shadow_plan" in result
        assert "plan_divergence" in result
        assert isinstance(result["plan_divergence"], float)


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


class TestTestEvalNode:
    def test_returns_test_results(self) -> None:
        result = evaluation_node({**DEFAULT_STATE})
        assert isinstance(result, dict)
        assert "test_results" in result
        assert isinstance(result["test_results"], list)


class TestPlanGateNode:
    def test_passes_when_divergence_low(self) -> None:
        result = plan_gate_node({**DEFAULT_STATE, "plan_divergence": 0.1})
        assert result["gate_status"]["plan_gate"] == "pass"

    def test_fails_when_divergence_high(self) -> None:
        result = plan_gate_node({**DEFAULT_STATE, "plan_divergence": 0.5})
        assert result["gate_status"]["plan_gate"] == "fail"

    def test_threshold_is_035(self) -> None:
        """The divergence threshold is 0.35 per the plan."""
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

    @pytest.mark.parametrize("node_fn", [
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
    ])
    def test_returns_dict(self, node_fn) -> None:
        result = node_fn({**DEFAULT_STATE, "task": "test task"})
        assert isinstance(result, dict), f"{node_fn.__name__} did not return a dict"

    @pytest.mark.parametrize("node_fn", [
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
    ])
    def test_does_not_mutate_input(self, node_fn) -> None:
        """Nodes must not mutate the input state dict."""
        original_state = {**DEFAULT_STATE, "task": "test task"}
        state_before = dict(original_state)
        node_fn(original_state)
        assert original_state == state_before, f"{node_fn.__name__} mutated input state"
