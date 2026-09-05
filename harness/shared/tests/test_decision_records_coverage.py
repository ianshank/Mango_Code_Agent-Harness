"""Coverage for decision_records helpers and generate_decision_index CLI."""

from __future__ import annotations

import json
import runpy
import sys
from pathlib import Path

import pytest

from harness.shared import decision_records as dr
from harness.shared import generate_decision_index as gdi
from harness.shared.tests._helpers import seed_minimal_decision_records, utc_today
from harness.shared.validate_governance_docs import main as validate_governance_docs


class TestDecisionRecordsHelpers:
    def test_find_decisions_dir_none(self, tmp_path: Path) -> None:
        assert dr.find_decisions_dir(tmp_path) is None

    def test_parse_scalar_variants(self) -> None:
        assert dr._parse_scalar("true") is True
        assert dr._parse_scalar("false") is False
        assert dr._parse_scalar("null") is None
        assert dr._parse_scalar("[]") == []
        assert dr._parse_scalar("[DEC-1, DEC-2]") == ["DEC-1", "DEC-2"]
        assert dr._parse_scalar('"hello"') == "hello"
        assert dr._parse_scalar("'quoted'") == "quoted"
        # Broken JSON double-quoted scalar falls back to stripping quotes.
        assert dr._parse_scalar('"\\q"') == "\\q"

    def test_parse_frontmatter_errors(self) -> None:
        with pytest.raises(ValueError, match="opening"):
            dr.parse_frontmatter("no fence\n")
        with pytest.raises(ValueError, match="closing"):
            dr.parse_frontmatter("---\nid: DEC-1\n")
        with pytest.raises(ValueError, match="missing ':'"):
            dr.parse_frontmatter("---\nbadline\n---\n")

    def test_validate_record_fail_paths(self, tmp_path: Path) -> None:
        decisions = tmp_path / "docs" / "decisions"
        decisions.mkdir(parents=True)
        bad = decisions / "DEC-001.md"
        bad.write_text(
            "---\n"
            "id: DEC-999\n"
            'title: "x"\n'
            "status: nope\n"
            "date: 2026-01-01\n"
            "supersedes: null\n"
            "superseded_by: null\n"
            "owners: []\n"
            "---\n\n"
            "# wrong\n\n"
            "No required sections here.\n",
            encoding="utf-8",
        )
        record = dr.load_record(bad)
        problems = dr.validate_record(record)
        joined = " ".join(problems)
        assert "invalid status" in joined
        assert "filename does not match" in joined
        assert "supersedes must be a list" in joined
        assert "owners must be a non-empty list" in joined
        assert "missing '## Context'" in joined

    def test_validate_record_bad_supersedes_entry(self, tmp_path: Path) -> None:
        decisions = tmp_path / "docs" / "decisions"
        decisions.mkdir(parents=True)
        path = decisions / "DEC-002.md"
        path.write_text(
            "---\n"
            "id: DEC-002\n"
            'title: "ok"\n'
            "status: accepted\n"
            "date: 2026-01-01\n"
            'supersedes: ["not-an-id"]\n'
            "superseded_by: null\n"
            'owners: ["gov"]\n'
            "---\n\n"
            "# DEC-002: ok\n\n"
            "## Context\n\na\n\n"
            "## Decision\n\nb\n\n"
            "## Consequences\n\nc\n",
            encoding="utf-8",
        )
        problems = dr.validate_record(dr.load_record(path))
        assert any("supersedes entry" in p for p in problems)

    def test_skill_duplicates_decision_text(self) -> None:
        assert dr.skill_duplicates_decision_text("# no section\n") == []
        long = "y" * 120
        text = f"## Decisions since 2026-01-01\n- DEC-001 — {long}\n## Other\n"
        fails = dr.skill_duplicates_decision_text(text)
        assert fails and "restates DEC-001" in fails[0]


