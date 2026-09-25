"""The ``agents_doc`` command line and its staleness report.

Split from `test_agents_doc.py` when it reached ``limits.test_size_budget_lines``,
along the seam the source uses: `agents_doc` owns how the gate is invoked and how
it reports, `agents_doc_checks` owns what is true. That direction is load-bearing
and `test_import_direction.py` holds it -- a command line imports the checks, not
the other way around.

The staleness half is the one worth reading twice. C-ADOC-4 says an old
`**Reviewed:**` date must *not* block a pull request -- a clock-dependent gate
over two dozen documents turns CI red on a date boundary for a change that
touched none of them -- so these assert that a stale date is reported and that
a missing or unparseable one is what actually fails.
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import pytest

from harness.shared.agents_doc import main, render_staleness_report, stale_documents
from harness.shared.agents_doc_policy import POLICY_BLOCK, AgentsDocConfig
from harness.shared.tests._agents_doc_helpers import (
    policy_block,
    write_document,
    write_policy,
)

pytestmark = pytest.mark.governance


class TestStaleness:
    """C-ADOC-4. Reported, never blocking. Presence of `**Reviewed:**` is a blocking rule;
    its age is not, because a clock-dependent gate over twenty-five documents
    turns unrelated pull requests red at a date boundary (DEC-070, C-ADOC-4)."""

    @staticmethod
    def tree(tmp_path: Path, reviewed: str) -> AgentsDocConfig:
        write_document(tmp_path / "pkg", reviewed=reviewed)
        return AgentsDocConfig(additional_directories=("pkg",))

    def test_a_fresh_document_is_not_stale(self, tmp_path: Path) -> None:
        config = self.tree(tmp_path, "2026-09-19")
        assert stale_documents(tmp_path, config, 90, date(2026, 10, 1)) == []

    def test_a_document_past_the_horizon_is_reported(self, tmp_path: Path) -> None:
        config = self.tree(tmp_path, "2026-01-01")
        assert stale_documents(tmp_path, config, 90, date(2026, 10, 1)) == [("pkg", "2026-01-01", 273)]

    def test_an_unparseable_date_is_left_to_the_blocking_rule(self, tmp_path: Path) -> None:
        """Reporting it here as well would file an issue for something that has
        already failed `make ci`, which trains people to ignore the issue."""
        config = self.tree(tmp_path, "last-tuesday")
        assert stale_documents(tmp_path, config, 90, date(2026, 10, 1)) == []

    def test_a_missing_document_is_not_a_staleness_report(self, tmp_path: Path) -> None:
        (tmp_path / "pkg").mkdir()
        config = AgentsDocConfig(additional_directories=("pkg",))
        assert stale_documents(tmp_path, config, 90, date(2026, 10, 1)) == []

    def test_nothing_stale_renders_nothing(self) -> None:
        """The workflow appends this to an issue body and opens the issue only
        when the file is non-empty, so an empty string is load-bearing."""
        assert render_staleness_report([], 90, "AGENTS.md") == ""

    def test_the_report_names_the_directory_and_the_age(self) -> None:
        report = render_staleness_report([("pkg", "2026-01-01", 273)], 90, "AGENTS.md")
        assert "| `pkg` | 2026-01-01 | 273 |" in report
        assert "past 90 days" in report

    def test_the_command_line_reports_and_still_exits_zero(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Exit 0 is the whole point: this path must never fail a pipeline."""
        write_document(tmp_path / "pkg", reviewed="2020-01-01")
        policy = write_policy(tmp_path, policy_block(additional_directories=["pkg"]))
        assert main(["--repo-root", str(tmp_path), "--policy", str(policy), "--stale-since-days", "1"]) == 0
        assert "| `pkg` |" in capsys.readouterr().out


class TestCommandLine:
    """Each case passes `--policy`. Without it the CLI resolves this repository's
    policy, whose `additional_directories` name paths a `tmp_path` tree does not
    have -- so the run under test would be judged against the wrong contract."""

    def test_list_prints_the_required_directories(self, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
        write_document(tmp_path / "pkg")
        policy = write_policy(tmp_path, policy_block(min_documented_directories=1))
        assert main(["--repo-root", str(tmp_path), "--policy", str(policy), "--list"]) == 0
        assert capsys.readouterr().out.strip() == "pkg"

    def test_a_clean_tree_exits_zero(self, tmp_path: Path) -> None:
        for name in ("one", "two"):
            write_document(tmp_path / name)
        policy = write_policy(tmp_path, policy_block(min_documented_directories=2))
        assert main(["--repo-root", str(tmp_path), "--policy", str(policy)]) == 0

    def test_findings_exit_non_zero(self, tmp_path: Path) -> None:
        policy = write_policy(tmp_path, policy_block())
        assert main(["--repo-root", str(tmp_path), "--policy", str(policy)]) == 1

    def test_an_explicit_override_reaches_the_audit(self, tmp_path: Path) -> None:
        """`--max-lines` is the one threshold the command line can tighten, so a
        run can prove a stricter budget without editing a protected policy."""
        write_document(tmp_path / "pkg")
        policy = write_policy(tmp_path, policy_block(min_documented_directories=1))
        argv = ["--repo-root", str(tmp_path), "--policy", str(policy)]
        assert main(argv) == 0
        assert main([*argv, "--max-lines", "5"]) == 1

    def test_an_unreadable_policy_exits_non_zero_rather_than_raising(self, tmp_path: Path) -> None:
        """Fail closed: a gate that crashes on its own policy has still not
        judged the tree, and an exception trace is not a verdict."""
        bad = tmp_path / "policy.json"
        bad.write_text(json.dumps({POLICY_BLOCK: {"max_lines": 1}}), encoding="utf-8")
        assert main(["--repo-root", str(tmp_path), "--policy", str(bad)]) == 1


# --- This repository ------------------------------------------------------------
