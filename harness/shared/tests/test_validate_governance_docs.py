"""Tests for validate_governance_docs: charter, skill freshness, decision records."""

from __future__ import annotations

import datetime as dt
import json
from pathlib import Path

import pytest

from harness.shared import decision_records as dr
from harness.shared.validate_governance_docs import main


def _write_record(
    decisions: Path,
    *,
    dec_id: str = "DEC-001",
    status: str = "accepted",
    date: str = "2026-09-01",
    supersedes: list[str] | None = None,
    owners: list[str] | None = None,
    title: str = "Example decision",
) -> Path:
    supersedes = supersedes or []
    owners = owners or ["governance-maintainers"]
    text = (
        "---\n"
        f"id: {dec_id}\n"
        f'title: "{title}"\n'
        f"status: {status}\n"
        f"date: {date}\n"
        f"supersedes: {json.dumps(supersedes)}\n"
        "superseded_by: null\n"
        f"owners: {json.dumps(owners)}\n"
        "---\n\n"
        f"# {dec_id}: {title}\n\n"
        "## Context\n\nWhy.\n\n"
        "## Decision\n\nWhat.\n\n"
        "## Consequences\n\nEffects.\n"
    )
    path = decisions / f"{dec_id}.md"
    path.write_text(text, encoding="utf-8")
    return path


def _write_indexes(decisions: Path) -> None:
    records = dr.load_all(decisions)
    payload = dr.index_payload(records)
    (decisions / "index.json").write_text(dr.render_index_json(payload), encoding="utf-8")
    (decisions / "index.md").write_text(dr.render_index_md(payload), encoding="utf-8")


def _scaffold_valid(root: Path) -> Path:
    """Build the minimum tree that passes governance-docs validation.

    Returns the decisions directory (under repo-root ``docs/decisions``).
    """
    gov = root / ".governance"
    gov.mkdir(parents=True, exist_ok=True)
    policy = {
        "charter_version": "2.0",
        "governance_skill_path": "agents/GOVERNANCE_SKILL.md",
        "skill_max_age_days": 90,
    }
    (gov / "policy.json").write_text(json.dumps(policy), encoding="utf-8")

    docs = root / "docs"
    docs.mkdir(parents=True, exist_ok=True)
    (docs / "PROJECT-CHARTER.md").write_text("# Charter v2.0\nContent here.", encoding="utf-8")

    decisions = docs / "decisions"
    decisions.mkdir(parents=True, exist_ok=True)
    today = dt.datetime.now(dt.timezone.utc).date().isoformat()
    _write_record(decisions, dec_id="DEC-100", date=today)
    _write_indexes(decisions)
    # Thin node-shaped log path for drift check
    node_gov = root / "harness" / "node" / ".governance"
    node_gov.mkdir(parents=True, exist_ok=True)
    payload = dr.index_payload(dr.load_all(decisions))
    (node_gov / "decision-log.md").write_text(dr.render_thin_decision_log(payload), encoding="utf-8")

    agents = root / "agents"
    agents.mkdir(parents=True, exist_ok=True)
    (agents / "GOVERNANCE_SKILL.md").write_text(
        f"# Governance Skill\nReviewed: {today}\n\n"
        f"## Decisions since {today}\n\n"
        "Source of truth: docs/decisions/ (see index.md).\n",
        encoding="utf-8",
    )
    return decisions


