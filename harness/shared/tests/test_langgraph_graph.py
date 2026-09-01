"""Tests for harness/shared/langgraph/graph.py.

Verifies:
- Graph compiles successfully
- Correct number of nodes
- Edge topology matches the architecture diagram
- Routing functions work correctly across all branches
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from harness.shared.langgraph import LANGGRAPH_AVAILABLE
from harness.shared.langgraph.graph import (
    EXPECTED_NODE_COUNT,
    _route_plan_gate,
    _route_quality_gate,
    build_graph,
)
from harness.shared.langgraph.policy import GraphPolicy

pytestmark = pytest.mark.langgraph


class TestRoutingFunctions:
    """Verifies pure routing logic without requiring external framework execution."""

    def test_plan_gate_routes_to_implementer_on_pass(self) -> None:
        result = _route_plan_gate({"gate_status": {"plan_gate": "pass"}})
        assert result == "implementer"

    def test_plan_gate_routes_to_clarify_on_fail(self) -> None:
        result = _route_plan_gate({"gate_status": {"plan_gate": "fail"}})
        assert result == "clarify"

    def test_plan_gate_routes_to_clarify_on_missing(self) -> None:
        result = _route_plan_gate({"gate_status": {}})
        assert result == "clarify"

    def test_quality_gate_routes_to_end_on_pass(self) -> None:
        result = _route_quality_gate({"gate_status": {"quality_gate": "pass"}})
        assert result == "__end__"

    def test_quality_gate_routes_to_implementer_on_fail_with_budget(self) -> None:
        result = _route_quality_gate({
            "gate_status": {"quality_gate": "fail"},
            "revision_count": 2,
        })
        assert result == "implementer"

    def test_quality_gate_routes_to_escalate_on_exhausted(self) -> None:
        result = _route_quality_gate({
            "gate_status": {"quality_gate": "fail"},
            "revision_count": 15,
        })
        assert result == "escalate"


class TestQualityGateRoutingUsesPolicy:
    """docs/specs/langgraph-policy-wiring.md R-LPW-4: the revision cap comes
    from GraphPolicy via config["configurable"]["policy"], not the literal
    10 a prior version hard-coded."""

    def test_custom_lower_cap_escalates_where_default_cap_would_not(self) -> None:
        """revision_count=2 is well under the *default* policy's cap (10),
        which would route to "implementer" -- proving a custom, lower cap
        threaded through configurable is what actually decided "escalate"
        here, not the old literal."""
        custom_policy = GraphPolicy(max_iterations=2)
        config = {"configurable": {"policy": custom_policy}}
        state = {"gate_status": {"quality_gate": "fail"}, "revision_count": 2}
        assert _route_quality_gate(state, config=config) == "escalate"

    def test_custom_lower_cap_still_retries_below_its_own_threshold(self) -> None:
        custom_policy = GraphPolicy(max_iterations=2)
        config = {"configurable": {"policy": custom_policy}}
        state = {"gate_status": {"quality_gate": "fail"}, "revision_count": 1}
        assert _route_quality_gate(state, config=config) == "implementer"

    def test_no_config_falls_back_to_default_policy_cap_unchanged(self) -> None:
        """Bare-state calls (no config at all) must observe identical
        behavior to before this fix: GraphPolicy()'s default is 10, matching
        the literal it replaces."""
        state = {"gate_status": {"quality_gate": "fail"}, "revision_count": 9}
        assert _route_quality_gate(state) == "implementer"
        state = {"gate_status": {"quality_gate": "fail"}, "revision_count": 10}
        assert _route_quality_gate(state) == "escalate"

    def test_accepts_config_via_kwargs_too(self) -> None:
        """Matches the calling-convention contract nodes.py already
        establishes for orchestrator: state, positional config, or keyword
        config must all work."""
        custom_policy = GraphPolicy(max_iterations=1)
        state = {"gate_status": {"quality_gate": "fail"}, "revision_count": 1}
        via_positional = _route_quality_gate(state, {"configurable": {"policy": custom_policy}})
        via_keyword = _route_quality_gate(state, config={"configurable": {"policy": custom_policy}})
        assert via_positional == via_keyword == "escalate"


class TestGraphBuilderWithMock:
    """Verifies graph assembly and edge wiring using builder mock."""

    def test_build_graph_assembles_nodes_and_edges(self) -> None:
        mock_builder_cls = MagicMock()
        mock_builder_instance = MagicMock()
        mock_builder_cls.return_value = mock_builder_instance
        mock_compiled = MagicMock()
        mock_compiled.nodes = {"planner": MagicMock()}
        mock_builder_instance.compile.return_value = mock_compiled

        with patch("harness.shared.langgraph.graph.StateGraph", mock_builder_cls):
            custom_policy = GraphPolicy(recursion_limit=42)
            compiled = build_graph(policy=custom_policy)
            assert compiled == mock_compiled
            assert mock_builder_instance.add_node.call_count == EXPECTED_NODE_COUNT
            assert mock_builder_instance.add_edge.call_count >= 5
            assert mock_builder_instance.add_conditional_edges.call_count == 2
            mock_builder_instance.compile.assert_called_once_with(checkpointer=None)

    def test_build_graph_raises_when_stategraph_is_none(self) -> None:
        with patch("harness.shared.langgraph.graph.StateGraph", None):
            with pytest.raises(RuntimeError, match="langgraph library is required"):
                build_graph()

    def test_default_policy_is_loaded_from_governance_json(self) -> None:
        """R-LPW-3: build_graph() with no policy argument must call
        GraphPolicy.from_governance_json(), not silently compile a bare
        GraphPolicy() that skips policy loading entirely (the prior bug)."""
        mock_builder_cls = MagicMock()
        mock_compiled = MagicMock()
        mock_compiled.nodes = {"planner": MagicMock()}
        mock_builder_cls.return_value.compile.return_value = mock_compiled

        sentinel_policy = GraphPolicy(recursion_limit=777)
        with (
            patch("harness.shared.langgraph.graph.StateGraph", mock_builder_cls),
            patch(
                "harness.shared.langgraph.graph.GraphPolicy.from_governance_json",
                return_value=sentinel_policy,
            ) as mock_from_governance_json,
        ):
            build_graph()  # no policy argument
            mock_from_governance_json.assert_called_once()


@pytest.mark.skipif(not LANGGRAPH_AVAILABLE, reason="langgraph not installed")
class TestLiveGraphExecution:
    """Runs live graph compilation and invocation when langgraph is installed."""

    def test_graph_compiles_live(self) -> None:
        graph = build_graph()
        assert graph is not None

    def test_graph_node_count_live(self) -> None:
        graph = build_graph()
        user_nodes = {k for k in graph.nodes if not k.startswith("__")}
        assert len(user_nodes) == EXPECTED_NODE_COUNT

    def test_graph_has_all_expected_nodes_live(self) -> None:
        graph = build_graph()
        expected = {
            "planner",
            "shadow_planner",
            "plan_gate",
            "clarify",
            "implementer",
            "peer_reviewer",
            "security_reviewer",
            "test_eval",
            "quality_gate",
            "escalate",
        }
        actual = {k for k in graph.nodes if not k.startswith("__")}
        assert actual == expected

    def test_happy_path_produces_verdict_live(self) -> None:
        from harness.shared.langgraph.state import DEFAULT_STATE

        graph = build_graph()
        result = graph.invoke({**DEFAULT_STATE, "task": "test task"})
        assert "verdict" in result
        assert result["verdict"] in ("VERIFIED", "FAILED", "BLOCKED", "")
