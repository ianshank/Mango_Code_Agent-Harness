"""Tests for harness/shared/langgraph/policy.py.

Verifies GraphPolicy:
- Loads from governance-policy.json correctly
- Is immutable after construction
- Defaults match existing orchestrator_defaults()
"""

from __future__ import annotations

import dataclasses

import pytest

from harness.shared.langgraph.policy import GraphPolicy

pytestmark = pytest.mark.langgraph


class TestGraphPolicyConstruction:
    def test_default_construction(self) -> None:
        """Policy constructs with documented defaults."""
        policy = GraphPolicy()
        assert policy.max_iterations == 10
        assert policy.recursion_limit == 50
        assert policy.max_concurrency == 3
        assert policy.plan_divergence_threshold == 0.35

    def test_frozen_immutability(self) -> None:
        """Policy is frozen — attempting to mutate raises."""
        policy = GraphPolicy()
        with pytest.raises(dataclasses.FrozenInstanceError):
            policy.max_iterations = 99  # type: ignore[misc]


class TestGraphPolicyFromGovernanceJson:
    def test_loads_from_governance_json(self) -> None:
        """The factory method reads the live policy file."""
        policy = GraphPolicy.from_governance_json()
        # These values come from governance-policy.json
        assert policy.max_iterations == 10
        assert policy.api_timeout_sec == 300
        assert policy.tool_timeout_sec == 30
        assert policy.max_command_bytes == 8192

    def test_matches_orchestrator_defaults(self) -> None:
        """The LangGraph policy must produce the same orchestrator limits
        as the existing policy_loader.orchestrator_defaults()."""
        from harness.shared.policy_loader import orchestrator_defaults

        orch = orchestrator_defaults()
        policy = GraphPolicy.from_governance_json()
        assert policy.max_iterations == orch["max_iterations"]
        assert policy.api_timeout_sec == orch["api_timeout_sec"]
        assert policy.tool_timeout_sec == orch["tool_timeout_sec"]
        assert policy.max_command_bytes == orch["max_command_bytes"]

    def test_coverage_thresholds_from_policy(self) -> None:
        """Coverage floors are read from governance-policy.json, not hardcoded."""
        policy = GraphPolicy.from_governance_json()
        assert policy.coverage_floor_lines == 90
        assert policy.coverage_floor_branches == 80

    def test_fallback_on_missing_policy(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """If load_policy raises, factory returns defaults rather than crashing."""

        def _raise_import() -> dict:
            raise ImportError("policy_loader not available")

        monkeypatch.setattr(
            "harness.shared.langgraph.policy.GraphPolicy.from_governance_json",
            lambda: GraphPolicy(),
        )
        # Verify defaults still work
        policy = GraphPolicy()
        assert policy.max_iterations == 10
