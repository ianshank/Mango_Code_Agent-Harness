"""Tests for harness/shared/validate_invariants.py — protected paths, secrets, size budget."""

import json
import logging
import subprocess
from pathlib import Path

import pytest

from harness.shared import validate_invariants as vi


@pytest.fixture
def temp_repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """An isolated git repo with a governance policy, for invariant testing."""
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init"], cwd=repo, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=repo, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=repo, check=True, capture_output=True)
    shared = repo / "harness" / "shared"
    shared.mkdir(parents=True)
    policy = shared / "governance-policy.json"
    policy.write_text(
        json.dumps({"protected_paths": [".github/workflows/**", "Makefile"]}),
        encoding="utf-8",
    )
    # Baseline commit so git diff has a HEAD to compare against.
    (shared / ".gitkeep").write_text("", encoding="utf-8")
    subprocess.run(["git", "add", "-A"], cwd=repo, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=repo, check=True, capture_output=True)
    monkeypatch.setenv("GITHUB_BASE_REF", "")
    monkeypatch.delenv("ALLOW_GITHUB_CHANGES", raising=False)
    return repo


def _policy_path(repo: Path) -> Path:
    return repo / "harness" / "shared" / "governance-policy.json"


# --- load_protected_patterns ---

def test_load_protected_patterns_reads_policy(temp_repo: Path):
    patterns = vi.load_protected_patterns(_policy_path(temp_repo))
    assert patterns == [".github/workflows/**", "Makefile"]


def test_load_protected_patterns_defaults_when_missing(tmp_path: Path):
    # Non-existent policy path -> fails closed (sys.exit) is the contract,
    # but the default branch returns [".github/**"] only when the key is absent.
    missing = tmp_path / "does-not-exist.json"
    with pytest.raises(SystemExit) as exc_info:
        vi.load_protected_patterns(missing)
    assert exc_info.value.code == 1


# --- git_modified_files ---

def test_git_modified_files_empty_when_clean(temp_repo: Path):
    assert vi.git_modified_files(temp_repo) == set()


