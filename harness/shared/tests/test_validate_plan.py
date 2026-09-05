"""Behavioural tests for the plan gate CLI.

Spec: ``docs/specs/plan-review-framework.md`` (R-PLR-5, R-PLR-6).

The rules themselves are covered by ``test_plan_rules.py``. What is pinned here is
the part a rule test cannot reach: which plans the gate decides to look at, and
what it does when it cannot read one. A gate scoped by git diff has a specific way
of dying -- it matches nothing and reports success -- so the scoping is asserted on
the *set of plans examined*, not just on the exit code.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from harness.shared.tests.conftest import POSIX_ONLY
from harness.shared.validate_plan import build_parser, changed_plans, main, review

pytestmark = pytest.mark.governance

REPO = Path(__file__).resolve().parents[3]

CONFORMING = """\
# Spec: a conforming plan

## Requirements

- R-EX-1: The thing MUST happen.

## Steps

1. Do it — produces `out.py`

## Files touched

- `out.py`

## Acceptance criteria

- [ ] AC-1: `out.py` exists — verified by `pytest -k test_out` · stage: `make ci` (R-EX-1)
- [ ] AC-2: A missing input is rejected with exit 1 (R-EX-1)
"""

DEFECTIVE = CONFORMING.replace(
    "- [ ] AC-2: A missing input is rejected with exit 1 (R-EX-1)",
    "- [ ] AC-2: The design is sound and the approach is reasonable (R-EX-1)",
)


@pytest.fixture
def repo(tmp_git_repo: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """An isolated repository, with the CI base-ref scrubbed.

    ``git_modified_files`` adds a ``git diff origin/$GITHUB_BASE_REF...HEAD``
    pass when that variable is set. GitHub Actions sets it on every pull request,
    so without this the fixture repo -- which has no ``origin`` at all -- makes
    git exit 128 and every scoping test below dies in CI while passing locally.
    These tests are about which paths the gate selects in a repository; the
    base-ref pass has its own test.
    """
    monkeypatch.delenv("GITHUB_BASE_REF", raising=False)
    (tmp_git_repo / "docs" / "specs").mkdir(parents=True)
    return tmp_git_repo


def _commit_all(repo: Path) -> None:
    subprocess.run(["git", "-C", str(repo), "add", "-A"], capture_output=True, check=True)
    # --allow-empty: git tracks no empty directory, so a repo whose only new path
    # is `docs/specs/` has nothing staged and `commit` would exit 1.
    subprocess.run(
        ["git", "-C", str(repo), "commit", "--allow-empty", "-m", "baseline"],
        capture_output=True,
        check=True,
    )


class TestModifiedScoping:
    """R-PLR-5 / AC-6."""

    def test_only_the_changed_spec_is_examined(self, repo: Path, capsys) -> None:
        (repo / "docs/specs/old.md").write_text(DEFECTIVE, encoding="utf-8")
        _commit_all(repo)
        (repo / "docs/specs/new.md").write_text(CONFORMING, encoding="utf-8")

        examined = changed_plans(repo, Path("docs/specs"))
        assert [p.name for p in examined] == ["new.md"], "a committed plan was re-litigated"

    def test_a_committed_defect_does_not_fail_an_unrelated_change(self, repo: Path) -> None:
        """The landed corpus predates these rules. Back-filling it would mean
        inventing retrospective plans for shipped work."""
        (repo / "docs/specs/old.md").write_text(DEFECTIVE, encoding="utf-8")
        _commit_all(repo)
        (repo / "unrelated.txt").write_text("x", encoding="utf-8")
        assert main(["--repo-root", str(repo)]) == 0

    def test_no_changed_spec_says_so_rather_than_passing_silently(
        self, repo: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """A scoped gate that matches nothing and prints nothing is how it goes
        quietly dead -- the shape `test_protected_path_liveness` exists to catch."""
        _commit_all(repo)
        assert main(["--repo-root", str(repo)]) == 0
        assert "0 examined" in capsys.readouterr().out

    def test_a_changed_defective_spec_fails(self, repo: Path) -> None:
        _commit_all(repo)
        (repo / "docs/specs/new.md").write_text(DEFECTIVE, encoding="utf-8")
        assert main(["--repo-root", str(repo)]) == 1

    def test_a_changed_conforming_spec_passes(self, repo: Path, capsys) -> None:
        _commit_all(repo)
        (repo / "docs/specs/new.md").write_text(CONFORMING, encoding="utf-8")
        assert main(["--repo-root", str(repo)]) == 0
        assert "1 plan(s) examined" in capsys.readouterr().out

    def test_the_template_is_never_examined(self, repo: Path) -> None:
        """`make spec` copies it verbatim, so it is a placeholder document by
        definition; the structural tier is what rejects an unfilled *copy*."""
        _commit_all(repo)
        (repo / "docs/specs/SPEC_TEMPLATE.md").write_text(DEFECTIVE, encoding="utf-8")
        assert changed_plans(repo, Path("docs/specs")) == []

    def test_changes_outside_the_spec_dir_are_ignored(self, repo: Path) -> None:
        _commit_all(repo)
        (repo / "notes.md").write_text(DEFECTIVE, encoding="utf-8")
        assert changed_plans(repo, Path("docs/specs")) == []


class TestTheBaseRefPassIsFailClosed:
    """The behaviour the fixture above scrubs, asserted rather than assumed."""

    def test_an_unresolvable_base_ref_raises_rather_than_reporting_nothing(
        self, tmp_git_repo: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Inherited from `validate_invariants`, and load-bearing: a gate that
        treated an unusable git state as "nothing changed" would pass every PR it
        could not inspect. This test is why the fixture scrubs the variable rather
        than the module tolerating a missing ref."""
        (tmp_git_repo / "docs" / "specs").mkdir(parents=True)
        monkeypatch.setenv("GITHUB_BASE_REF", "a-ref-that-does-not-exist")
        with pytest.raises(subprocess.CalledProcessError):
            changed_plans(tmp_git_repo, Path("docs/specs"))


