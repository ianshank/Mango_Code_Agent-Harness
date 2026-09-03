"""The protected-path attestation table must be derived, not transcribed (DEC-038).

`harness/CONTRACT.md` requires a PR that touches a protected path to carry a
per-file table, because applying `infra-reviewed` is the human attestation the
gate stands on. That table was written by hand from a CI log and drifted: on this
repository's own governance PR it claimed thirteen rows while the validator's set
was ten. These tests hold the deriver to the property that makes it worth having
-- it is the gate's own matcher and discovery, not a second implementation that
happens to agree -- and hold `--check` to failing closed on every shape of
disagreement.

The fixtures build actual git repositories. A stubbed `git` would let the deriver
and the gate agree about a world neither one runs in, which is the failure mode
this module exists to remove.
"""

from __future__ import annotations

import logging
import os
import subprocess
import sys
from pathlib import Path

import pytest

from harness.shared.governance import attestation

pytestmark = pytest.mark.governance

POLICY_PATTERNS = ["secrets/**", "Makefile"]


def attested(paths: list[str]) -> str:
    """A minimal description carrying `paths` under the heading `--check` looks for."""
    return "## Protected-path attestation\n\n" + attestation.render(paths, "markdown") + "\n"


def _git(repo: Path, *args: str) -> str:
    return subprocess.check_output(["git", *args], cwd=repo, encoding="utf-8")


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    """A repository with a `base` branch and one commit on top touching two paths.

    One protected (`secrets/key.txt`), one not (`README.md`), so a passing
    assertion has to discriminate rather than merely count.
    """
    root = tmp_path / "repo"
    (root / "secrets").mkdir(parents=True)
    _git(root.parent, "init", "--quiet", root.name)
    _git(root, "config", "user.email", "t@example.invalid")
    _git(root, "config", "user.name", "t")
    (root / "README.md").write_text("base\n", encoding="utf-8")
    _git(root, "add", "-A")
    _git(root, "commit", "--quiet", "-m", "base")
    _git(root, "branch", "-M", "base")
    # `git_modified_files` diffs `origin/<base_ref>`; a local ref of that name is
    # indistinguishable to git and keeps the fixture offline.
    _git(root, "update-ref", "refs/remotes/origin/base", "HEAD")
    _git(root, "checkout", "--quiet", "-b", "work")
    (root / "secrets" / "key.txt").write_text("x\n", encoding="utf-8")
    (root / "README.md").write_text("changed\n", encoding="utf-8")
    _git(root, "add", "-A")
    _git(root, "commit", "--quiet", "-m", "work")
    return root


class TestProtectedChanges:
    def test_reports_only_the_protected_path(self, repo: Path) -> None:
        assert attestation.protected_changes(repo, POLICY_PATTERNS, "base") == ["secrets/key.txt"]

    def test_a_change_touching_nothing_protected_is_an_empty_table(self, repo: Path) -> None:
        assert attestation.protected_changes(repo, ["nothing/**"], "base") == []

    def test_uses_the_gates_own_matcher_and_discovery(self) -> None:
        """The property the module exists for, asserted as identity, not similarity.

        A deriver that agrees with the gate today by reimplementing it diverges
        the first time the gate changes -- `git_modified_files` gained the
        `core.quotePath=false` handling exactly that way. Binding the symbols
        rather than the behaviour makes divergence impossible instead of
        detectable.
        """
        from harness.shared import validate_invariants as vi

        assert attestation.is_protected is vi.is_protected
        assert attestation.git_modified_files is vi.git_modified_files
        assert attestation.load_protected_patterns is vi.load_protected_patterns

    def test_results_are_deduplicated_and_ordered_like_the_gate(self, repo: Path) -> None:
        """`git_modified_files` unions four commands; the gate sorts, so this must too."""
        derived = attestation.protected_changes(repo, POLICY_PATTERNS, "base")
        assert derived == sorted(set(derived))


