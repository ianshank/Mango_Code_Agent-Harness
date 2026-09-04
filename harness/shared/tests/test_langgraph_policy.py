"""Tests for harness/shared/langgraph/policy.py.

Verifies GraphPolicy:
- Loads from governance-policy.json correctly
- Is immutable after construction
- Defaults match existing orchestrator_defaults()
- Fails closed on malformed policy, uses defaults only on an absent file
- Fields introduced by docs/specs/langgraph-policy-wiring.md genuinely flow
  from policy rather than merely coinciding with the dataclass default
"""

from __future__ import annotations

import dataclasses
import json
from pathlib import Path

import pytest

from harness.shared import policy_loader
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

    def test_langgraph_fields_load_from_policy(self) -> None:
        """recursion_limit / max_concurrency / plan_divergence_threshold were
        previously never populated by from_governance_json() at all (the bug
        docs/specs/langgraph-policy-wiring.md fixes) -- assert they now come
        from the live policy's `langgraph` section, not silently stay at the
        dataclass default regardless of what the policy says."""
        policy = GraphPolicy.from_governance_json()
        lg = policy_loader.langgraph_defaults()
        assert policy.recursion_limit == lg["recursion_limit"]
        assert policy.max_concurrency == lg["max_concurrency"]
        assert policy.plan_divergence_threshold == lg["plan_divergence_threshold"]


class TestGraphPolicyFailClosed:
    """R-LPW-1: a malformed policy must raise, not silently degrade to
    defaults. Only a genuinely *absent* policy file is the adopter path."""

    def test_absent_policy_file_uses_builtin_defaults(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """The legitimate adopter path: no policy file at all still compiles
        a GraphPolicy from built-in defaults, unchanged by this fix."""
        monkeypatch.setattr(policy_loader, "POLICY_PATH", tmp_path / "does-not-exist.json")
        policy = GraphPolicy.from_governance_json()
        assert policy.recursion_limit == GraphPolicy().recursion_limit
        assert policy.max_iterations == GraphPolicy().max_iterations

    def test_malformed_policy_raises(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        """A present-but-malformed policy (bad JSON) must raise -- the exact
        bug this spec fixes: a prior version caught this and silently
        returned GraphPolicy() instead."""
        bad_policy = tmp_path / "governance-policy.json"
        bad_policy.write_text("{not valid json", encoding="utf-8")
        monkeypatch.setattr(policy_loader, "POLICY_PATH", bad_policy)
        with pytest.raises(policy_loader.PolicyError):
            GraphPolicy.from_governance_json()

    def test_wrong_typed_langgraph_field_raises(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """A structurally-valid JSON file with the wrong type for a langgraph
        field (a string instead of a number) must also raise -- proving the
        new langgraph_defaults() accessor is genuinely type-validated, not
        just present-vs-absent."""
        bad_policy = tmp_path / "governance-policy.json"
        bad_policy.write_text(
            json.dumps({"langgraph": {"recursion_limit": "not-a-number"}}), encoding="utf-8"
        )
        monkeypatch.setattr(policy_loader, "POLICY_PATH", bad_policy)
        with pytest.raises(policy_loader.PolicyError):
            GraphPolicy.from_governance_json()

    def test_non_object_coverage_section_raises_policy_error_not_attribute_error(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """GitHub Copilot's review of PR #53: a present-but-non-object `coverage`
        section used to reach `coverage.get("lines", ...)` via a raw, unvalidated
        `policy.get("coverage", {})` -- raising AttributeError (not PolicyError),
        contradicting this method's own documented fail-closed contract. Fixed by
        routing through policy_loader.coverage_defaults(), which validates the
        section's shape the same way langgraph_defaults() already does."""
        bad_policy = tmp_path / "governance-policy.json"
        bad_policy.write_text(json.dumps({"coverage": "not-an-object"}), encoding="utf-8")
        monkeypatch.setattr(policy_loader, "POLICY_PATH", bad_policy)
        with pytest.raises(policy_loader.PolicyError):
            GraphPolicy.from_governance_json()

    def test_non_object_agent_defaults_section_raises_policy_error_not_attribute_error(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """Same defect, the other unvalidated section Copilot's review named."""
        bad_policy = tmp_path / "governance-policy.json"
        bad_policy.write_text(json.dumps({"agent_defaults": [1, 2, 3]}), encoding="utf-8")
        monkeypatch.setattr(policy_loader, "POLICY_PATH", bad_policy)
        with pytest.raises(policy_loader.PolicyError):
            GraphPolicy.from_governance_json()

    def test_distinguishable_value_actually_flows_through(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """The core liveness proof: a policy value that does NOT match any
        dataclass default must still be picked up -- ruling out the
        "coincidence, not liveness" failure mode where every prior assertion
        in this file happened to equal the default regardless of wiring."""
        fixture_policy = tmp_path / "governance-policy.json"
        fixture_policy.write_text(
            json.dumps(
                {
                    "langgraph": {
                        "recursion_limit": 999,
                        "max_concurrency": 17,
                        "plan_divergence_threshold": 0.01,
                    },
                    # Complete blocks, not just the keys this test asserts on:
                    # since R-CQ-8 a present policy that omits a key its reader
                    # asks for fails closed, so a partial block would raise
                    # before any value could be shown to flow through. The
                    # unasserted values are still distinguishable from their
                    # built-in defaults, which keeps this a liveness fixture
                    # rather than one that happens to match.
                    "orchestrator": {
                        "max_iterations": 42,
                        "api_timeout_sec": 301,
                        "verification_timeout_sec": 901,
                        "tool_timeout_sec": 31,
                        "max_command_bytes": 8193,
                        "max_healing_retries": 4,
                        "max_output_bytes": 65537,
                    },
                    "coverage": {"lines": 71, "branches": 61},
                    "agent_defaults": {
                        "max_delegation_depth": 9,
                        "max_parallel_subagents": 13,
                        "max_tool_calls_per_task": 101,
                    },
                }
            ),
            encoding="utf-8",
        )
        monkeypatch.setattr(policy_loader, "POLICY_PATH", fixture_policy)
        policy = GraphPolicy.from_governance_json()
        assert policy.recursion_limit == 999
        assert policy.max_concurrency == 17
        assert policy.plan_divergence_threshold == 0.01
        assert policy.max_iterations == 42
        assert policy.coverage_floor_lines == 71
        assert policy.coverage_floor_branches == 61
        assert policy.max_delegation_depth == 9
        assert policy.max_parallel_subagents == 13