class TestSweepMode:
    """`--all` is the one-off report over landed plans, not a gate."""

    def test_all_examines_committed_plans_too(self, repo: Path) -> None:
        (repo / "docs/specs/old.md").write_text(DEFECTIVE, encoding="utf-8")
        _commit_all(repo)
        assert main(["--repo-root", str(repo), "--all"]) == 1

    def test_the_parser_declares_both_modes(self) -> None:
        args = build_parser().parse_args([])
        assert args.all is False and args.spec_dir == Path("docs") / "specs"


class TestUnreadablePlanIsAFinding:
    """R-PLR-6 / AC-7: reported, never skipped."""

    def test_a_path_that_cannot_be_read_is_reported(self, tmp_path: Path) -> None:
        """A linter that silently passes what it cannot read is the protected-path
        pattern that matched zero files, in a new costume."""
        directory = tmp_path / "not-a-file.md"
        directory.mkdir()
        findings = review([directory], tmp_path)
        assert [f.defect_class for f in findings] == ["UNPARSEABLE_PLAN"]

    def test_the_finding_names_the_path(self, tmp_path: Path) -> None:
        directory = tmp_path / "not-a-file.md"
        directory.mkdir()
        assert "not-a-file.md" in review([directory], tmp_path)[0].ref


@POSIX_ONLY
class TestNegativeProbes:
    """AC-10: each seeded defect must turn the real gate red.

    Driven through the CLI as a subprocess, so what is exercised is the shipped
    entry point rather than an import of it.
    """

    @pytest.mark.parametrize(
        ("mutation", "expected"),
        [
            ("The design is sound and the approach is reasonable", "UNFALSIFIABLE_ACCEPTANCE"),
            ("`out.py` is checked — verified by inspection", "STAGE_REACHABILITY"),
            ("`out.py` is importable and complete", "MISSING_FAILURE_PATH"),
        ],
    )
    def test_a_seeded_defect_is_caught(self, tmp_path: Path, mutation: str, expected: str) -> None:
        spec_dir = tmp_path / "specs"
        spec_dir.mkdir()
        (spec_dir / "probe.md").write_text(
            CONFORMING.replace("A missing input is rejected with exit 1", mutation),
            encoding="utf-8",
        )
        result = subprocess.run(
            [
                "python3",
                str(REPO / "harness/shared/validate_plan.py"),
                "--repo-root",
                str(tmp_path),
                "--spec-dir",
                str(spec_dir),
                "--all",
            ],
            capture_output=True,
            text=True,
            cwd=REPO,
        )
        assert result.returncode == 1, result.stdout
        assert expected in result.stderr

    def test_the_conforming_baseline_stays_green(self, tmp_path: Path) -> None:
        """Without this, a rule tightened into rejecting everything would still
        pass every probe above."""
        spec_dir = tmp_path / "specs"
        spec_dir.mkdir()
        (spec_dir / "probe.md").write_text(CONFORMING, encoding="utf-8")
        result = subprocess.run(
            [
                "python3",
                str(REPO / "harness/shared/validate_plan.py"),
                "--repo-root",
                str(tmp_path),
                "--spec-dir",
                str(spec_dir),
                "--all",
            ],
            capture_output=True,
            text=True,
            cwd=REPO,
        )
        assert result.returncode == 0, result.stderr


