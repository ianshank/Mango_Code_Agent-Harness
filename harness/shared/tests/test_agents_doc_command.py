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
import subprocess
import sys
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

    def test_a_document_with_no_reviewed_line_is_left_to_the_blocking_rule(self, tmp_path: Path) -> None:
        """Same reasoning as the unparseable date, one step earlier: a document
        with no date at all already fails `make ci`, so reporting it weekly as
        well files an issue for something already red."""
        write_document(tmp_path / "pkg", reviewed=None)
        config = AgentsDocConfig(additional_directories=("pkg",))
        assert stale_documents(tmp_path, config, 90, date(2026, 10, 1)) == []

    def test_a_symlinked_document_is_not_read_for_staleness(self, tmp_path: Path) -> None:
        """The report reached a document `audit()` refuses, and read a file outside
        the checkout to do it: `path.is_file()` follows links. Reporting an external
        document's date as this repository's staleness is the same defect as parsing
        it -- one report further on."""
        write_document(tmp_path / "outside", reviewed="2020-01-01")
        pkg = tmp_path / "repo" / "pkg"
        pkg.mkdir(parents=True)
        (pkg / "AGENTS.md").symlink_to(tmp_path / "outside" / "AGENTS.md")
        (pkg / "CLAUDE.md").write_text("@AGENTS.md\n", encoding="utf-8")
        config = AgentsDocConfig(additional_directories=("pkg",))
        assert stale_documents(tmp_path / "repo", config, 90, date(2026, 10, 1)) == []

    def test_an_escaping_directory_is_not_read_for_staleness(self, tmp_path: Path) -> None:
        """Same rule one level up: a configured directory that resolves outside is a
        finding in `audit()`, so this path declines to read it rather than reporting
        on a tree the repository does not own."""
        write_document(tmp_path / "outside", reviewed="2020-01-01")
        repo = tmp_path / "repo"
        repo.mkdir()
        (repo / "pkg").symlink_to(tmp_path / "outside", target_is_directory=True)
        config = AgentsDocConfig(additional_directories=("pkg",))
        assert stale_documents(repo, config, 90, date(2026, 10, 1)) == []

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

    def test_nothing_stale_prints_nothing_and_still_exits_zero(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """The workflow opens an issue only when this output is non-empty, so a
        run with nothing to report must print nothing rather than an empty table
        -- a heading with no rows is an issue nobody can act on."""
        write_document(tmp_path / "pkg")
        policy = write_policy(tmp_path, policy_block(additional_directories=["pkg"]))
        argv = ["--repo-root", str(tmp_path), "--policy", str(policy), "--stale-since-days", "36500"]
        assert main(argv) == 0
        assert capsys.readouterr().out == ""


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


class TestTheSiblingImportFallback:
    """`python harness/shared/agents_doc.py` has to work, and no in-process test
    can prove it: the editable install makes `harness.shared` importable, so the
    `try` arm always wins here and the `except ImportError` arm -- five modules
    deep, since every sibling needs its own -- is never entered. `python -S -E`
    is the adopter's bare invocation: no site processing, no `PYTHON*` variables,
    so the script's own directory at the head of `sys.path` is the only way any
    of it resolves. The same idiom guards the shim entry points."""

    def test_the_gate_runs_as_a_script_from_its_own_directory(self) -> None:
        shared = Path(__file__).resolve().parents[1]
        result = subprocess.run(
            [sys.executable, "-S", "-E", "agents_doc.py", "--repo-root", str(shared.parents[1]), "--list"],
            cwd=shared,
            capture_output=True,
            text=True,
            check=False,
        )
        assert result.returncode == 0, result.stderr
        assert "harness/shared" in result.stdout.splitlines()

    def test_the_package_path_is_genuinely_unavailable_there(self) -> None:
        """The positive control. Without it the test above would pass just as well
        through the `try` arm, and prove nothing about the fallback."""
        shared = Path(__file__).resolve().parents[1]
        result = subprocess.run(
            [sys.executable, "-S", "-E", "-c", "import harness.shared.agents_doc_checks"],
            cwd=shared,
            capture_output=True,
            text=True,
            check=False,
        )
        assert result.returncode != 0
        assert "No module named 'harness'" in result.stderr


# --- This repository ------------------------------------------------------------
