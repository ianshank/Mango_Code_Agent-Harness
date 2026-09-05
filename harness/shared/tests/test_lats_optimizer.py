"""Tests for Language Agent Tree Search optimizer."""

from __future__ import annotations

from typing import Any

from harness.shared.experimental.lats_optimizer import LATSOptimizer
from harness.shared.langgraph.ablation import AblationNode
from harness.shared.langgraph.state import MangoState


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


def _make_base_state(**overrides: Any) -> MangoState:
    """DRY helper: builds a minimal MangoState with optional overrides."""
    state: MangoState = {
        "task": "test",
        "plan": "",
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
    state.update(overrides)  # type: ignore[typeddict-item]
    return state


def test_lats_max_budget_zero_returns_base_state() -> None:
    """With max_budget=0 no MCTS iterations run; base_state is returned unchanged."""
    opt = LATSOptimizer(max_budget=0)
    base = _make_base_state(plan="original")
    refined = opt.refine_plan(base, lambda s: [{"plan": "changed"}], lambda s: 1.0)
    assert refined["plan"] == "original"


def test_lats_pure_exploitation_selects_highest_score() -> None:
    """exploration_weight=0 makes UCB1 pure exploitation: always picks highest avg score."""
    opt = LATSOptimizer(exploration_weight=0.0, max_budget=1)
    root = AblationNode(state_diff={})
    high = AblationNode(state_diff={"plan": "high"}, visits=1, score=0.9)
    low = AblationNode(state_diff={"plan": "low"}, visits=1, score=0.1)
    root.add_child(low)
    root.add_child(high)

    selected = opt.select(root)
    assert selected == high


def test_lats_select_traverses_deep_tree() -> None:
    """UCB1 select traverses a 3-level tree to find the leaf with highest potential."""
    opt = LATSOptimizer(exploration_weight=1.414, max_budget=1)
    root = AblationNode(state_diff={}, visits=3, score=1.0)
    mid = AblationNode(state_diff={"plan": "mid"}, visits=2, score=0.8)
    root.add_child(mid)
    leaf = AblationNode(state_diff={"plan": "leaf"}, visits=0, score=0.0)
    mid.add_child(leaf)

    selected = opt.select(root)
    assert selected == leaf  # unvisited leaf has UCB1 = inf


def test_lats_backpropagate_deep_chain() -> None:
    """Backpropagation updates scores along a 4-node chain: leaf → mid → root_child → root."""
    opt = LATSOptimizer()
    root = AblationNode(state_diff={})
    child = AblationNode(state_diff={"a": 1})
    grandchild = AblationNode(state_diff={"b": 2})
    root.add_child(child)
    child.add_child(grandchild)

    opt.backpropagate(grandchild, 0.5)
    assert grandchild.visits == 1 and grandchild.score == 0.5
    assert child.visits == 1 and child.score == 0.5
    assert root.visits == 1 and root.score == 0.5


def test_lats_best_leaf_ignores_root() -> None:
    """_best_leaf must never return the root node itself, even if it's the only 'leaf'."""
    opt = LATSOptimizer()
    root = AblationNode(state_diff={}, visits=1, score=1.0)
    assert opt._best_leaf(root) is None
