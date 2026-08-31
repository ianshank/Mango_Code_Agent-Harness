"""Tests for validate_agent_policy: agent policy schema validation."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from harness.shared.validate_agent_policy import main


def _scaffold_valid_policy(root: Path) -> Path:
    """Write a minimal valid agent-policy.json and return its path."""
    gov = root / ".governance"
    gov.mkdir(parents=True, exist_ok=True)
    policy_path = gov / "agent-policy.json"
    policy = {
        "default_deny": True,
        "high_risk_actions": ["destructive", "external_write"],
        "limits": {"max_delegation_depth": 2},
        "agents": [
            {
                "id": role,
                "delegation_depth": 1,
                "allowed_actions": ["read", "write", "destructive", "external_write"],
                "human_approval_required_for": ["destructive", "external_write"],
            }
            for role in [
                "orchestrator", "spec-analyst", "implementer",
                "test-eval", "security-reviewer", "peer-reviewer", "release-auditor",
            ]
        ],
        "rules": {
            "self_modify_policy": False,
            "secrets_may_not_be_propagated_to_subagents": True,
            "delegation_does_not_transfer_authority": True,
            "every_side_effect_requires_trace_id": True,
        },
    }
    policy_path.write_text(json.dumps(policy), encoding="utf-8")
    return policy_path


class TestValidateAgentPolicy:
    """Exercises the agent-policy validator's pass and fail paths."""

    def test_valid_policy_passes(self, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
        path = _scaffold_valid_policy(tmp_path)
        main(path)  # no SystemExit
        assert "passed" in capsys.readouterr().out

    def test_missing_role_fails(self, tmp_path: Path) -> None:
        path = _scaffold_valid_policy(tmp_path)
        data = json.loads(path.read_text())
        data["agents"] = [a for a in data["agents"] if a["id"] != "orchestrator"]
        path.write_text(json.dumps(data), encoding="utf-8")
        with pytest.raises(SystemExit) as exc_info:
            main(path)
        assert "orchestrator" in str(exc_info.value)

    def test_default_deny_false_fails(self, tmp_path: Path) -> None:
        path = _scaffold_valid_policy(tmp_path)
        data = json.loads(path.read_text())
        data["default_deny"] = False
        path.write_text(json.dumps(data), encoding="utf-8")
        with pytest.raises(SystemExit) as exc_info:
            main(path)
        assert "default_deny" in str(exc_info.value)

    def test_empty_high_risk_fails(self, tmp_path: Path) -> None:
        path = _scaffold_valid_policy(tmp_path)
        data = json.loads(path.read_text())
        data["high_risk_actions"] = []
        path.write_text(json.dumps(data), encoding="utf-8")
        with pytest.raises(SystemExit):
            main(path)

    def test_delegation_depth_exceeded_fails(self, tmp_path: Path) -> None:
        path = _scaffold_valid_policy(tmp_path)
        data = json.loads(path.read_text())
        data["agents"][0]["delegation_depth"] = 99
        path.write_text(json.dumps(data), encoding="utf-8")
        with pytest.raises(SystemExit) as exc_info:
            main(path)
        assert "delegation depth" in str(exc_info.value)

    def test_missing_allowed_actions_fails(self, tmp_path: Path) -> None:
        path = _scaffold_valid_policy(tmp_path)
        data = json.loads(path.read_text())
        del data["agents"][0]["allowed_actions"]
        path.write_text(json.dumps(data), encoding="utf-8")
        with pytest.raises(SystemExit) as exc_info:
            main(path)
        assert "allowed_actions" in str(exc_info.value)

    def test_self_modify_policy_true_fails(self, tmp_path: Path) -> None:
        path = _scaffold_valid_policy(tmp_path)
        data = json.loads(path.read_text())
        data["rules"]["self_modify_policy"] = True
        path.write_text(json.dumps(data), encoding="utf-8")
        with pytest.raises(SystemExit) as exc_info:
            main(path)
        assert "self-modify" in str(exc_info.value)

    def test_unapproved_high_risk_action_fails(self, tmp_path: Path) -> None:
        path = _scaffold_valid_policy(tmp_path)
        data = json.loads(path.read_text())
        # Remove "destructive" from human_approval_required_for but keep it in allowed_actions
        data["agents"][0]["human_approval_required_for"] = ["external_write"]
        path.write_text(json.dumps(data), encoding="utf-8")
        with pytest.raises(SystemExit) as exc_info:
            main(path)
        assert "high-risk" in str(exc_info.value).lower() or "approval" in str(exc_info.value).lower()

    def test_approval_not_subset_of_allowed_fails(self, tmp_path: Path) -> None:
        """Cover line 45: approval action that is not in allowed_actions."""
        path = _scaffold_valid_policy(tmp_path)
        data = json.loads(path.read_text())
        # Add an approval action that is NOT in allowed_actions
        data["agents"][0]["human_approval_required_for"] = ["destructive", "external_write", "not_allowed"]
        path.write_text(json.dumps(data), encoding="utf-8")
        with pytest.raises(SystemExit) as exc_info:
            main(path)
        assert "approval action is not allowed" in str(exc_info.value)

    def test_delegation_does_not_transfer_false_fails(self, tmp_path: Path) -> None:
        """Cover line 64: delegation_does_not_transfer_authority set to False."""
        path = _scaffold_valid_policy(tmp_path)
        data = json.loads(path.read_text())
        data["rules"]["delegation_does_not_transfer_authority"] = False
        path.write_text(json.dumps(data), encoding="utf-8")
        with pytest.raises(SystemExit) as exc_info:
            main(path)
        assert "delegation" in str(exc_info.value)

    def test_side_effects_require_trace_id_false_fails(self, tmp_path: Path) -> None:
        """Cover line 66: every_side_effect_requires_trace_id set to False."""
        path = _scaffold_valid_policy(tmp_path)
        data = json.loads(path.read_text())
        data["rules"]["every_side_effect_requires_trace_id"] = False
        path.write_text(json.dumps(data), encoding="utf-8")
        with pytest.raises(SystemExit) as exc_info:
            main(path)
        assert "trace" in str(exc_info.value)
