"""Tests for harness/shared/agent_authority.py.

Spec: ``docs/specs/agent-containment.md`` (R-AC-8).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from harness.shared import mango_mas_orchestrator as orch_module
from harness.shared.agent_authority import (
    ACTIVE_TO_CANONICAL,
    DEFAULT_AGENT_POLICY_PATH,
    TOOL_REQUIRED_ACTION,
    allowed_actions,
    load_agent_policy,
    tools_for_role,
)

pytestmark = pytest.mark.governance


def _names(role: str) -> set[str]:
    return {t["function"]["name"] for t in tools_for_role(role, orch_module.NEMOTRON_TOOLS)}


class TestDerivedExposure:
    def test_the_verifier_cannot_write_files(self) -> None:
        """The defect this module exists to close. ``execute_agent`` passed no
        ``tools=`` for the verifier, so it received the implementer schema --
        while ``peer-reviewer.md`` denies "changing the implementation being
        judged" and ``test-eval.md`` denies "product implementation changes"."""
        assert "write_file" not in _names("verifier")

    def test_the_verifier_can_still_run_the_gates(self) -> None:
        """A denial of everything would satisfy the test above and break the loop."""
        assert "run_command" in _names("verifier")

    def test_the_reasoner_keeps_the_implementer_surface(self) -> None:
        assert {"write_file", "run_command"} <= _names("nemotron-reasoner")

    def test_the_planner_holds_no_execution_authority(self) -> None:
        assert not ({"write_file", "run_command"} & _names("planner"))

    def test_an_unknown_role_receives_nothing(self) -> None:
        """Defaulting to the full schema on an unrecognised name is how the
        verifier came to hold ``write_file``."""
        assert _names("some-future-role") == set()
        assert allowed_actions("some-future-role") == frozenset()

    def test_meta_tools_reach_every_active_role(self) -> None:
        for role in ACTIVE_TO_CANONICAL:
            assert {"knowledge_gap_log", "hypothesis_register"} <= _names(role), role


class TestApprovalGatedActionsAreSubtracted:
    def test_release_auditor_authority_does_not_leak_into_the_verifier(self) -> None:
        """``release-auditor`` grants ``external_write`` and ``production_change``
        *and* requires human approval for both. A plain union would hand the
        verifier production authority on the strength of a role whose entire
        purpose is that a human signs first."""
        granted = allowed_actions("verifier")
        assert "external_write" not in granted
        assert "production_change" not in granted

    def test_the_subtraction_is_read_from_policy_not_assumed(self) -> None:
        policy = load_agent_policy()
        auditor = next(r for r in policy["agents"] if r["id"] == "release-auditor")
        assert set(auditor["human_approval_required_for"]) == {"external_write", "production_change"}


class TestMappingsStayHonest:
    def test_every_declared_tool_has_a_required_action(self) -> None:
        """Set equality in both directions, mirroring
        ``TestToolRegistry::test_every_declared_tool_has_a_handler``: a tool added
        to the registry without an action would otherwise be silently withheld
        from every role, and a stale entry here would outlive its tool."""
        # Annotated for the same reason test_mango_mas_orchestrator.py does it:
        # mypy narrows the literal schema list to Collection[str] values.
        tools: list[dict[str, Any]] = orch_module.NEMOTRON_TOOLS
        declared = {t["function"]["name"] for t in tools}
        assert declared == set(TOOL_REQUIRED_ACTION), (
            f"unmapped tools: {declared - set(TOOL_REQUIRED_ACTION)}; "
            f"stale mappings: {set(TOOL_REQUIRED_ACTION) - declared}"
        )

    def test_active_roles_match_the_executed_loop(self) -> None:
        assert set(ACTIVE_TO_CANONICAL) == {"planner", "nemotron-reasoner", "verifier"}

    def test_every_canonical_role_named_here_exists_in_the_policy(self) -> None:
        declared = {r["id"] for r in load_agent_policy()["agents"]}
        for active, canonical in ACTIVE_TO_CANONICAL.items():
            assert set(canonical) <= declared, f"{active} maps to roles absent from agent-policy.json"

    def test_an_unmapped_tool_is_withheld_rather_than_granted(self) -> None:
        invented = [{"type": "function", "function": {"name": "launch_missiles"}}]
        assert tools_for_role("nemotron-reasoner", invented) == []


class TestPolicyLoading:
    def test_default_policy_travels_with_the_installed_harness(self) -> None:
        assert DEFAULT_AGENT_POLICY_PATH.is_file()

    def test_a_non_object_policy_is_rejected(self, tmp_path: Path) -> None:
        bad = tmp_path / "agent-policy.json"
        bad.write_text("[]", encoding="utf-8")
        with pytest.raises(ValueError, match="not a JSON object"):
            load_agent_policy(bad)

    def test_a_role_absent_from_the_policy_contributes_nothing(self, tmp_path: Path) -> None:
        thin = tmp_path / "agent-policy.json"
        thin.write_text(json.dumps({"agents": [{"id": "implementer", "allowed_actions": ["read"]}]}), encoding="utf-8")
        assert allowed_actions("verifier", policy_path=thin) == frozenset()
        assert allowed_actions("nemotron-reasoner", policy_path=thin) == frozenset({"read"})

    def test_malformed_agent_entries_are_skipped_not_crashed_on(self, tmp_path: Path) -> None:
        odd = tmp_path / "agent-policy.json"
        odd.write_text(
            json.dumps({"agents": ["not-a-dict", {"no_id": True}, {"id": "implementer", "allowed_actions": ["write"]}]}),
            encoding="utf-8",
        )
        assert allowed_actions("nemotron-reasoner", policy_path=odd) == frozenset({"write"})
