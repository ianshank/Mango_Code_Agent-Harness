"""Tests for Language Agent Tree Search optimizer."""

from __future__ import annotations

from typing import Any

from harness.shared.langgraph.ablation import AblationNode
from harness.shared.langgraph.state import MangoState
from harness.shared.lats_optimizer import LATSOptimizer


def test_lats_optimizer_ucb1_and_select() -> None:
    """Test UCB1 selection prioritizes unvisited nodes."""
    opt = LATSOptimizer(exploration_weight=1.414, max_budget=5)
    root = AblationNode(state_diff={})
    child1 = AblationNode(state_diff={"action": "1"}, visits=2, score=1.0)
    child2 = AblationNode(state_diff={"action": "2"}, visits=0, score=0.0)
    root.add_child(child1)
    root.add_child(child2)

    assert opt._ucb1(child2, total_visits=2) == float("inf")
    selected = opt.select(root)
    assert selected == child2


def test_lats_optimizer_backpropagate() -> None:
    """Test backpropagation increments visits and propagates score upwards."""
    opt = LATSOptimizer()
    root = AblationNode(state_diff={})
    child = AblationNode(state_diff={"a": 1})
    root.add_child(child)

    opt.backpropagate(child, 0.8)
    assert child.visits == 1
    assert child.score == 0.8
    assert root.visits == 1
    assert root.score == 0.8


def test_lats_refine_plan() -> None:
    """Test full MCTS refinement loop produces optimized state."""
    opt = LATSOptimizer(max_budget=4)
    base_state: MangoState = {
        "task": "optimize",
        "plan": "initial",
        "shadow_plan": "",
        "plan_divergence": 0.0,
        "revision_count": 0,
        "gate_status": {},
        "verdict": "",
        "tool_budget_used": 0,
        "patches": [],
        "findings": [],
        "test_results": [],
        "errors": [],
    }

    def rollout(s: MangoState) -> list[dict[str, Any]]:
        return [{"plan": f"{s.get('plan')}+step"}]

    def evaluate(s: MangoState) -> float:
        return 1.0 if "step" in str(s.get("plan", "")) else 0.0

    refined = opt.refine_plan(base_state, rollout, evaluate)
    assert "step" in str(refined["plan"])


def test_lats_refine_plan_no_children_fallback() -> None:
    """Test refine_plan returns base_state when no children generated."""
    opt = LATSOptimizer(max_budget=1)
    base_state: MangoState = {
        "task": "noop",
        "plan": "initial",
        "shadow_plan": "",
        "plan_divergence": 0.0,
        "revision_count": 0,
        "gate_status": {},
        "verdict": "",
        "tool_budget_used": 0,
        "patches": [],
        "findings": [],
        "test_results": [],
        "errors": [],
    }
    refined = opt.refine_plan(base_state, lambda s: [], lambda s: 0.0)
    assert refined["plan"] == "initial"