class TestGenerateDecisionIndex:
    def test_repo_root_from_and_missing(self, tmp_path: Path) -> None:
        with pytest.raises(SystemExit, match="cannot locate"):
            gdi.repo_root_from(tmp_path)
        seed_minimal_decision_records(tmp_path, write_skill=False)
        (tmp_path / "Makefile").write_text("# stub\n", encoding="utf-8")
        assert gdi.repo_root_from(tmp_path / "docs") == tmp_path.resolve()

    def test_main_write_and_check(self, tmp_path: Path) -> None:
        seed_minimal_decision_records(tmp_path, write_skill=False)
        (tmp_path / "Makefile").write_text("# stub\n", encoding="utf-8")
        # Drop generated artefacts so write path runs.
        (tmp_path / "docs/decisions/index.md").unlink()
        (tmp_path / "docs/decisions/index.json").unlink()
        gdi.main(["--root", str(tmp_path)])
        assert (tmp_path / "docs/decisions/index.md").is_file()
        assert (tmp_path / "harness/node/.governance/decision-log.md").is_file()
        gdi.main(["--root", str(tmp_path), "--check"])

    def test_main_check_drift_and_bad_record(self, tmp_path: Path) -> None:
        seed_minimal_decision_records(tmp_path, write_skill=False)
        (tmp_path / "Makefile").write_text("# stub\n", encoding="utf-8")
        gdi.main(["--root", str(tmp_path)])
        (tmp_path / "docs/decisions/index.md").write_text("# stale\n", encoding="utf-8")
        with pytest.raises(SystemExit, match="drift"):
            gdi.main(["--root", str(tmp_path), "--check"])

        bad = tmp_path / "docs/decisions/DEC-001.md"
        bad.write_text("---\nid: DEC-001\n---\nbody\n", encoding="utf-8")
        with pytest.raises(SystemExit, match="FAILED"):
            gdi.main(["--root", str(tmp_path)])

    def test_main_missing_decisions_dir(self, tmp_path: Path) -> None:
        (tmp_path / "Makefile").write_text("# stub\n", encoding="utf-8")
        with pytest.raises(SystemExit, match="missing"):
            gdi.main(["--root", str(tmp_path)])

    def test_module_as_main(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        seed_minimal_decision_records(tmp_path, write_skill=False)
        (tmp_path / "Makefile").write_text("# stub\n", encoding="utf-8")
        monkeypatch.setattr(
            sys,
            "argv",
            ["generate_decision_index.py", "--root", str(tmp_path), "--check"],
        )
        # Ensure indexes match before check.
        gdi.main(["--root", str(tmp_path)])
        script = Path(gdi.__file__).resolve()
        runpy.run_path(str(script), run_name="__main__")


class TestValidateGovernanceDocsExtraBranches:
    def test_unreadable_decision_file(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        seed_minimal_decision_records(tmp_path)
        (tmp_path / ".governance").mkdir(exist_ok=True)
        (tmp_path / ".governance/policy.json").write_text(
            json.dumps(
                {
                    "charter_version": "1.0",
                    "governance_skill_path": "agents/GOVERNANCE_SKILL.md",
                    "skill_max_age_days": 90,
                }
            ),
            encoding="utf-8",
        )
        (tmp_path / "docs/PROJECT-CHARTER.md").write_text("# Charter v1.0\n", encoding="utf-8")
        # Corrupt frontmatter so load_all raises ValueError.
        (tmp_path / "docs/decisions/DEC-001.md").write_text("not a record\n", encoding="utf-8")
        monkeypatch.chdir(tmp_path)
        with pytest.raises(SystemExit, match="unreadable"):
            validate_governance_docs(tmp_path)

    def test_missing_generated_index_and_sot_pointer(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        seed_minimal_decision_records(tmp_path)
        (tmp_path / ".governance").mkdir(exist_ok=True)
        (tmp_path / ".governance/policy.json").write_text(
            json.dumps(
                {
                    "charter_version": "1.0",
                    "governance_skill_path": "agents/GOVERNANCE_SKILL.md",
                    "skill_max_age_days": 90,
                }
            ),
            encoding="utf-8",
        )
        (tmp_path / "docs/PROJECT-CHARTER.md").write_text("# Charter v1.0\n", encoding="utf-8")
        (tmp_path / "docs/decisions/index.md").unlink()
        today = utc_today().isoformat()
        (tmp_path / "agents/GOVERNANCE_SKILL.md").write_text(
            f"# Governance Skill\nReviewed: {today}\n\n## Decisions since {today}\nNo SoT pointer.\n",
            encoding="utf-8",
        )
        monkeypatch.chdir(tmp_path)
        with pytest.raises(SystemExit) as exc_info:
            validate_governance_docs(tmp_path)
        msg = str(exc_info.value)
        assert "generated decision index missing" in msg
        assert "must point at docs/decisions" in msg

    def test_invalid_and_missing_record_dates(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        seed_minimal_decision_records(tmp_path, dec_id="DEC-010", date="2026-01-01")
        (tmp_path / ".governance").mkdir(exist_ok=True)
        (tmp_path / ".governance/policy.json").write_text(
            json.dumps(
                {
                    "charter_version": "1.0",
                    "governance_skill_path": "agents/GOVERNANCE_SKILL.md",
                    "skill_max_age_days": 90,
                }
            ),
            encoding="utf-8",
        )
        (tmp_path / "docs/PROJECT-CHARTER.md").write_text("# Charter v1.0\n", encoding="utf-8")
        decisions = tmp_path / "docs/decisions"
        # Valid shape but non-ISO date (schema does not check ISO).
        (decisions / "DEC-011.md").write_text(
            "---\n"
            "id: DEC-011\n"
            'title: "bad date"\n'
            "status: accepted\n"
            "date: not-a-date\n"
            "supersedes: []\n"
            "superseded_by: null\n"
            'owners: ["gov"]\n'
            "---\n\n"
            "# DEC-011: bad date\n\n"
            "## Context\n\na\n\n"
            "## Decision\n\nb\n\n"
            "## Consequences\n\nc\n",
            encoding="utf-8",
        )
        # Missing date field: load succeeds; schema fails; skill loop continues.
        (decisions / "DEC-012.md").write_text(
            "---\n"
            "id: DEC-012\n"
            'title: "no date"\n'
            "status: accepted\n"
            "supersedes: []\n"
            "superseded_by: null\n"
            'owners: ["gov"]\n'
            "---\n\n"
            "# DEC-012: no date\n\n"
            "## Context\n\na\n\n"
            "## Decision\n\nb\n\n"
            "## Consequences\n\nc\n",
            encoding="utf-8",
        )
        # Refresh indexes so drift is not the first failure (schema fails first).
        records = dr.load_all(decisions)
        payload = dr.index_payload(records)
        (decisions / "index.json").write_text(dr.render_index_json(payload), encoding="utf-8")
        (decisions / "index.md").write_text(dr.render_index_md(payload), encoding="utf-8")
        monkeypatch.chdir(tmp_path)
        with pytest.raises(SystemExit) as exc_info:
            validate_governance_docs(tmp_path)
        msg = str(exc_info.value)
        assert "invalid date" in msg or "missing frontmatter field 'date'" in msg
