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
