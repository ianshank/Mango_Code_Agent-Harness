"""Tests for validate_policy: governance policy schema and invariant validation."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from harness.shared.validate_policy import main


def _scaffold_valid_policy(root: Path) -> Path:
    """Write a minimal valid governance policy and return its path."""
    gov = root / ".governance"
    gov.mkdir(parents=True, exist_ok=True)
    policy_path = gov / "policy.json"
    policy = {
        "target_contract": ["install", "lint", "test", "cov"],
        "pre_pr_order": ["lint", "cov"],
        "ci_required_targets": [
            "cov", "lint", "types", "secrets", "specs",
            "audit", "remotes", "projections", "traceability", "governance",
        ],
        "decision_id_pattern": "^(DEC-[0-9]+)$",
        "agent_defaults": {"deny_unclassified_side_effects": True},
        "protected_paths": [
            ".governance/**", ".github/workflows/**",
            "Makefile", "scripts/remotes.py", "scripts/verify_zero_skips.py",
        ],
        "charter_version": "2.0",
        "governance_skill_path": "agents/GOVERNANCE_SKILL.md",
        "skill_max_age_days": 90,
        "external_root_of_trust_required": True,
    }
    policy_path.write_text(json.dumps(policy), encoding="utf-8")
    return policy_path


class TestValidatePolicy:
    """Exercises the governance policy validator."""

    def test_valid_policy_passes(self, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
        path = _scaffold_valid_policy(tmp_path)
        main(path)  # no SystemExit
        assert "passed" in capsys.readouterr().out

    @pytest.mark.parametrize("missing_key", [
        "target_contract", "pre_pr_order", "ci_required_targets",
        "decision_id_pattern", "agent_defaults", "protected_paths",
        "charter_version", "governance_skill_path", "skill_max_age_days",
    ])
    def test_missing_required_key_fails(self, tmp_path: Path, missing_key: str) -> None:
        path = _scaffold_valid_policy(tmp_path)
        data = json.loads(path.read_text())
        del data[missing_key]
        path.write_text(json.dumps(data), encoding="utf-8")
        with pytest.raises(SystemExit) as exc_info:
            main(path)
        assert missing_key in str(exc_info.value)

    def test_missing_ci_gate_fails(self, tmp_path: Path) -> None:
        path = _scaffold_valid_policy(tmp_path)
        data = json.loads(path.read_text())
        data["ci_required_targets"] = ["cov", "lint"]
        path.write_text(json.dumps(data), encoding="utf-8")
        with pytest.raises(SystemExit) as exc_info:
            main(path)
        assert "critical CI gates" in str(exc_info.value)

    def test_missing_protected_path_fails(self, tmp_path: Path) -> None:
        path = _scaffold_valid_policy(tmp_path)
        data = json.loads(path.read_text())
        data["protected_paths"] = [".governance/**"]
        path.write_text(json.dumps(data), encoding="utf-8")
        with pytest.raises(SystemExit) as exc_info:
            main(path)
        assert "critical protected path" in str(exc_info.value)

    def test_external_rot_required_false_fails(self, tmp_path: Path) -> None:
        path = _scaffold_valid_policy(tmp_path)
        data = json.loads(path.read_text())
        data["external_root_of_trust_required"] = False
        path.write_text(json.dumps(data), encoding="utf-8")
        with pytest.raises(SystemExit):
            main(path)

    def test_deny_unclassified_false_fails(self, tmp_path: Path) -> None:
        path = _scaffold_valid_policy(tmp_path)
        data = json.loads(path.read_text())
        data["agent_defaults"]["deny_unclassified_side_effects"] = False
        path.write_text(json.dumps(data), encoding="utf-8")
        with pytest.raises(SystemExit):
            main(path)

    def test_missing_key_raises_systemexit_with_key_name(self, tmp_path: Path) -> None:
        """Cover line 28: missing top-level key triggers SystemExit with key name in message."""
        path = _scaffold_valid_policy(tmp_path)
        data = json.loads(path.read_text())
        del data["charter_version"]
        path.write_text(json.dumps(data), encoding="utf-8")
        with pytest.raises(SystemExit) as exc_info:
            main(path)
        assert "charter_version" in str(exc_info.value)

    def test_missing_github_workflows_protected_path_fails(self, tmp_path: Path) -> None:
        """Cover line 55: individual critical protected-path entries checked one-by-one."""
        path = _scaffold_valid_policy(tmp_path)
        data = json.loads(path.read_text())
        # Remove only .github/workflows/** so the loop hits line 55 on that specific entry
        data["protected_paths"] = [p for p in data["protected_paths"] if p != ".github/workflows/**"]
        path.write_text(json.dumps(data), encoding="utf-8")
        with pytest.raises(SystemExit) as exc_info:
            main(path)
        assert ".github/workflows/**" in str(exc_info.value)

    def test_missing_makefile_protected_path_fails(self, tmp_path: Path) -> None:
        """Cover line 55: Makefile entry individually checked."""
        path = _scaffold_valid_policy(tmp_path)
        data = json.loads(path.read_text())
        data["protected_paths"] = [p for p in data["protected_paths"] if p != "Makefile"]
        path.write_text(json.dumps(data), encoding="utf-8")
        with pytest.raises(SystemExit) as exc_info:
            main(path)
        assert "Makefile" in str(exc_info.value)
