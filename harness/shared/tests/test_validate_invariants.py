"""Tests for harness/shared/validate_invariants.py — protected paths, secrets, size budget."""

import json
import logging
import subprocess
import unicodedata
from pathlib import Path

import pytest

from harness.shared import validate_invariants as vi

# `invariants_repo` arrives from `conftest.py` as a fixture; these two are
# ordinary functions and are imported. Both moved there when this module was
# split, so the two halves share one definition rather than importing across
# test modules.
from harness.shared.tests.conftest import _write_lines, invariants_policy_path

# --- load_protected_patterns ---

def test_load_protected_patterns_reads_policy(invariants_repo: Path):
    patterns = vi.load_protected_patterns(invariants_policy_path(invariants_repo))
    assert patterns == [".github/workflows/**", "Makefile"]


def test_load_protected_patterns_fails_closed_when_the_policy_is_missing(tmp_path: Path):
    # Renamed and re-commented: the "defaults" this used to describe are gone.
    # There is no longer a `[".github/**"]` branch for an absent key (R-CQ-8),
    # so an unreadable policy path is the only case left, and it exits 1.
    missing = tmp_path / "does-not-exist.json"
    with pytest.raises(SystemExit) as exc_info:
        vi.load_protected_patterns(missing)
    assert exc_info.value.code == 1


# --- git_modified_files ---

def test_git_modified_files_empty_when_clean(invariants_repo: Path):
    assert vi.git_modified_files(invariants_repo) == set()


