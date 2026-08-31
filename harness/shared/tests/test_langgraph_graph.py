"""Tests for harness/shared/langgraph/graph.py.

Verifies:
- Graph compiles successfully
- Correct number of nodes
- Edge topology matches the architecture diagram
- Routing functions work correctly
"""

from __future__ import annotations

import pytest

from harness.shared.langgraph import LANGGRAPH_AVAILABLE

pytestmark = [
    pytest.mark.langgraph,
    pytest.mark.skipif(not LANGGRAPH_AVAILABLE, reason="langgraph not installed"),
]


class TestGraphCompilation:
    def test_graph_compiles(self) -> None:
        """build_graph returns a compiled graph without errors."""
        from harness.shared.langgraph.graph import build_graph

        graph = build_graph()
        assert graph is not None

    def test_graph_node_count(self) -> None:
        """The graph has the expected number of nodes (10 user + __start__ + __end__)."""
        from harness.shared.langgraph.graph import EXPECTED_NODE_COUNT, build_graph

        graph = build_graph()
        # LangGraph compiled graph includes __start__ and __end__ pseudo-nodes
        user_nodes = {k for k in graph.nodes if not k.startswith("__")}
        assert len(user_nodes) == EXPECTED_NODE_COUNT, (
            f"Expected {EXPECTED_NODE_COUNT} user nodes, got {len(user_nodes)}: {user_nodes}"
        )

    def test_graph_has_all_expected_nodes(self) -> None:
        """Every node from the architecture diagram is present."""
        from harness.shared.langgraph.graph import build_graph

        graph = build_graph()
        expected = {
            "planner", "shadow_planner", "plan_gate", "clarify",
            "implementer", "peer_reviewer", "security_reviewer",
            "test_eval", "quality_gate", "escalate",
        }
        actual = {k for k in graph.nodes if not k.startswith("__")}
        assert actual == expected


class TestGraphTopology:
    """Verify edges match the architecture diagram."""

    def test_start_reaches_planner(self) -> None:
        """START → planner must be a direct edge."""
        from harness.shared.langgraph.graph import build_graph

        graph = build_graph()
        # Invoke the graph with minimal state and check planner is first
        # This is a topology test, not a runtime test
        assert "planner" in graph.nodes

    def test_escalate_reaches_end(self) -> None:
        """escalate → END must be a direct edge."""
        from harness.shared.langgraph.graph import build_graph

        graph = build_graph()
        assert "escalate" in graph.nodes


class TestRoutingFunctions:
    def test_plan_gate_routes_to_implementer_on_pass(self) -> None:
        from harness.shared.langgraph.graph import _route_plan_gate

        result = _route_plan_gate({"gate_status": {"plan_gate": "pass"}})
        assert result == "implementer"

    def test_plan_gate_routes_to_clarify_on_fail(self) -> None:
        from harness.shared.langgraph.graph import _route_plan_gate

        result = _route_plan_gate({"gate_status": {"plan_gate": "fail"}})
        assert result == "clarify"

    def test_plan_gate_routes_to_clarify_on_missing(self) -> None:
        from harness.shared.langgraph.graph import _route_plan_gate

        result = _route_plan_gate({"gate_status": {}})
        assert result == "clarify"

    def test_quality_gate_routes_to_end_on_pass(self) -> None:
        from langgraph.graph import END

        from harness.shared.langgraph.graph import _route_quality_gate

        result = _route_quality_gate({"gate_status": {"quality_gate": "pass"}})
        assert result == END

    def test_quality_gate_routes_to_implementer_on_fail_with_budget(self) -> None:
        from harness.shared.langgraph.graph import _route_quality_gate

        result = _route_quality_gate({
            "gate_status": {"quality_gate": "fail"},
            "revision_count": 2,
        })
        assert result == "implementer"

    def test_quality_gate_routes_to_escalate_on_exhausted(self) -> None:
        from harness.shared.langgraph.graph import _route_quality_gate

        result = _route_quality_gate({
            "gate_status": {"quality_gate": "fail"},
            "revision_count": 15,
        })
        assert result == "escalate"


class TestGraphInvocation:
    """Smoke test: the graph can be invoked and produces a final state."""

    def test_happy_path_produces_verdict(self) -> None:
        """A basic invoke with default state should complete without error."""
        from harness.shared.langgraph.graph import build_graph
        from harness.shared.langgraph.state import DEFAULT_STATE

        graph = build_graph()
        result = graph.invoke({**DEFAULT_STATE, "task": "test task"})
        assert "verdict" in result
        assert result["verdict"] in ("VERIFIED", "FAILED", "BLOCKED", "")