class TestBaseRefResolution:
    def test_explicit_wins_over_environment(self, repo: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv(attestation.BASE_REF_ENV, "from-env")
        assert attestation.resolve_base_ref(repo, "explicit") == "explicit"

    def test_environment_wins_over_the_remote_default(self, repo: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv(attestation.BASE_REF_ENV, "from-env")
        assert attestation.resolve_base_ref(repo) == "from-env"

    def test_falls_back_to_the_remote_published_default(self, repo: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """No branch name is hard-coded: an adopter fork's default is read from the remote."""
        monkeypatch.delenv(attestation.BASE_REF_ENV, raising=False)
        _git(repo, "symbolic-ref", "refs/remotes/origin/HEAD", "refs/remotes/origin/base")
        assert attestation.resolve_base_ref(repo) == "base"

    def test_fails_closed_when_no_base_can_be_determined(
        self, repo: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
    ) -> None:
        monkeypatch.delenv(attestation.BASE_REF_ENV, raising=False)
        with caplog.at_level(logging.ERROR, logger="harness.shared"), pytest.raises(SystemExit) as exc:
            attestation.resolve_base_ref(repo)
        assert exc.value.code == 1
        assert "no base ref" in caplog.text


class TestBaseRefScope:
    def test_restores_a_previous_value(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv(attestation.BASE_REF_ENV, "before")
        with attestation.base_ref_scope("during"):
            assert attestation.os.environ[attestation.BASE_REF_ENV] == "during"
        assert attestation.os.environ[attestation.BASE_REF_ENV] == "before"

    def test_removes_the_variable_it_introduced(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv(attestation.BASE_REF_ENV, raising=False)
        with attestation.base_ref_scope("during"):
            pass
        assert attestation.BASE_REF_ENV not in attestation.os.environ

    def test_restores_after_an_exception(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv(attestation.BASE_REF_ENV, "before")
        with pytest.raises(RuntimeError), attestation.base_ref_scope("during"):
            raise RuntimeError("boom")
        assert attestation.os.environ[attestation.BASE_REF_ENV] == "before"


class TestRender:
    def test_plain_is_one_path_per_line(self) -> None:
        assert attestation.render(["a", "b"], "plain") == "a\nb"

    def test_markdown_round_trips_through_the_parser(self) -> None:
        """Generated tables must satisfy the checker, or `--check` is unusable."""
        paths = ["Makefile", "secrets/key.txt"]
        assert attestation.table_paths(attestation.render(paths, "markdown")) == paths


class TestTablePaths:
    def test_skips_the_header_and_separator_rows(self) -> None:
        table = "| Protected path | Why |\n| --- | --- |\n| `Makefile` | reason |"
        assert attestation.table_paths(table) == ["Makefile"]

    def test_drops_the_header_of_a_table_that_does_not_start_the_body(self) -> None:
        """The header is found by the separator under it, not by being row one."""
        body = "Some prose first.\n\n| Path | Why |\n| --- | --- |\n| `Makefile` | reason |\n"
        assert attestation.table_paths(body) == ["Makefile"]

    def test_reads_every_table_in_a_body_that_has_several(self) -> None:
        body = (
            "| Path | Why |\n| --- | --- |\n| `Makefile` | a |\n\n"
            "| Path | Why |\n| --- | --- |\n| `secrets/key.txt` | b |\n"
        )
        assert attestation.table_paths(body) == ["Makefile", "secrets/key.txt"]

    def test_a_row_above_a_separator_that_is_not_adjacent_is_kept(self) -> None:
        """Only the immediately preceding row is a header; a blank line breaks that."""
        body = "| `Makefile` | a |\n\n| --- | --- |\n"
        assert attestation.table_paths(body) == ["Makefile"]

    def test_ignores_backticked_prose_outside_a_table(self) -> None:
        assert attestation.table_paths("touching `Makefile` was unavoidable\n") == []

    def test_reads_a_cell_written_without_backticks(self) -> None:
        assert attestation.table_paths("| Makefile | reason |") == ["Makefile"]

    def test_skips_an_empty_leading_cell(self) -> None:
        assert attestation.table_paths("|  | reason |") == []


#: A description shaped like the real thing: a summary table the change does not
#: attest to, then the attestation section, then a section after it. Scoping is
#: what stops the first table's rows being reported as paths the change does not
#: touch, and the third section's rows being attested by accident.
PR_BODY = """## Summary

| Item | What passed before |
|---|---|
| `lint-node` in ci | the recorded blocker was wrong |

## Protected-path attestation

| File | Change | Why it is safe |
|---|---|---|
| `Makefile` | new target | additive |

Once this table is reviewed, the label may be applied.

## Backward compatibility

| Caller | Effect |
|---|---|
| `everything.py` | none |
"""


class TestSectionScoping:
    def test_reads_only_the_attested_section(self) -> None:
        section = attestation.section_body(PR_BODY, attestation.DEFAULT_SECTION)
        assert section is not None
        assert attestation.table_paths(section) == ["Makefile"]

    def test_a_description_with_no_such_heading_returns_none(self) -> None:
        assert attestation.section_body("## Summary\n\nno table here\n", attestation.DEFAULT_SECTION) is None

    def test_the_heading_pattern_is_configurable(self) -> None:
        body = "## Infra sign-off\n\n| P | W |\n|---|---|\n| `Makefile` | a |\n"
        section = attestation.section_body(body, r"^#{1,6}\s.*sign-off")
        assert section is not None
        assert attestation.table_paths(section) == ["Makefile"]

    def test_check_passes_on_a_full_description(self, tmp_path: Path) -> None:
        body = tmp_path / "body.md"
        body.write_text(PR_BODY, encoding="utf-8")
        assert attestation._check(["Makefile"], body) == 0

    def test_check_fails_when_the_section_is_absent(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        """A description that never attests must fail, not pass for lack of a table."""
        body = tmp_path / "body.md"
        body.write_text("## Summary\n\n| A | B |\n|---|---|\n| `Makefile` | x |\n", encoding="utf-8")
        with caplog.at_level(logging.ERROR, logger="harness.shared"):
            assert attestation._check(["Makefile"], body) == 1
        assert "no heading matching" in caplog.text

    def test_a_row_in_a_later_section_does_not_attest(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        body = tmp_path / "body.md"
        body.write_text(PR_BODY, encoding="utf-8")
        with caplog.at_level(logging.ERROR, logger="harness.shared"):
            assert attestation._check(["Makefile", "everything.py"], body) == 1
        assert "not attested: everything.py" in caplog.text


class TestCompare:
    def test_missing_row(self) -> None:
        missing, unexpected = attestation.compare(["a", "b"], "| `a` | why |")
        assert (missing, unexpected) == (["b"], [])

    def test_row_naming_a_path_the_change_does_not_touch(self) -> None:
        missing, unexpected = attestation.compare(["a"], "| `a` | why |\n| `z` | why |")
        assert (missing, unexpected) == ([], ["z"])

    def test_exact_match(self) -> None:
        assert attestation.compare(["a"], "| `a` | why |") == ([], [])


class TestCheck:
    def test_a_body_with_no_table_fails_closed(self, tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
        """"No table" must never read as "no rows to attest"."""
        body = tmp_path / "body.md"
        body.write_text("## Protected-path attestation\n\nNothing tabular here.\n", encoding="utf-8")
        with caplog.at_level(logging.ERROR, logger="harness.shared"):
            assert attestation._check(["Makefile"], body) == 1
        assert "contains no attestation table" in caplog.text

    def test_an_unreadable_body_fails_closed(self, tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
        with caplog.at_level(logging.ERROR, logger="harness.shared"):
            assert attestation._check([], tmp_path / "absent.md") == 1
        assert "could not read" in caplog.text

    def test_a_missing_row_fails_and_names_the_path(self, tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
        body = tmp_path / "body.md"
        body.write_text(attested(["Makefile"]), encoding="utf-8")
        with caplog.at_level(logging.ERROR, logger="harness.shared"):
            assert attestation._check(["Makefile", "secrets/key.txt"], body) == 1
        assert "not attested: secrets/key.txt" in caplog.text

    def test_an_extra_row_fails_and_names_the_cell(self, tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
        body = tmp_path / "body.md"
        body.write_text(attested(["Makefile", "gone.py"]), encoding="utf-8")
        with caplog.at_level(logging.ERROR, logger="harness.shared"):
            assert attestation._check(["Makefile"], body) == 1
        assert "names no protected path" in caplog.text

    def test_a_matching_table_passes(self, tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
        body = tmp_path / "body.md"
        body.write_text(attested(["Makefile"]), encoding="utf-8")
        with caplog.at_level(logging.INFO, logger="harness.shared"):
            assert attestation._check(["Makefile"], body) == 0
        assert "[PASS]" in caplog.text


class TestCli:
    def _policy(self, tmp_path: Path) -> Path:
        policy = tmp_path / "policy.json"
        policy.write_text('{"protected_paths": ["secrets/**", "Makefile"]}', encoding="utf-8")
        return policy

    def test_prints_the_table(self, repo: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
        code = attestation.main(
            ["--workspace", str(repo), "--policy", str(self._policy(tmp_path)), "--base-ref", "base"]
        )
        assert code == 0
        assert "| `secrets/key.txt` |" in capsys.readouterr().out

    def test_plain_format_prints_bare_paths(
        self, repo: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        code = attestation.main(
            [
                "--workspace", str(repo),
                "--policy", str(self._policy(tmp_path)),
                "--base-ref", "base",
                "--format", "plain",
            ]
        )
        assert code == 0
        assert capsys.readouterr().out.strip() == "secrets/key.txt"

    def test_a_change_touching_nothing_protected_prints_no_table(
        self, repo: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str], caplog: pytest.LogCaptureFixture
    ) -> None:
        policy = tmp_path / "empty.json"
        policy.write_text('{"protected_paths": ["nothing/**"]}', encoding="utf-8")
        with caplog.at_level(logging.INFO, logger="harness.shared"):
            code = attestation.main(["--workspace", str(repo), "--policy", str(policy), "--base-ref", "base"])
        assert code == 0
        assert capsys.readouterr().out == ""
        assert "no attestation is required" in caplog.text

    def test_check_mode_verifies_a_written_table(self, repo: Path, tmp_path: Path) -> None:
        body = tmp_path / "body.md"
        body.write_text(attested(["secrets/key.txt"]), encoding="utf-8")
        argv = [
            "--workspace", str(repo),
            "--policy", str(self._policy(tmp_path)),
            "--base-ref", "base",
            "--check", str(body),
        ]
        assert attestation.main(argv) == 0
        body.write_text(attested(["Makefile"]), encoding="utf-8")
        assert attestation.main(argv) == 1


class TestStandaloneInvocation:
    def test_runs_without_the_package_on_sys_path(self, repo: Path, tmp_path: Path) -> None:
        """The `except ImportError` fallback is a real entry point, not decoration.

        `make attestation` invokes the file by path, so the module must import its
        siblings with no package context -- run from a directory that is not the
        repository root, which is what breaks a fallback that only ever worked by
        accident of the caller's cwd. Pointed at the fixture repository so the
        assertion is about the import path and nothing else.
        """
        script = attestation.DEFAULT_WORKSPACE_DIR / "harness" / "shared" / "governance" / "attestation.py"
        policy = tmp_path / "policy.json"
        policy.write_text('{"protected_paths": ["secrets/**"]}', encoding="utf-8")
        result = subprocess.run(
            [
                sys.executable, str(script),
                "--workspace", str(repo),
                "--policy", str(policy),
                "--base-ref", "base",
                "--format", "plain",
            ],
            cwd=script.parent,
            capture_output=True,
            text=True,
            env={**os.environ, "PYTHONPATH": ""},
        )
        assert result.returncode == 0, result.stderr
        assert result.stdout.strip() == "secrets/key.txt"
