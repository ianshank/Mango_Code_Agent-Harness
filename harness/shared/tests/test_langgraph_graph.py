"""Tests for harness/shared/langgraph/graph.py.

Verifies:
- Graph compiles successfully
- Correct number of nodes
- Edge topology matches the architecture diagram
- Routing functions work correctly across all branches
"""

from __future__ import annotations

import inspect
import warnings
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from harness.shared.langgraph import LANGGRAPH_AVAILABLE
from harness.shared.langgraph.graph import (
    EXPECTED_NODE_COUNT,
    _route_plan_gate,
    _route_quality_gate,
    build_graph,
    runtime_config,
)
from harness.shared.langgraph.nodes import (
    CLARIFY_COUNT,
    QUALITY_GATE_REASON,
    REASON_ERROR,
    REASON_INCONCLUSIVE,
    evaluation_node,
    implementer_node,
    plan_gate_node,
    planner_node,
    shadow_planner_node,
)
from harness.shared.langgraph.policy import GraphPolicy

pytestmark = pytest.mark.langgraph

#: Every routing function and node that reads ``config``. A node absent from
#: this list is not covered by ``TestConfigInjectionContract``, so it is kept
#: beside the graph rather than derived from it: adding a config-reading node
#: means adding it here.
CONFIG_TAKING_CALLABLES = [
    _route_plan_gate,
    _route_quality_gate,
    planner_node,
    shadow_planner_node,
    implementer_node,
    evaluation_node,
    plan_gate_node,
]


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
        result = _route_quality_gate(
            {
                "gate_status": {"quality_gate": "fail"},
                "revision_count": 2,
            }
        )
        assert result == "implementer"

    def test_quality_gate_routes_to_escalate_on_exhausted(self) -> None:
        result = _route_quality_gate(
            {
                "gate_status": {"quality_gate": "fail"},
                "revision_count": 15,
            }
        )
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
        state = {"gate_status": {"quality_gate": "fail"}, "revision_count": 2}
        assert _route_quality_gate(state, config={"configurable": {"policy": custom_policy}}) == "escalate"

    def test_custom_lower_cap_still_retries_below_its_own_threshold(self) -> None:
        custom_policy = GraphPolicy(max_iterations=2)
        state = {"gate_status": {"quality_gate": "fail"}, "revision_count": 1}
        assert _route_quality_gate(state, config={"configurable": {"policy": custom_policy}}) == "implementer"

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


class TestPlanGateRoutingTerminates:
    """docs/specs/langgraph-fail-open-hardening.md R-LGH-5.

    ``clarify_node`` writes ``plan_gate: "pass"`` and ``plan_gate_node``
    recomputes that key from an unchanged ``plan_divergence`` on the way back,
    so the cycle had no fixpoint and no third exit.
    """

    def test_routes_to_clarify_below_the_bound(self) -> None:
        state = {"gate_status": {"plan_gate": "fail", CLARIFY_COUNT: 1}}
        config = runtime_config(GraphPolicy(max_iterations=3))
        assert _route_plan_gate(state, config=config) == "clarify"

    def test_escalates_at_the_bound(self) -> None:
        state = {"gate_status": {"plan_gate": "fail", CLARIFY_COUNT: 3}}
        config = runtime_config(GraphPolicy(max_iterations=3))
        assert _route_plan_gate(state, config=config) == "escalate"

    def test_bound_comes_from_policy_not_a_literal(self) -> None:
        """A count of 3 clarifies under the default cap (10) and escalates under
        a cap of 3, so the policy — not a constant — decided it."""
        state = {"gate_status": {"plan_gate": "fail", CLARIFY_COUNT: 3}}
        assert _route_plan_gate(state) == "clarify"
        assert _route_plan_gate(state, config=runtime_config(GraphPolicy(max_iterations=3))) == "escalate"

    def test_a_passing_gate_still_reaches_the_implementer(self) -> None:
        state = {"gate_status": {"plan_gate": "pass", CLARIFY_COUNT: 99}}
        assert _route_plan_gate(state) == "implementer"


class TestQualityGateRoutingOnBlockingError:
    """R-LGH-3: a blocking error is terminal, not retryable."""

    def test_error_reason_escalates_without_spending_revisions(self) -> None:
        state = {
            "gate_status": {"quality_gate": "fail", QUALITY_GATE_REASON: REASON_ERROR},
            "revision_count": 0,
        }
        assert _route_quality_gate(state) == "escalate"

    def test_a_failing_suite_still_retries(self) -> None:
        """The reason matters: a failing suite is the *only* retryable one,
        because the implementer is handed the failure message and can act on
        it."""
        state = {
            "gate_status": {"quality_gate": "fail", QUALITY_GATE_REASON: "tests_failed"},
            "revision_count": 0,
        }
        assert _route_quality_gate(state) == "implementer"

    def test_inconclusive_is_terminal_too(self) -> None:
        """R-LGH-8. The first version treated only ``error`` as terminal, so an
        inconclusive result fell through to the revision loop — and nothing
        inside the loop can supply the evidence it lacks, so every retry ran the
        write-capable implementer to produce another `passed=0, failed=0` row.
        Found by review on PR #87."""
        state = {
            "gate_status": {"quality_gate": "fail", QUALITY_GATE_REASON: REASON_INCONCLUSIVE},
            "revision_count": 0,
        }
        assert _route_quality_gate(state) == "escalate"

    def test_an_unrecognised_reason_is_terminal(self) -> None:
        """The set is stated as *retryable*, so a reason added later is terminal
        until someone argues otherwise — which is the failure mode above,
        inverted."""
        state = {
            "gate_status": {"quality_gate": "fail", QUALITY_GATE_REASON: "some_future_reason"},
            "revision_count": 0,
        }
        assert _route_quality_gate(state) == "escalate"


