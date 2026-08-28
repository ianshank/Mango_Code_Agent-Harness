"""Tests for harness/shared/governance/policy_decision.py.

Spec: ``docs/specs/agent-containment.md`` (R-AC-11).
"""

from __future__ import annotations

import json
import subprocess
import sys

import pytest

from harness.shared.governance.policy_decision import ALLOW, DENY, decide
from harness.shared.tests._helpers import REPO

pytestmark = pytest.mark.governance

POLICY = json.loads((REPO / "harness" / "shared" / "agent-policy.json").read_text(encoding="utf-8"))
REFERENCE_PDP = REPO / "harness" / "control-plane" / "tool_broker_reference.py"
AGENT_POLICY = REPO / "harness" / "shared" / "agent-policy.json"


def _reference_verdict(agent: str, action: str, human_approved: bool = False) -> str:
    argv = [sys.executable, str(REFERENCE_PDP), "--policy", str(AGENT_POLICY), "--agent", agent, "--action", action]
    if human_approved:
        argv.append("--human-approved")
    return ALLOW if subprocess.run(argv, capture_output=True, text=True).returncode == 0 else DENY


class TestAgreesWithTheReferenceImplementation:
    """The reference PDP stays as the contract an external broker mirrors. If the
    in-process evaluation drifted from it, the local fast control and the
    authoritative one would disagree about the same request."""

    @pytest.mark.parametrize(
        ("agent", "action"),
        [
            ("implementer", "write"),
            ("implementer", "destructive"),
            ("implementer", "test_execute"),
            ("peer-reviewer", "write"),
            ("peer-reviewer", "read"),
            ("release-auditor", "external_write"),
            ("release-auditor", "read"),
            ("nobody", "read"),
            ("orchestrator", "delegate"),
        ],
    )
    def test_same_verdict(self, agent: str, action: str) -> None:
        assert decide(agent, action, POLICY).verdict == _reference_verdict(agent, action)

    def test_same_verdict_with_human_approval(self) -> None:
        got = decide("release-auditor", "external_write", POLICY, human_approved=True).verdict
        assert got == _reference_verdict("release-auditor", "external_write", human_approved=True)


class TestDenialsAreOrdered:
    def test_unknown_identity_is_reported_before_the_action(self) -> None:
        assert "unknown agent identity" in decide("nobody", "read", POLICY).reason

    def test_an_ungranted_action_says_so(self) -> None:
        assert "not granted" in decide("peer-reviewer", "write", POLICY).reason

    def test_approval_gating_is_distinguished_from_a_plain_denial(self) -> None:
        """An operator needs to tell "you may not" from "not yet"."""
        assert "human approval" in decide("release-auditor", "production_change", POLICY).reason


class TestMalformedPolicies:
    def test_no_agents_key_denies(self) -> None:
        assert decide("implementer", "read", {}).verdict == DENY

    def test_agents_of_the_wrong_type_denies(self) -> None:
        assert decide("implementer", "read", {"agents": "not-a-list"}).verdict == DENY

    def test_malformed_entries_are_skipped(self) -> None:
        policy = {"agents": ["nope", {"no_id": 1}, {"id": "implementer", "allowed_actions": ["read"]}]}
        assert decide("implementer", "read", policy).verdict == ALLOW

    def test_a_role_without_allowed_actions_grants_nothing(self) -> None:
        assert decide("implementer", "read", {"agents": [{"id": "implementer"}]}).verdict == DENY


def test_allowed_property_matches_the_verdict() -> None:
    assert decide("implementer", "read", POLICY).allowed is True
    assert decide("implementer", "destructive", POLICY).allowed is False