class TestTheRepositoryPasses:
    def test_the_real_gate_is_green(self) -> None:
        result = subprocess.run(
            ["python3", str(REPO / "harness/shared/validate_plan.py"), "--repo-root", str(REPO)],
            capture_output=True,
            text=True,
            cwd=REPO,
        )
        assert result.returncode == 0, result.stderr


@POSIX_ONLY
class TestVerbosityDegradesRatherThanCrashing:
    """`args.log_level.upper()` went straight into `logging.basicConfig`, so
    `--log-level BOGUS` raised `ValueError: Unknown level` before a single plan
    was read, and the environment's `LOG_LEVEL` was not consulted at all
    (2026 standards audit M25)."""

    def _run(self, tmp_path: Path, *argv: str, **env: str) -> subprocess.CompletedProcess[str]:
        import os

        spec_dir = tmp_path / "specs"
        spec_dir.mkdir(exist_ok=True)
        (spec_dir / "probe.md").write_text(CONFORMING, encoding="utf-8")
        return subprocess.run(
            [
                "python3",
                str(REPO / "harness/shared/validate_plan.py"),
                "--repo-root",
                str(tmp_path),
                "--spec-dir",
                str(spec_dir),
                "--all",
                *argv,
            ],
            capture_output=True,
            text=True,
            cwd=REPO,
            env={**os.environ, **env},
        )

    def test_a_bogus_flag_value_is_not_a_crash(self, tmp_path: Path) -> None:
        result = self._run(tmp_path, "--log-level", "BOGUS")
        assert result.returncode == 0, result.stderr
        assert "Unknown level" not in result.stderr
        assert "plan: passed (1 plan(s) examined)" in result.stdout

    def test_a_bogus_environment_value_is_not_a_crash(self, tmp_path: Path) -> None:
        result = self._run(tmp_path, LOG_LEVEL="BOGUS")
        assert result.returncode == 0, result.stderr
        assert "Unknown level" not in result.stderr

    def test_the_verdict_is_byte_identical_across_levels(self, tmp_path: Path) -> None:
        quiet = self._run(tmp_path, LOG_LEVEL="CRITICAL")
        loud = self._run(tmp_path, LOG_LEVEL="DEBUG")
        assert quiet.returncode == loud.returncode == 0
        assert quiet.stdout == loud.stdout