class TestRuntimeConfig:
    """R-LGH-4: the producer for the ``configurable.policy`` key that R-LPW-4
    and R-LPW-5 read and that no caller had ever written."""

    def test_carries_policy_recursion_limit_and_concurrency(self) -> None:
        policy = GraphPolicy(max_iterations=2, recursion_limit=7, max_concurrency=5)
        config = runtime_config(policy)
        assert config["configurable"]["policy"] is policy
        assert config["recursion_limit"] == 7
        assert config["max_concurrency"] == 5

    def test_passes_through_other_configurable_keys(self) -> None:
        sentinel = object()
        config = runtime_config(GraphPolicy(), orchestrator=sentinel)
        assert config["configurable"]["orchestrator"] is sentinel

    def test_defaults_to_the_governance_policy(self) -> None:
        sentinel = GraphPolicy(recursion_limit=777)
        with patch(
            "harness.shared.langgraph.graph.GraphPolicy.from_governance_json",
            return_value=sentinel,
        ) as loader:
            config = runtime_config()
        loader.assert_called_once()
        assert config["recursion_limit"] == 777

    def test_the_config_it_builds_actually_decides_routing(self) -> None:
        """A revision count of 2 retries under the dataclass default (10) and
        escalates under the config this builds, so the threading is live rather
        than merely present in a dict."""
        state = {"gate_status": {"quality_gate": "fail"}, "revision_count": 2}
        assert _route_quality_gate(state) == "implementer"
        config = runtime_config(GraphPolicy(max_iterations=2))
        assert _route_quality_gate(state, config=config) == "escalate"


class TestConfigInjectionContract:
    """LangGraph injects ``config`` only for an accepted annotation spelling.

    ``KWARGS_CONFIG_KEYS`` in ``langgraph._internal._runnable`` accepts
    ``RunnableConfig``, ``Optional[RunnableConfig]`` or *no annotation*, and
    skips anything else with a ``UserWarning`` — so ``config: Any``, which both
    routers carried, meant the parameter never arrived and R-LPW-4's policy
    wiring did nothing through a compiled graph. Its unit tests called the
    routers directly and could not see it. This pins the spelling; the live
    classes below pin the behaviour.
    """

    ACCEPTED = frozenset({"RunnableConfig", "Optional[RunnableConfig]", inspect.Parameter.empty})

    @pytest.mark.parametrize("fn", CONFIG_TAKING_CALLABLES, ids=lambda fn: fn.__name__)
    def test_config_parameter_uses_an_injectable_annotation(self, fn: Any) -> None:
        param = inspect.signature(fn).parameters.get("config")
        assert param is not None, f"{fn.__name__} takes no config parameter"
        assert param.annotation in self.ACCEPTED, (
            f"{fn.__name__} annotates config as {param.annotation!r}; LangGraph will "
            "not inject it, and the function will silently never see the "
            "orchestrator or the policy"
        )

    @pytest.mark.skipif(not LANGGRAPH_AVAILABLE, reason="langgraph not installed (DEC-026)")
    def test_building_the_graph_emits_no_injection_warning(self) -> None:
        """The ``UserWarning`` is LangGraph's only signal, and it is raised when
        the graph is *built* rather than when the module is imported — which is
        why the remediation plan's AC-27 import-under-``-W error`` check cannot
        see it."""
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always", UserWarning)
            build_graph()
        skipped = [str(w.message) for w in caught if "config" in str(w.message)]
        assert not skipped, f"LangGraph refused to inject config somewhere: {skipped}"


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


@pytest.mark.skipif(not LANGGRAPH_AVAILABLE, reason="langgraph not installed (DEC-026)")
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

    def test_stub_path_produces_a_blocked_verdict_live(self) -> None:
        """R-LGH-2. The assertion this replaces was
        ``verdict in ("VERIFIED", "FAILED", "BLOCKED", "")`` — the whole domain
        of the channel, which no implementation could fail. With no
        orchestrator, ``evaluation_node`` reports ``passed=0, failed=0``; that
        is an absence of evidence, and it now ends ``BLOCKED`` rather than
        claiming ``VERIFIED`` over a suite that never ran.
        """
        from harness.shared.langgraph.state import DEFAULT_STATE

        graph = build_graph()
        result = graph.invoke(
            {**DEFAULT_STATE, "task": "test task"},
            config=runtime_config(GraphPolicy(max_iterations=2)),
        )
        assert result["verdict"] == "BLOCKED"
        assert result["gate_status"][QUALITY_GATE_REASON] == "inconclusive"
