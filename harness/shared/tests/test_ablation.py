"""Tests for LangGraph ablation tracking channel."""

from __future__ import annotations

from harness.shared.langgraph.ablation import AblationChannel, AblationNode
from harness.shared.langgraph.state import MangoState


def test_ablation_tree_structure() -> None:
    """Test building and linking nodes in the ablation tree."""
    root = AblationNode(state_diff={})
    child1 = AblationNode(state_diff={"plan": "step 1"}, action_description="add plan")
    root.add_child(child1)

    assert child1.parent == root
    assert len(root.children) == 1
    assert root.children[0] == child1


def test_ablation_channel_isolated_diff() -> None:
    """Test that hypothetical states do not mutate base MangoState (INV-LG-5)."""
    base_state: MangoState = {
        "task": "solve bug",
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
    channel = AblationChannel(base_state)
    child1 = AblationNode(state_diff={"plan": "step 1"})
    child2 = AblationNode(state_diff={"tool_budget_used": 2})
    channel.root.add_child(child1)
    child1.add_child(child2)

    diff_state = channel.apply_diff(child2)
    assert diff_state["plan"] == "step 1"
    assert diff_state["tool_budget_used"] == 2
    # Ensure base state is untouched
    assert base_state["plan"] == ""
    assert base_state["tool_budget_used"] == 0


def test_ablation_leak_denial() -> None:
    """Nested-mutation regression: mutating a hypothetical state must not corrupt the base.

    A rollout that appends to a mutable nested list (patches, errors, findings)
    must not be visible in subsequent apply_diff calls — confirming that
    deep-copy isolation prevents cross-rollout contamination (INV-LG-5).
    """
    base_state: MangoState = {
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
    channel = AblationChannel(base_state)
    child = AblationNode(state_diff={"patches": [{"file": "a.py", "diff": "+x"}]})
    channel.root.add_child(child)

    # First application gives an isolated copy
    hyp1 = channel.apply_diff(child)
    # Mutate the hypothetical's nested list (simulating a rollout appending data)
    hyp1["patches"].append({"file": "b.py", "diff": "+y"})

    # Second application must reflect only the node's diff, not hyp1's mutation
    hyp2 = channel.apply_diff(child)
    assert len(hyp2["patches"]) == 1, "Mutation of one rollout must not leak into another"

    # The original base_state must also remain clean
    assert base_state["patches"] == [], "Base state must not be modified by any rollout"