class TestValidateGovernanceDocs:
    """Exercises the governance-docs validator pass and fail paths."""

    def test_valid_structure_passes(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        _scaffold_valid(tmp_path)
        monkeypatch.chdir(tmp_path)
        main(tmp_path)
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
            f"# Governance Skill\nReviewed: {stale_date}\n\n"
            f"## Decisions since {stale_date}\n\nSource of truth: docs/decisions/ index.md\n",
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
            f"# Governance Skill\nReviewed: {future_date}\n\n"
            f"## Decisions since {future_date}\n\nSource of truth: docs/decisions/ index.md\n",
            encoding="utf-8",
        )
        monkeypatch.chdir(tmp_path)
        with pytest.raises(SystemExit) as exc_info:
            main(tmp_path)
        assert "future" in str(exc_info.value).lower()

    def test_missing_decisions_dir_fails(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        _scaffold_valid(tmp_path)
        import shutil

        shutil.rmtree(tmp_path / "docs" / "decisions")
        monkeypatch.chdir(tmp_path)
        with pytest.raises(SystemExit) as exc_info:
            main(tmp_path)
        assert "docs/decisions" in str(exc_info.value).lower()

    def test_decision_without_status_fails(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        decisions = _scaffold_valid(tmp_path)
        path = decisions / "DEC-100.md"
        text = path.read_text(encoding="utf-8")
        path.write_text(text.replace("status: accepted\n", ""), encoding="utf-8")
        monkeypatch.chdir(tmp_path)
        with pytest.raises(SystemExit) as exc_info:
            main(tmp_path)
        assert "status" in str(exc_info.value).lower()

    def test_supersedes_must_be_parseable(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        decisions = _scaffold_valid(tmp_path)
        today = dt.datetime.now(dt.timezone.utc).date().isoformat()
        _write_record(decisions, dec_id="DEC-101", date=today, supersedes=["DEC-100"])
        _write_indexes(decisions)
        payload = dr.index_payload(dr.load_all(decisions))
        (tmp_path / "harness/node/.governance/decision-log.md").write_text(
            dr.render_thin_decision_log(payload), encoding="utf-8"
        )
        monkeypatch.chdir(tmp_path)
        main(tmp_path)  # valid list parses

        bad = decisions / "DEC-101.md"
        bad.write_text(
            bad.read_text(encoding="utf-8").replace('supersedes: ["DEC-100"]', "supersedes: DEC-100"),
            encoding="utf-8",
        )
        with pytest.raises(SystemExit) as exc_info:
            main(tmp_path)
        assert "supersedes" in str(exc_info.value).lower()

    def test_index_drift_fails(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        decisions = _scaffold_valid(tmp_path)
        (decisions / "index.md").write_text("# stale\n", encoding="utf-8")
        monkeypatch.chdir(tmp_path)
        with pytest.raises(SystemExit) as exc_info:
            main(tmp_path)
        assert "drift" in str(exc_info.value).lower()

    def test_skill_restating_decision_text_fails(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        _scaffold_valid(tmp_path)
        today = dt.datetime.now(dt.timezone.utc).date().isoformat()
        long = "x" * 120
        (tmp_path / "agents" / "GOVERNANCE_SKILL.md").write_text(
            f"# Governance Skill\nReviewed: {today}\n\n"
            f"## Decisions since {today}\n\n"
            f"Source of truth: docs/decisions/ index.md\n"
            f"- DEC-100 — {long}\n",
            encoding="utf-8",
        )
        monkeypatch.chdir(tmp_path)
        with pytest.raises(SystemExit) as exc_info:
            main(tmp_path)
        assert "restates" in str(exc_info.value).lower()

    def test_skill_missing_decisions_since_section_fails(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        _scaffold_valid(tmp_path)
        today = dt.datetime.now(dt.timezone.utc).date().isoformat()
        (tmp_path / "agents" / "GOVERNANCE_SKILL.md").write_text(
            f"# Governance Skill\nReviewed: {today}\n\nSome content but no Decisions since header.\n",
            encoding="utf-8",
        )
        monkeypatch.chdir(tmp_path)
        with pytest.raises(SystemExit) as exc_info:
            main(tmp_path)
        assert "decisions since" in str(exc_info.value).lower() or "lacks" in str(exc_info.value).lower()

    def test_migration_completeness_every_legacy_id_present(self) -> None:
        """Every DEC id from the pre-NS-34 pipe log must exist as a record file."""
        from harness.shared.tests._helpers import REPO

        legacy = REPO / "docs" / "decisions" / "index.json"
        assert legacy.is_file(), "docs/decisions/index.json missing"
        payload = json.loads(legacy.read_text(encoding="utf-8"))
        ids = {row["id"] for row in payload["decisions"]}
        expected = {f"DEC-{n:03d}" for n in range(57)}
        assert ids == expected, f"missing {sorted(expected - ids)} extra {sorted(ids - expected)}"
        for dec_id in expected:
            assert (REPO / "docs" / "decisions" / f"{dec_id}.md").is_file()