def test_git_modified_files_detects_unstaged(invariants_repo: Path):
    # git diff --name-only only lists tracked-but-modified files, not untracked ones.
    f = invariants_repo / "src.py"
    f.write_text("x = 1\n", encoding="utf-8")
    subprocess.run(["git", "add", "src.py"], cwd=invariants_repo, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-m", "add"], cwd=invariants_repo, check=True, capture_output=True)
    f.write_text("x = 2\n", encoding="utf-8")  # now tracked-modified
    assert "src.py" in vi.git_modified_files(invariants_repo)


def test_git_modified_files_detects_staged(invariants_repo: Path):
    f = invariants_repo / "src.py"
    f.write_text("x = 1\n", encoding="utf-8")
    subprocess.run(["git", "add", "src.py"], cwd=invariants_repo, check=True, capture_output=True)
    assert "src.py" in vi.git_modified_files(invariants_repo)


def test_git_modified_files_detects_untracked(invariants_repo: Path):
    # Untracked (never staged) files must be caught so a new file in a protected
    # path cannot slip through before being staged (fail-closed).
    (invariants_repo / "Makefile").write_text("all:\n", encoding="utf-8")
    assert "Makefile" in vi.git_modified_files(invariants_repo)


def test_git_modified_files_ignores_gitignored(invariants_repo: Path):
    (invariants_repo / ".gitignore").write_text("*.log\n", encoding="utf-8")
    subprocess.run(["git", "add", ".gitignore"], cwd=invariants_repo, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-m", "gi"], cwd=invariants_repo, check=True, capture_output=True)
    (invariants_repo / "noise.log").write_text("noise\n", encoding="utf-8")
    assert "noise.log" not in vi.git_modified_files(invariants_repo)


# --- check_protected_paths ---

def test_check_protected_paths_pass_when_clean(invariants_repo: Path, caplog):
    with caplog.at_level(logging.INFO, logger=vi.logger.name):
        assert vi.check_protected_paths(invariants_repo, [".github/workflows/**", "Makefile"]) is True
    assert "[PASS]" in caplog.text


def test_check_protected_paths_fails_on_protected_change(invariants_repo: Path, caplog):
    mf = invariants_repo / "Makefile"
    mf.write_text("all:\n", encoding="utf-8")
    subprocess.run(["git", "add", "Makefile"], cwd=invariants_repo, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-m", "mk"], cwd=invariants_repo, check=True, capture_output=True)
    mf.write_text("all:\nclean:\n", encoding="utf-8")  # tracked-modified protected path
    with caplog.at_level(logging.ERROR, logger=vi.logger.name):
        assert vi.check_protected_paths(invariants_repo, [".github/workflows/**", "Makefile"]) is False
    assert "[FAIL]" in caplog.text
    assert "Makefile" in caplog.text


def test_check_protected_paths_allows_with_env(invariants_repo: Path):
    mf = invariants_repo / "Makefile"
    mf.write_text("all:\n", encoding="utf-8")
    subprocess.run(["git", "add", "Makefile"], cwd=invariants_repo, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-m", "mk"], cwd=invariants_repo, check=True, capture_output=True)
    mf.write_text("all:\nclean:\n", encoding="utf-8")  # tracked-modified protected path
    import os

    os.environ["ALLOW_GITHUB_CHANGES"] = "1"
    try:
        assert vi.check_protected_paths(invariants_repo, ["Makefile"]) is True
    finally:
        del os.environ["ALLOW_GITHUB_CHANGES"]


def test_check_protected_paths_ignores_non_protected(invariants_repo: Path):
    (invariants_repo / "feature.py").write_text("x = 1\n", encoding="utf-8")
    assert vi.check_protected_paths(invariants_repo, [".github/workflows/**", "Makefile"]) is True


# --- check_hardcoded_secrets ---

def test_check_hardcoded_secrets_clean(invariants_repo: Path):
    (invariants_repo / "app.py").write_text("API_KEY = os.environ.get('X')\n", encoding="utf-8")
    assert vi.check_hardcoded_secrets(invariants_repo) is True


def test_check_hardcoded_secrets_detects_literal(invariants_repo: Path, caplog):
    # Build the secret literal dynamically so this test file is not itself flagged.
    secret_literal = "NVIDIA_" + "API_KEY = 'nvapi-secret'\n"
    (invariants_repo / "leaky.py").write_text(secret_literal, encoding="utf-8")
    with caplog.at_level(logging.ERROR, logger=vi.logger.name):
        assert vi.check_hardcoded_secrets(invariants_repo) is False
    assert "[FAIL]" in caplog.text


def test_check_hardcoded_secrets_skips_venv(invariants_repo: Path):
    venv_file = invariants_repo / ".venv" / "lib" / "x.py"
    venv_file.parent.mkdir(parents=True)
    secret_literal = "NVIDIA_" + "API_KEY = 'leak'\n"
    venv_file.write_text(secret_literal, encoding="utf-8")
    assert vi.check_hardcoded_secrets(invariants_repo) is True


# --- check_size_budget ---

def test_check_size_budget_pass(invariants_repo: Path):
    (invariants_repo / "small.py").write_text("\n".join("x = 1" for _ in range(10)) + "\n", encoding="utf-8")
    assert vi.check_size_budget(invariants_repo, budget=500) is True


def test_check_size_budget_fails_over(invariants_repo: Path, caplog):
    (invariants_repo / "big.py").write_text("\n".join("x = 1" for _ in range(501)) + "\n", encoding="utf-8")
    with caplog.at_level(logging.ERROR, logger=vi.logger.name):
        assert vi.check_size_budget(invariants_repo, budget=500) is False
    assert "[FAIL]" in caplog.text


def test_check_size_budget_ignores_tests(invariants_repo: Path):
    (invariants_repo / "test_big.py").write_text("\n".join("x = 1" for _ in range(600)) + "\n", encoding="utf-8")
    assert vi.check_size_budget(invariants_repo, budget=500) is True


# --- main ---

def test_main_passes_on_clean_repo(invariants_repo: Path):
    assert vi.main(workspace_dir=invariants_repo, policy_path=invariants_policy_path(invariants_repo)) == 0


def test_main_fails_on_protected_path_violation(invariants_repo: Path):
    mf = invariants_repo / "Makefile"
    mf.write_text("all:\n", encoding="utf-8")
    subprocess.run(["git", "add", "Makefile"], cwd=invariants_repo, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-m", "mk"], cwd=invariants_repo, check=True, capture_output=True)
    mf.write_text("all:\nclean:\n", encoding="utf-8")  # tracked-modified protected path
    assert vi.main(workspace_dir=invariants_repo, policy_path=invariants_policy_path(invariants_repo)) == 1


def test_main_fails_on_hardcoded_secret(invariants_repo: Path):
    secret_literal = "API_SERVER_" + "KEY = 'k'\n"
    (invariants_repo / "leaky.py").write_text(secret_literal, encoding="utf-8")
    assert vi.main(workspace_dir=invariants_repo, policy_path=invariants_policy_path(invariants_repo)) == 1


def test_main_default_workspace_runs(invariants_repo: Path, monkeypatch: pytest.MonkeyPatch):
    # Patch DEFAULT_WORKSPACE_DIR so the default-path branch is exercised
    # against a hermetic temp repo instead of the real working tree.
    monkeypatch.setattr(vi, "DEFAULT_WORKSPACE_DIR", invariants_repo)
    code = vi.main()
    assert code == 0


# --- size_budget_lines (MAX_FILE_LINES override) ---

def test_size_budget_lines_defaults(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("MAX_FILE_LINES", raising=False)
    assert vi.size_budget_lines() == vi.SIZE_BUDGET_LINES


def test_size_budget_lines_honors_env_override(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("MAX_FILE_LINES", "42")
    assert vi.size_budget_lines() == 42


def test_size_budget_lines_ignores_non_integer(monkeypatch: pytest.MonkeyPatch, caplog):
    monkeypatch.setenv("MAX_FILE_LINES", "not-a-number")
    with caplog.at_level(logging.WARNING, logger=vi.logger.name):
        assert vi.size_budget_lines() == vi.SIZE_BUDGET_LINES
    assert "MAX_FILE_LINES" in caplog.text


def test_check_size_budget_uses_env_override(invariants_repo: Path, monkeypatch: pytest.MonkeyPatch):
    (invariants_repo / "medium.py").write_text("\n".join("x = 1" for _ in range(20)) + "\n", encoding="utf-8")
    monkeypatch.setenv("MAX_FILE_LINES", "10")
    assert vi.check_size_budget(invariants_repo) is False
    monkeypatch.setenv("MAX_FILE_LINES", "500")
    assert vi.check_size_budget(invariants_repo) is True


def test_check_protected_paths_warns_when_attested(invariants_repo: Path, monkeypatch: pytest.MonkeyPatch, caplog):
    """An attested protected-path change passes, but must still be logged for the audit trail."""
    mf = invariants_repo / "Makefile"
    mf.write_text("all:\n", encoding="utf-8")
    monkeypatch.setenv("ALLOW_GITHUB_CHANGES", "1")
    with caplog.at_level(logging.WARNING, logger=vi.logger.name):
        assert vi.check_protected_paths(invariants_repo, ["Makefile"]) is True
    assert "attestation" in caplog.text
    assert "Makefile" in caplog.text


def test_git_modified_files_raises_on_git_failure(invariants_repo: Path, monkeypatch: pytest.MonkeyPatch, caplog):
    """INV-6: Inability to inspect git state is fatal and must fail closed (raise)."""
    def broken_check_output(*args, **kwargs):
        raise subprocess.CalledProcessError(1, ["git", "diff"], output="", stderr="git error")

    monkeypatch.setattr(subprocess, "check_output", broken_check_output)
    with caplog.at_level(logging.ERROR, logger=vi.logger.name):
        with pytest.raises(subprocess.CalledProcessError):
            vi.git_modified_files(invariants_repo)
    assert "[FAIL] Could not run" in caplog.text


def test_size_budget_lines_reads_from_policy(invariants_repo: Path, monkeypatch: pytest.MonkeyPatch):
    policy = invariants_policy_path(invariants_repo)
    policy.write_text(json.dumps({"limits": {"size_budget_lines": 350}}), encoding="utf-8")
    monkeypatch.delenv("MAX_FILE_LINES", raising=False)
    assert vi.size_budget_lines(policy) == 350



def test_non_ascii_protected_path_is_not_hidden_by_git_quoting(invariants_repo: Path):
    """A protected file with a non-ASCII name must still trip the gate.

    With git's default `core.quotePath=true`, such a path is reported C-escaped and
    double-quoted (`"a/caf\\303\\251.py"`). The leading quote defeats every anchored
    fnmatch pattern, so the file would sail through as unprotected. This pins the
    `core.quotePath=false` that keeps the name matchable.
    """
    guarded = invariants_repo / ".github" / "workflows"
    guarded.mkdir(parents=True, exist_ok=True)
    target = guarded / "café-ci.yml"
    target.write_text("name: CI\n", encoding="utf-8")

    modified = vi.git_modified_files(invariants_repo)
    # Git on Windows may return NFD (decomposed) form of accented characters,
    # while Python string literals use NFC (composed). Normalize both sides.
    normalized = {unicodedata.normalize("NFC", f) for f in modified}
    expected = unicodedata.normalize("NFC", "café-ci.yml")
    assert any(f.endswith(expected) for f in normalized), (
        f"non-ASCII path came back quoted or escaped: {modified}"
    )
    assert not any(f.startswith('"') for f in modified), "git output is still C-quoted"
    assert vi.check_protected_paths(invariants_repo, [".github/workflows/**"]) is False, (
        "a non-ASCII file inside a protected path evaded the gate"
    )


def test_size_budget_lines_fails_closed_on_malformed_policy(invariants_repo: Path, monkeypatch, caplog):
    """A malformed policy must not silently relax the size gate.

    This previously returned SIZE_BUDGET_LINES via a bare `except Exception`, the
    same fail-open inversion COV_MIN had: the gate lowered itself on exactly the
    input that should stop it.
    """
    monkeypatch.delenv("MAX_FILE_LINES", raising=False)
    policy = invariants_policy_path(invariants_repo)
    policy.write_text("{not json", encoding="utf-8")
    with caplog.at_level(logging.ERROR, logger=vi.logger.name):
        with pytest.raises(SystemExit) as excinfo:
            vi.size_budget_lines(policy)
    assert excinfo.value.code == 1
    assert "Malformed governance policy" in caplog.text


def test_size_budget_lines_uses_default_when_policy_is_absent(tmp_path: Path, monkeypatch):
    """An absent policy is the adopter path; defaults still apply."""
    monkeypatch.delenv("MAX_FILE_LINES", raising=False)
    assert vi.size_budget_lines(tmp_path / "nope.json") == vi.SIZE_BUDGET_LINES


def test_check_size_budget_enforces_the_policy_value_not_the_default(
    invariants_repo: Path, monkeypatch: pytest.MonkeyPatch
):
    """End-to-end probe: the policy number must reach the *gate*, not just the loader.

    The repository's `size_budget_lines` is byte-identical to `SIZE_BUDGET_LINES`,
    so every existing assertion passes whether the policy is read or ignored. A
    deliberately distinguishable budget (7) is the only thing that separates the
    two, and it is what would catch the block being deleted outright.
    """
    monkeypatch.delenv("MAX_FILE_LINES", raising=False)
    policy = invariants_policy_path(invariants_repo)
    policy.write_text(json.dumps({"limits": {"size_budget_lines": 7}}), encoding="utf-8")
    (invariants_repo / "small.py").write_text("x = 1\n" * 5, encoding="utf-8")
    assert vi.check_size_budget(invariants_repo, policy_path=policy) is True
    (invariants_repo / "big.py").write_text("x = 1\n" * 10, encoding="utf-8")
    assert vi.check_size_budget(invariants_repo, policy_path=policy) is False, (
        "a 10-line file passed a 7-line policy budget; the policy is not reaching the gate"
    )


def test_cli_survives_a_bogus_log_level(invariants_repo: Path):
    """LOG_LEVEL=BOGUS previously crashed the gate with ValueError before any check ran.

    Subprocess deliberately: under pytest the root logger already has a handler,
    and `logging.basicConfig` only applies `level` when there is none -- an
    in-process version of this test passes identically with and without the fix.
    The gate runs against its own repository (the CLI takes no --repo-root), so a
    clean tree plus the attestation env is the passing baseline.
    """
    import os
    import subprocess
    import sys

    result = subprocess.run(
        [sys.executable, str(Path(vi.__file__).resolve())],
        env={**os.environ, "LOG_LEVEL": "BOGUS", "ALLOW_GITHUB_CHANGES": "1", "GITHUB_BASE_REF": ""},
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    assert "Unknown level" not in result.stderr


def test_size_budget_lines_fails_closed_on_a_non_object_policy(invariants_repo: Path, monkeypatch):
    """Valid JSON that is not an object previously escaped as a raw AttributeError."""
    monkeypatch.delenv("MAX_FILE_LINES", raising=False)
    policy = invariants_policy_path(invariants_repo)
    policy.write_text("[]", encoding="utf-8")
    with pytest.raises(SystemExit) as excinfo:
        vi.size_budget_lines(policy)
    assert excinfo.value.code == 1


def test_size_budget_lines_fails_closed_on_unreadable_policy(invariants_repo: Path, monkeypatch, caplog):
    """An OSError that is not FileNotFoundError (here: the policy path is a
    directory) is corruption, not the adopter path — it must exit 1, never
    silently fall back to the built-in budget."""
    monkeypatch.delenv("MAX_FILE_LINES", raising=False)
    policy_dir = invariants_repo / "policy-as-a-directory"
    policy_dir.mkdir()
    with caplog.at_level(logging.ERROR, logger=vi.logger.name):
        with pytest.raises(SystemExit) as excinfo:
            vi.size_budget_lines(policy_dir)
    assert excinfo.value.code == 1
    assert "Could not read governance policy" in caplog.text


def test_git_modified_files_includes_pr_diff_when_base_ref_set(invariants_repo: Path, monkeypatch: pytest.MonkeyPatch):
    """With GITHUB_BASE_REF set (a PR build), files committed since the base
    ref must be part of the modified set even when the working tree is clean."""
    subprocess.run(
        ["git", "update-ref", "refs/remotes/origin/main", "HEAD"], cwd=invariants_repo, check=True, capture_output=True
    )
    pr_file = invariants_repo / "pr_change.py"
    pr_file.write_text("x = 1\n", encoding="utf-8")
    subprocess.run(["git", "add", "pr_change.py"], cwd=invariants_repo, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-m", "pr change"], cwd=invariants_repo, check=True, capture_output=True)
    monkeypatch.setenv("GITHUB_BASE_REF", "main")
    assert "pr_change.py" in vi.git_modified_files(invariants_repo)


def test_check_hardcoded_secrets_skips_its_own_module_copy(invariants_repo: Path):
    """A file named validate_invariants.py legitimately names the patterns it
    scans for, so the scanner must exclude it from its own scan."""
    secret_literal = "NVIDIA_" + "API_KEY = 'would-flag-anywhere-else'\n"
    (invariants_repo / "validate_invariants.py").write_text(secret_literal, encoding="utf-8")
    assert vi.check_hardcoded_secrets(invariants_repo) is True


def test_unreadable_file_does_not_abort_secret_or_size_scans(invariants_repo: Path):
    """A .py file that cannot be decoded (invalid UTF-8) is skipped with a
    debug note; it must not abort either scan or fail the gate on its own."""
    (invariants_repo / "binaryish.py").write_bytes(b"\xff\xfe\x00 not utf-8 \xba\xad")
    assert vi.check_hardcoded_secrets(invariants_repo) is True
    assert vi.check_size_budget(invariants_repo, budget=500) is True


# --- test_size_budget_lines / check_test_size_budget (tech-debt-hardening-plan R-TDH-22) ---
#
# Test modules were exempt from the source budget and the exemption grew a
# 923-line module. They now have their own budget, `limits.test_size_budget_lines`,
# enforced by the same gate; ids contain "test_size_budget" so AC-22's
# `-k test_size_budget` selects exactly these.


def test_test_size_budget_lines_reads_from_policy(invariants_repo: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv(vi.TEST_SIZE_BUDGET_ENV, raising=False)
    policy = invariants_policy_path(invariants_repo)
    policy.write_text(json.dumps({"limits": {"test_size_budget_lines": 120}}), encoding="utf-8")
    assert vi.test_size_budget_lines(policy) == 120


def test_test_size_budget_lines_defaults_without_a_policy(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv(vi.TEST_SIZE_BUDGET_ENV, raising=False)
    assert vi.test_size_budget_lines(tmp_path / "absent.json") == vi.TEST_SIZE_BUDGET_LINES


def test_test_size_budget_lines_honors_its_own_env_override(invariants_repo: Path, monkeypatch: pytest.MonkeyPatch):
    """The two budgets have separate overrides: MAX_FILE_LINES must not move the test budget."""
    monkeypatch.setenv(vi.SIZE_BUDGET_ENV, "5")
    monkeypatch.setenv(vi.TEST_SIZE_BUDGET_ENV, "77")
    assert vi.test_size_budget_lines(invariants_policy_path(invariants_repo)) == 77
    assert vi.size_budget_lines(invariants_policy_path(invariants_repo)) == 5


def test_test_size_budget_lines_fails_closed_on_a_malformed_policy(
    invariants_repo: Path, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.delenv(vi.TEST_SIZE_BUDGET_ENV, raising=False)
    policy = invariants_policy_path(invariants_repo)
    policy.write_text(json.dumps({"limits": {"test_size_budget_lines": "many"}}), encoding="utf-8")
    with pytest.raises(SystemExit) as exc:
        vi.test_size_budget_lines(policy)
    assert exc.value.code == 1


def test_check_test_size_budget_fails_one_line_over_and_passes_at_the_budget(invariants_repo: Path, caplog):
    """AC-22: one line over the budget fails; exactly at the budget passes."""
    _write_lines(invariants_repo / "test_wide.py", 51)
    with caplog.at_level(logging.ERROR, logger=vi.logger.name):
        assert vi.check_test_size_budget(invariants_repo, budget=50) is False
    assert "[FAIL] Test Size Budget: File test_wide.py exceeds 50 lines (51 lines)." in caplog.text
    _write_lines(invariants_repo / "test_wide.py", 50)
    assert vi.check_test_size_budget(invariants_repo, budget=50) is True


def test_a_passing_budget_reports_the_closest_file_and_its_headroom(invariants_repo: Path, caplog):
    """The budget was a cliff: silent until it failed, so the first signal was a red gate.

    `test_verify_zero_skips.py` reached 684 of 700 with nothing surfacing it.
    The gauge is INFO-only and cannot change the verdict, so this asserts the
    measurement is reported, not that it gates anything.
    """
    _write_lines(invariants_repo / "test_near.py", 48)
    _write_lines(invariants_repo / "test_small.py", 5)
    with caplog.at_level(logging.INFO, logger="harness.shared"):
        assert vi.check_test_size_budget(invariants_repo, budget=50) is True
    assert "closest is test_near.py at 48 lines (2 to spare)" in caplog.text
    assert "test_small.py" not in caplog.text, "only the closest file is worth a line"


def test_no_headroom_line_when_the_budget_is_breached(invariants_repo: Path, caplog):
    """A failing run must lead with the failure, not bury it under a gauge for the runners-up."""
    _write_lines(invariants_repo / "test_wide.py", 51)
    with caplog.at_level(logging.INFO, logger="harness.shared"):
        assert vi.check_test_size_budget(invariants_repo, budget=50) is False
    assert "to spare" not in caplog.text


def test_check_test_size_budget_ignores_source_modules(invariants_repo: Path):
    """Source files belong to the other budget; counting them here would double-report."""
    _write_lines(invariants_repo / "big_source.py", 600)
    assert vi.check_test_size_budget(invariants_repo, budget=50) is True
    _write_lines(invariants_repo / "wide_test.py", 60)  # the `_test.py` suffix counts as a test module
    assert vi.check_test_size_budget(invariants_repo, budget=50) is False


def test_main_fails_on_an_oversized_test_module_from_policy(invariants_repo: Path, monkeypatch: pytest.MonkeyPatch):
    """End to end through main(): the budget comes from the policy, not a constant."""
    monkeypatch.delenv(vi.TEST_SIZE_BUDGET_ENV, raising=False)
    monkeypatch.delenv(vi.SIZE_BUDGET_ENV, raising=False)
    policy = invariants_policy_path(invariants_repo)
    policy.write_text(
        # Both budgets stated: `main()` reads the source budget too, and since
        # R-CQ-8 a present policy that omits it fails closed before this test's
        # own assertion is reached. 40 stays distinguishable from the built-in
        # 700, which is what makes this a liveness check on the policy value.
        json.dumps(
            {
                "protected_paths": ["Makefile"],
                "limits": {"test_size_budget_lines": 40, "size_budget_lines": 500},
            }
        ),
        encoding="utf-8",
    )
    _write_lines(invariants_repo / "test_over.py", 41)
    assert vi.main(invariants_repo, policy_path=policy) == 1
    _write_lines(invariants_repo / "test_over.py", 40)
    assert vi.main(invariants_repo, policy_path=policy) == 0

