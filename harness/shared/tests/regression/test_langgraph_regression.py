"""AQA & Regression tests for the LangGraph StateGraph engine.

Pins critical runtime invariants and prevents regressions across:
1. Node calling conventions (positional vs keyword RunnableConfig).
2. Input state immutability across node boundaries.
3. 12-channel accumulator list-concatenation vs LWW semantics.
4. Contained error isolation and recording to the errors channel (INV-LG-3).
5. Fail-closed verdict: a blocking error or an inconclusive result cannot
   reach VERIFIED, while an observation-plane failure stays non-blocking
   per INV-16 (INV-LG-6).
6. Termination of the plan_gate/clarify cycle at its policy bound (INV-LG-6).
7. Plan gate divergence boundary condition precision (0.35 threshold).
8. Safe fallback and feature detection behavior.
"""

from __future__ import annotations

import copy
from typing import Any
from unittest.mock import MagicMock

import pytest

from harness.shared.governance.verdict import BLOCKED, VERIFIED, Verdict
from harness.shared.langgraph import LANGGRAPH_AVAILABLE
from harness.shared.langgraph.decorators import budgeted, with_authority
from harness.shared.langgraph.errors import error_record
from harness.shared.langgraph.graph import runtime_config
from harness.shared.langgraph.nodes import (
    CLARIFY_COUNT,
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
from harness.shared.langgraph.policy import GraphPolicy
from harness.shared.langgraph.state import (
    ACCUMULATOR_CHANNELS,
    CHANNEL_COUNT,
    DEFAULT_STATE,
    LWW_CHANNELS,
    MangoState,
)

pytestmark = [
    pytest.mark.langgraph,
    pytest.mark.skipif(not LANGGRAPH_AVAILABLE, reason="langgraph not installed (DEC-026)"),
]


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
        from harness.shared.langgraph.graph import build_graph

        graph = build_graph()
        initial_state: MangoState = {
            "task": "Test accumulation",
            "patches": [{"file": "init.py", "old_text": "", "new_text": "# init", "agent": "setup"}],
        }

        output = graph.invoke(initial_state, config=runtime_config(GraphPolicy(max_iterations=2)))

        # Output must contain original patch plus newly generated patches
        patches = output.get("patches", [])
        assert len(patches) >= 2
        assert patches[0]["file"] == "init.py"
        # This path has no orchestrator, so `evaluation_node` reports
        # `passed=0, failed=0`. The two assertions here used to read `pass` and
        # `VERIFIED` from exactly that row — a third instance of the vacuous
        # pass R-LGH-2 closes, incidental to what this test is for. Accumulation
        # is unaffected either way, which is the regression being pinned.
        assert output.get("gate_status", {}).get("quality_gate") == "fail"
        assert output.get("verdict") == BLOCKED


class TestLangGraphErrorIsolationRegression:
    """Pins INV-LG-3: an exception inside an active node is contained in the
    `errors` channel rather than propagating. What the gate then does with
    that record is INV-LG-6, pinned by TestControlPlaneErrorIsTerminal."""

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

        from harness.shared.langgraph.graph import build_graph

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


class TestControlPlaneErrorIsTerminal:
    """docs/specs/langgraph-fail-open-hardening.md R-LGH-1, R-LGH-3.

    Reproduces the defect end to end: a node returning the exact denial record
    ``@with_authority`` writes on a refused role used to leave the run
    ``VERIFIED`` over an empty plan, because nothing read the ``errors``
    channel — ``_route_plan_gate`` and ``_route_quality_gate`` decided on
    ``gate_status`` and ``revision_count``, and ``quality_gate_node`` consulted
    ``errors`` only when ``test_results`` was empty, which no path through the
    compiled graph produces.
    """

    @staticmethod
    def _denied(state: Any, config=None, **_kwargs: Any) -> dict[str, Any]:
        return {"errors": [error_record("planner", "role 'planner' lacks read authority")]}

    def test_denied_planner_does_not_reach_a_verified_verdict(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import harness.shared.langgraph.graph as graph_module

        monkeypatch.setattr(graph_module, "planner_node", self._denied)
        graph = graph_module.build_graph()

        output = graph.invoke(
            {**DEFAULT_STATE, "task": "demo"},
            config=graph_module.runtime_config(GraphPolicy(max_iterations=4)),
        )

        assert output["verdict"] == BLOCKED
        assert output["plan"] == ""
        assert any("lacks read authority" in e["error"] for e in output["errors"])

    def test_it_escalates_without_spending_the_revision_budget(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """`errors` is an ``operator.add`` accumulator no node clears, so a
        retry can never remove the record that failed the gate; routing to the
        implementer would burn every revision to reach the same terminal."""
        import harness.shared.langgraph.graph as graph_module

        monkeypatch.setattr(graph_module, "planner_node", self._denied)
        graph = graph_module.build_graph()

        output = graph.invoke(
            {**DEFAULT_STATE, "task": "demo"},
            config=graph_module.runtime_config(GraphPolicy(max_iterations=4)),
        )

        assert output["revision_count"] == 1, "the implementer ran more than once on a terminal error"

    def test_an_observation_plane_failure_does_not_block_the_run(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """INV-16: an observation-mode producer's failure is contained and
        leaves the incumbent path unaffected, so the same shape of error from
        ``shadow_planner`` must not decide the verdict."""
        import harness.shared.langgraph.graph as graph_module

        def failing_shadow(state: Any, config=None, **_kwargs: Any) -> dict[str, Any]:
            return {"errors": [error_record("shadow_planner", "model timeout")]}

        mock_orch = MagicMock()
        mock_orch.execute_agent.side_effect = ["plan", "code", "verified"]
        mock_orch._harness_verdict.return_value = Verdict(
            status=VERIFIED, reason="green", termination_reason="", command="pytest", exit_code=0
        )

        monkeypatch.setattr(graph_module, "shadow_planner_node", failing_shadow)
        graph = graph_module.build_graph()

        output = graph.invoke(
            {**DEFAULT_STATE, "task": "demo"},
            config=graph_module.runtime_config(GraphPolicy(), orchestrator=mock_orch),
        )

        assert output["verdict"] == VERIFIED
        assert any(e["node"] == "shadow_planner" for e in output["errors"])


class TestClarifyCycleTerminates:
    """R-LGH-5. ``clarify_node`` writes ``plan_gate: "pass"`` and
    ``plan_gate_node`` recomputes that key from an unchanged
    ``plan_divergence`` on the way back, so the two nodes alternated until
    LangGraph raised ``GraphRecursionError``. Reachable today only through a
    failing shadow planner, whose ``errors``-only return leaves a
    caller-supplied divergence intact; it becomes reachable on the first real
    divergence computation.
    """

    @staticmethod
    def _failing_shadow(state: Any, config=None, **_kwargs: Any) -> dict[str, Any]:
        return {"errors": [error_record("shadow_planner", "model timeout")]}

    def test_unresolved_divergence_blocks_instead_of_recursing(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import harness.shared.langgraph.graph as graph_module

        monkeypatch.setattr(graph_module, "shadow_planner_node", self._failing_shadow)
        graph = graph_module.build_graph()

        output = graph.invoke(
            {**DEFAULT_STATE, "task": "demo", "plan_divergence": 0.9},
            config=graph_module.runtime_config(GraphPolicy(max_iterations=3)),
        )

        assert output["verdict"] == BLOCKED
        assert output["gate_status"][CLARIFY_COUNT] == 3

    def test_the_bound_is_the_policy_not_a_literal(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import harness.shared.langgraph.graph as graph_module

        monkeypatch.setattr(graph_module, "shadow_planner_node", self._failing_shadow)
        graph = graph_module.build_graph()

        output = graph.invoke(
            {**DEFAULT_STATE, "task": "demo", "plan_divergence": 0.9},
            config=graph_module.runtime_config(GraphPolicy(max_iterations=5)),
        )

        assert output["gate_status"][CLARIFY_COUNT] == 5
