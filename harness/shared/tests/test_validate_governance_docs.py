"""Tests for validate_governance_docs: charter version, governance skill freshness, decision log."""
from __future__ import annotations

import datetime as dt
import json
from pathlib import Path

import pytest

from harness.shared.validate_governance_docs import main


def _scaffold_valid(root: Path) -> None:
    """Build the minimum tree that passes governance-docs validation."""
    gov = root / ".governance"
    gov.mkdir(parents=True, exist_ok=True)

    # Policy
    policy = {
        "charter_version": "2.0",
        "governance_skill_path": "agents/GOVERNANCE_SKILL.md",
        "skill_max_age_days": 90,
    }
    (gov / "policy.json").write_text(json.dumps(policy), encoding="utf-8")

    # Charter
    docs = root / "docs"
    docs.mkdir(parents=True, exist_ok=True)
    (docs / "PROJECT-CHARTER.md").write_text("# Charter v2.0\nContent here.", encoding="utf-8")

    # Governance skill
    agents = root / "agents"
    agents.mkdir(parents=True, exist_ok=True)
    today = dt.datetime.now(dt.timezone.utc).date().isoformat()
    (agents / "GOVERNANCE_SKILL.md").write_text(
        f"# Governance Skill\nReviewed: {today}\n\n## Decisions since {today}\n",
        encoding="utf-8",
    )

    # Decision log (empty but present)
    (gov / "decision-log.md").write_text("# Decision Log\n", encoding="utf-8")


class TestValidateGovernanceDocs:
    """Exercises the governance-docs validator pass and fail paths."""

    def test_valid_structure_passes(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
    ) -> None:
        _scaffold_valid(tmp_path)
        monkeypatch.chdir(tmp_path)
        main(tmp_path)  # no SystemExit
        assert "passed" in capsys.readouterr().out

    def test_missing_charter_version_fails(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        _scaffold_valid(tmp_path)
        policy = json.loads((tmp_path / ".governance" / "policy.json").read_text())
        policy["charter_version"] = ""
        (tmp_path / ".governance" / "policy.json").write_text(json.dumps(policy), encoding="utf-8")
        monkeypatch.chdir(tmp_path)
        with pytest.raises(SystemExit) as exc_info:
            main(tmp_path)
        assert "charter_version" in str(exc_info.value)

    def test_charter_file_missing_fails(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        _scaffold_valid(tmp_path)
        (tmp_path / "docs" / "PROJECT-CHARTER.md").unlink()
        monkeypatch.chdir(tmp_path)
        with pytest.raises(SystemExit) as exc_info:
            main(tmp_path)
        assert "charter" in str(exc_info.value).lower()

    def test_governance_skill_missing_fails(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        _scaffold_valid(tmp_path)
        (tmp_path / "agents" / "GOVERNANCE_SKILL.md").unlink()
        monkeypatch.chdir(tmp_path)
        with pytest.raises(SystemExit) as exc_info:
            main(tmp_path)
        assert "governance skill missing" in str(exc_info.value).lower()

    def test_stale_review_date_fails(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        _scaffold_valid(tmp_path)
        stale_date = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=200)).date().isoformat()
        skill = tmp_path / "agents" / "GOVERNANCE_SKILL.md"
        skill.write_text(
            f"# Governance Skill\nReviewed: {stale_date}\n\n## Decisions since {stale_date}\n",
            encoding="utf-8",
        )
        monkeypatch.chdir(tmp_path)
        with pytest.raises(SystemExit) as exc_info:
            main(tmp_path)
        assert "stale" in str(exc_info.value).lower()

    def test_future_review_date_fails(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        _scaffold_valid(tmp_path)
        future_date = (dt.datetime.now(dt.timezone.utc) + dt.timedelta(days=10)).date().isoformat()
        skill = tmp_path / "agents" / "GOVERNANCE_SKILL.md"
        skill.write_text(
            f"# Governance Skill\nReviewed: {future_date}\n\n## Decisions since {future_date}\n",
            encoding="utf-8",
        )
        monkeypatch.chdir(tmp_path)
        with pytest.raises(SystemExit) as exc_info:
            main(tmp_path)
        assert "future" in str(exc_info.value).lower()

    def test_missing_decision_log_fails(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        _scaffold_valid(tmp_path)
        (tmp_path / ".governance" / "decision-log.md").unlink()
        monkeypatch.chdir(tmp_path)
        with pytest.raises(SystemExit) as exc_info:
            main(tmp_path)
        assert "decision log" in str(exc_info.value).lower()