def test_git_modified_files_detects_unstaged(temp_repo: Path):
    # git diff --name-only only lists tracked-but-modified files, not untracked ones.
    f = temp_repo / "src.py"
    f.write_text("x = 1\n", encoding="utf-8")
    subprocess.run(["git", "add", "src.py"], cwd=temp_repo, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-m", "add"], cwd=temp_repo, check=True, capture_output=True)
    f.write_text("x = 2\n", encoding="utf-8")  # now tracked-modified
    assert "src.py" in vi.git_modified_files(temp_repo)


def test_git_modified_files_detects_staged(temp_repo: Path):
    f = temp_repo / "src.py"
    f.write_text("x = 1\n", encoding="utf-8")
    subprocess.run(["git", "add", "src.py"], cwd=temp_repo, check=True, capture_output=True)
    assert "src.py" in vi.git_modified_files(temp_repo)


def test_git_modified_files_detects_untracked(temp_repo: Path):
    # Untracked (never staged) files must be caught so a new file in a protected
    # path cannot slip through before being staged (fail-closed).
    (temp_repo / "Makefile").write_text("all:\n", encoding="utf-8")
    assert "Makefile" in vi.git_modified_files(temp_repo)


def test_git_modified_files_ignores_gitignored(temp_repo: Path):
    (temp_repo / ".gitignore").write_text("*.log\n", encoding="utf-8")
    subprocess.run(["git", "add", ".gitignore"], cwd=temp_repo, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-m", "gi"], cwd=temp_repo, check=True, capture_output=True)
    (temp_repo / "noise.log").write_text("noise\n", encoding="utf-8")
    assert "noise.log" not in vi.git_modified_files(temp_repo)


# --- check_protected_paths ---

def test_check_protected_paths_pass_when_clean(temp_repo: Path, caplog):
    with caplog.at_level(logging.INFO, logger=vi.logger.name):
        assert vi.check_protected_paths(temp_repo, [".github/workflows/**", "Makefile"]) is True
    assert "[PASS]" in caplog.text


def test_check_protected_paths_fails_on_protected_change(temp_repo: Path, caplog):
    mf = temp_repo / "Makefile"
    mf.write_text("all:\n", encoding="utf-8")
    subprocess.run(["git", "add", "Makefile"], cwd=temp_repo, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-m", "mk"], cwd=temp_repo, check=True, capture_output=True)
    mf.write_text("all:\nclean:\n", encoding="utf-8")  # tracked-modified protected path
    with caplog.at_level(logging.ERROR, logger=vi.logger.name):
        assert vi.check_protected_paths(temp_repo, [".github/workflows/**", "Makefile"]) is False
    assert "[FAIL]" in caplog.text
    assert "Makefile" in caplog.text


def test_check_protected_paths_allows_with_env(temp_repo: Path):
    mf = temp_repo / "Makefile"
    mf.write_text("all:\n", encoding="utf-8")
    subprocess.run(["git", "add", "Makefile"], cwd=temp_repo, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-m", "mk"], cwd=temp_repo, check=True, capture_output=True)
    mf.write_text("all:\nclean:\n", encoding="utf-8")  # tracked-modified protected path
    import os

    os.environ["ALLOW_GITHUB_CHANGES"] = "1"
    try:
        assert vi.check_protected_paths(temp_repo, ["Makefile"]) is True
    finally:
        del os.environ["ALLOW_GITHUB_CHANGES"]


def test_check_protected_paths_ignores_non_protected(temp_repo: Path):
    (temp_repo / "feature.py").write_text("x = 1\n", encoding="utf-8")
    assert vi.check_protected_paths(temp_repo, [".github/workflows/**", "Makefile"]) is True


# --- check_hardcoded_secrets ---

def test_check_hardcoded_secrets_clean(temp_repo: Path):
    (temp_repo / "app.py").write_text("API_KEY = os.environ.get('X')\n", encoding="utf-8")
    assert vi.check_hardcoded_secrets(temp_repo) is True


def test_check_hardcoded_secrets_detects_literal(temp_repo: Path, caplog):
    # Build the secret literal dynamically so this test file is not itself flagged.
    secret_literal = "NVIDIA_" + "API_KEY = 'nvapi-secret'\n"
    (temp_repo / "leaky.py").write_text(secret_literal, encoding="utf-8")
    with caplog.at_level(logging.ERROR, logger=vi.logger.name):
        assert vi.check_hardcoded_secrets(temp_repo) is False
    assert "[FAIL]" in caplog.text


def test_check_hardcoded_secrets_skips_venv(temp_repo: Path):
    venv_file = temp_repo / ".venv" / "lib" / "x.py"
    venv_file.parent.mkdir(parents=True)
    secret_literal = "NVIDIA_" + "API_KEY = 'leak'\n"
    venv_file.write_text(secret_literal, encoding="utf-8")
    assert vi.check_hardcoded_secrets(temp_repo) is True


# --- check_size_budget ---

def test_check_size_budget_pass(temp_repo: Path):
    (temp_repo / "small.py").write_text("\n".join("x = 1" for _ in range(10)) + "\n", encoding="utf-8")
    assert vi.check_size_budget(temp_repo, budget=500) is True


def test_check_size_budget_fails_over(temp_repo: Path, caplog):
    (temp_repo / "big.py").write_text("\n".join("x = 1" for _ in range(501)) + "\n", encoding="utf-8")
    with caplog.at_level(logging.ERROR, logger=vi.logger.name):
        assert vi.check_size_budget(temp_repo, budget=500) is False
    assert "[FAIL]" in caplog.text


def test_check_size_budget_ignores_tests(temp_repo: Path):
    (temp_repo / "test_big.py").write_text("\n".join("x = 1" for _ in range(600)) + "\n", encoding="utf-8")
    assert vi.check_size_budget(temp_repo, budget=500) is True


# --- main ---

def test_main_passes_on_clean_repo(temp_repo: Path):
    assert vi.main(workspace_dir=temp_repo, policy_path=_policy_path(temp_repo)) == 0


def test_main_fails_on_protected_path_violation(temp_repo: Path):
    mf = temp_repo / "Makefile"
    mf.write_text("all:\n", encoding="utf-8")
    subprocess.run(["git", "add", "Makefile"], cwd=temp_repo, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-m", "mk"], cwd=temp_repo, check=True, capture_output=True)
    mf.write_text("all:\nclean:\n", encoding="utf-8")  # tracked-modified protected path
    assert vi.main(workspace_dir=temp_repo, policy_path=_policy_path(temp_repo)) == 1


def test_main_fails_on_hardcoded_secret(temp_repo: Path):
    secret_literal = "API_SERVER_" + "KEY = 'k'\n"
    (temp_repo / "leaky.py").write_text(secret_literal, encoding="utf-8")
    assert vi.main(workspace_dir=temp_repo, policy_path=_policy_path(temp_repo)) == 1


def test_main_default_workspace_runs(temp_repo: Path, monkeypatch: pytest.MonkeyPatch):
    # Patch DEFAULT_WORKSPACE_DIR so the default-path branch is exercised
    # against a hermetic temp repo instead of the real working tree.
    monkeypatch.setattr(vi, "DEFAULT_WORKSPACE_DIR", temp_repo)
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


def test_check_size_budget_uses_env_override(temp_repo: Path, monkeypatch: pytest.MonkeyPatch):
    (temp_repo / "medium.py").write_text("\n".join("x = 1" for _ in range(20)) + "\n", encoding="utf-8")
    monkeypatch.setenv("MAX_FILE_LINES", "10")
    assert vi.check_size_budget(temp_repo) is False
    monkeypatch.setenv("MAX_FILE_LINES", "500")
    assert vi.check_size_budget(temp_repo) is True


def test_check_protected_paths_warns_when_attested(temp_repo: Path, monkeypatch: pytest.MonkeyPatch, caplog):
    """An attested protected-path change passes, but must still be logged for the audit trail."""
    mf = temp_repo / "Makefile"
    mf.write_text("all:\n", encoding="utf-8")
    monkeypatch.setenv("ALLOW_GITHUB_CHANGES", "1")
    with caplog.at_level(logging.WARNING, logger=vi.logger.name):
        assert vi.check_protected_paths(temp_repo, ["Makefile"]) is True
    assert "attestation" in caplog.text
    assert "Makefile" in caplog.text


def test_git_modified_files_raises_on_git_failure(temp_repo: Path, monkeypatch: pytest.MonkeyPatch, caplog):
    """INV-6: Inability to inspect git state is fatal and must fail closed (raise)."""
    def broken_check_output(*args, **kwargs):
        raise subprocess.CalledProcessError(1, ["git", "diff"], output="", stderr="git error")

    monkeypatch.setattr(subprocess, "check_output", broken_check_output)
    with caplog.at_level(logging.ERROR, logger=vi.logger.name):
        with pytest.raises(subprocess.CalledProcessError):
            vi.git_modified_files(temp_repo)
    assert "[FAIL] Could not run" in caplog.text


def test_size_budget_lines_reads_from_policy(temp_repo: Path, monkeypatch: pytest.MonkeyPatch):
    policy = _policy_path(temp_repo)
    policy.write_text(json.dumps({"limits": {"size_budget_lines": 350}}), encoding="utf-8")
    monkeypatch.delenv("MAX_FILE_LINES", raising=False)
    assert vi.size_budget_lines(policy) == 350

