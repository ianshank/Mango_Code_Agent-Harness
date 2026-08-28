import io
import json
import os
import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from harness.shared.pretooluse_guard import (
    DANGER,
    UNMODELED,
    destinations,
    main,
    segments,
)


# --- Test segments() ---
def test_segments_simple_command():
    cmd = "git push origin main"
    res = segments(cmd)
    assert res == [["git", "push", "origin", "main"]]


def test_segments_piped_command():
    cmd = "echo foo | grep bar && ls ; pwd"
    res = segments(cmd)
    assert res == [["echo", "foo"], ["grep", "bar"], ["ls"], ["pwd"]]


def test_segments_empty_command():
    assert segments("") == []
    assert segments("   ") == []


def test_segments_quoted_semicolons():
    cmd = "git commit -m 'feat: add stuff; fix bugs'"
    res = segments(cmd)
    assert res == [["git", "commit", "-m", "feat: add stuff; fix bugs"]]


# --- Test destinations() and effective_remote() ---
def test_destinations_explicit_remote(tmp_git_repo: Path):
    subprocess.run(
        ["git", "-C", str(tmp_git_repo), "remote", "add", "origin", "https://github.com/org/repo.git"], check=True
    )
    seg = ["git", "push", "origin", "main"]
    res = destinations(tmp_git_repo, seg)
    assert res == ["https://github.com/org/repo.git"]


def test_destinations_url_remote(tmp_git_repo: Path):
    seg = ["git", "push", "https://github.com/org/repo.git", "main"]
    res = destinations(tmp_git_repo, seg)
    assert res == ["https://github.com/org/repo.git"]


def test_destinations_scp_remote(tmp_git_repo: Path):
    seg = ["git", "push", "git@github.com:org/repo.git", "main"]
    res = destinations(tmp_git_repo, seg)
    assert res == ["git@github.com:org/repo.git"]


def test_destinations_config_injection_blocked(tmp_git_repo: Path):
    seg_explicit = ["git", "push", "--config-env", "foo", "origin", "main"]
    with pytest.raises(ValueError, match="environment/config injection"):
        destinations(tmp_git_repo, seg_explicit)

    seg_env = ["git", "GIT_CONFIG_COUNT=1", "push"]
    with pytest.raises(ValueError, match="environment/config injection"):
        destinations(tmp_git_repo, seg_env)


def test_destinations_skips_git_options(tmp_git_repo: Path):
    subprocess.run(
        ["git", "-C", str(tmp_git_repo), "remote", "add", "origin", "https://github.com/org/repo.git"], check=True
    )
    seg = [
        "git",
        "-C",
        "/some/path",
        "--git-dir",
        ".git",
        "--work-tree",
        ".",
        "-c",
        "http.sslVerify=false",
        "push",
        "origin",
        "main",
    ]
    res = destinations(tmp_git_repo, seg)
    assert res == ["https://github.com/org/repo.git"]


def test_destinations_repo_flags(tmp_git_repo: Path):
    subprocess.run(
        ["git", "-C", str(tmp_git_repo), "remote", "add", "origin", "https://github.com/org/repo.git"], check=True
    )
    seg = ["git", "push", "--repo=origin", "main"]
    assert destinations(tmp_git_repo, seg) == ["https://github.com/org/repo.git"]
    seg2 = ["git", "push", "--repo", "origin", "main"]
    assert destinations(tmp_git_repo, seg2) == ["https://github.com/org/repo.git"]


def test_destinations_repo_missing_value(tmp_git_repo: Path):
    seg = ["git", "push", "--repo"]
    with pytest.raises(ValueError, match="--repo has no value"):
        destinations(tmp_git_repo, seg)

    seg2 = ["git", "push", "--push-option"]
    with pytest.raises(ValueError, match="--push-option has no value"):
        destinations(tmp_git_repo, seg2)


def test_effective_remote_fallback(tmp_git_repo: Path):
    subprocess.run(
        ["git", "-C", str(tmp_git_repo), "remote", "add", "upstream", "https://github.com/org/repo2.git"], check=True
    )
    # Configure branch main to push to upstream
    subprocess.run(["git", "-C", str(tmp_git_repo), "checkout", "-b", "main"], check=True)
    subprocess.run(["git", "-C", str(tmp_git_repo), "config", "branch.main.pushRemote", "upstream"], check=True)

    seg = ["git", "push"]
    res = destinations(tmp_git_repo, seg)
    assert res == ["https://github.com/org/repo2.git"]


def test_effective_remote_pushDefault(tmp_git_repo: Path):
    subprocess.run(
        ["git", "-C", str(tmp_git_repo), "remote", "add", "upstream", "https://github.com/org/repo2.git"], check=True
    )
    subprocess.run(["git", "-C", str(tmp_git_repo), "config", "remote.pushDefault", "upstream"], check=True)
    seg = ["git", "push"]
    res = destinations(tmp_git_repo, seg)
    assert res == ["https://github.com/org/repo2.git"]


def test_effective_remote_not_found(tmp_git_repo: Path):
    seg = ["git", "push"]
    with pytest.raises(ValueError, match="cannot resolve effective remote"):
        destinations(tmp_git_repo, seg)


def test_effective_remote_prefers_origin_among_many(tmp_git_repo: Path):
    """With no push config and several remotes, 'origin' wins."""
    subprocess.run(
        ["git", "-C", str(tmp_git_repo), "remote", "add", "origin", "https://github.com/org/repo.git"], check=True
    )
    subprocess.run(
        ["git", "-C", str(tmp_git_repo), "remote", "add", "mirror", "https://github.com/org/mirror.git"], check=True
    )
    assert destinations(tmp_git_repo, ["git", "push"]) == ["https://github.com/org/repo.git"]


def test_effective_remote_single_non_origin_remote(tmp_git_repo: Path):
    """A repository with exactly one remote (not named origin) pushes there."""
    subprocess.run(
        ["git", "-C", str(tmp_git_repo), "remote", "add", "upstream", "https://github.com/org/only.git"], check=True
    )
    assert destinations(tmp_git_repo, ["git", "push"]) == ["https://github.com/org/only.git"]


def test_destinations_non_git_segment_is_ignored(tmp_git_repo: Path):
    assert destinations(tmp_git_repo, ["ls", "-la"]) == []


def test_destinations_inline_C_and_c_options(tmp_git_repo: Path):
    """Attached-value forms (-C/path, -chttp.x=y) advance one token, not two."""
    subprocess.run(
        ["git", "-C", str(tmp_git_repo), "remote", "add", "origin", "https://github.com/org/repo.git"], check=True
    )
    seg = ["git", "-C/some/path", "-chttp.sslVerify=false", "push", "origin", "main"]
    assert destinations(tmp_git_repo, seg) == ["https://github.com/org/repo.git"]


def test_destinations_other_dashed_global_option(tmp_git_repo: Path):
    subprocess.run(
        ["git", "-C", str(tmp_git_repo), "remote", "add", "origin", "https://github.com/org/repo.git"], check=True
    )
    seg = ["git", "--no-pager", "push", "origin", "main"]
    assert destinations(tmp_git_repo, seg) == ["https://github.com/org/repo.git"]


def test_destinations_non_push_git_subcommand(tmp_git_repo: Path):
    assert destinations(tmp_git_repo, ["git", "commit", "-m", "x"]) == []


def test_destinations_git_with_only_options_and_no_push(tmp_git_repo: Path):
    assert destinations(tmp_git_repo, ["git", "-c", "a=b"]) == []


def test_destinations_double_dash_falls_back_to_effective_remote(tmp_git_repo: Path):
    """`git push -- main` names no repo before `--`, so the configured
    effective remote is the destination."""
    subprocess.run(
        ["git", "-C", str(tmp_git_repo), "remote", "add", "origin", "https://github.com/org/repo.git"], check=True
    )
    seg = ["git", "push", "--", "main"]
    assert destinations(tmp_git_repo, seg) == ["https://github.com/org/repo.git"]


def test_destinations_value_taking_push_option_is_skipped(tmp_git_repo: Path):
    subprocess.run(
        ["git", "-C", str(tmp_git_repo), "remote", "add", "origin", "https://github.com/org/repo.git"], check=True
    )
    seg = ["git", "push", "-o", "ci.skip", "origin", "main"]
    assert destinations(tmp_git_repo, seg) == ["https://github.com/org/repo.git"]


def test_destinations_unresolvable_named_remote_raises(tmp_git_repo: Path):
    with pytest.raises(ValueError, match="cannot resolve URL for remote nosuch"):
        destinations(tmp_git_repo, ["git", "push", "nosuch", "main"])


def test_governance_module_main_dispatch_leg(monkeypatch):
    """The governance module's own `__main__` leg (not the shim's): a benign
    command must exit 0 through the same dispatch a direct
    `python harness/shared/governance/pretooluse_guard.py` run uses."""
    import runpy
    import sys

    import harness.shared.governance.pretooluse_guard as guard_module

    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps({"tool_input": {"command": "git status"}})))
    with pytest.raises(SystemExit) as exc:
        runpy.run_path(guard_module.__file__, run_name="__main__")
    assert exc.value.code == 0


# --- Test Regex Filters (DANGER / UNMODELED) ---
def test_block_dangerous_rm():
    assert bool(DANGER.search("git push origin main")) is True
    assert bool(DANGER.search("git -c http.sslVerify=false push origin main")) is True


def test_block_public_repo_creation():
    assert bool(DANGER.search("gh repo create my-repo --public")) is True
    assert bool(DANGER.search("gh repo create my-repo --private")) is False


def test_allow_safe_git_status():
    assert bool(DANGER.search("git status")) is False
    assert bool(DANGER.search("git log")) is False
    assert bool(DANGER.search("ls -la")) is False


def test_unmodeled_command_blocked():
    assert bool(UNMODELED.search("git push origin `echo main`")) is True
    assert bool(UNMODELED.search("git push origin $(branch)")) is True
    assert bool(UNMODELED.search("GIT_CONFIG_COUNT=1 git push")) is True
    assert bool(UNMODELED.search("git push origin main")) is False


# --- Test main() execution ---
@patch("sys.stdin", new_callable=io.StringIO)
@patch("sys.stderr", new_callable=io.StringIO)
def test_main_invalid_json_with_danger(mock_stderr, mock_stdin):
    mock_stdin.write("some garbage git push origin main")
    mock_stdin.seek(0)
    assert main() == 2
    assert "unanalyzable payload" in mock_stderr.getvalue()


@patch("sys.stdin", new_callable=io.StringIO)
@patch("sys.stderr", new_callable=io.StringIO)
def test_main_invalid_json_safe(mock_stderr, mock_stdin):
    mock_stdin.write("some garbage git status")
    mock_stdin.seek(0)
    assert main() == 0


@patch("sys.stdin", new_callable=io.StringIO)
@patch("sys.stderr", new_callable=io.StringIO)
def test_main_public_repo_creation(mock_stderr, mock_stdin):
    mock_stdin.write(json.dumps({"tool_input": {"command": "gh repo create --public"}}))
    mock_stdin.seek(0)
    assert main() == 2
    assert "public repository creation requires explicit human approval" in mock_stderr.getvalue()


@patch("sys.stdin", new_callable=io.StringIO)
@patch("sys.stderr", new_callable=io.StringIO)
def test_main_unmodeled_blocked(mock_stderr, mock_stdin):
    mock_stdin.write(json.dumps({"tool_input": {"command": "git push origin `main`"}}))
    mock_stdin.seek(0)
    assert main() == 2
    assert "uses an unmodeled shell" in mock_stderr.getvalue()


@patch("sys.stdin", new_callable=io.StringIO)
@patch("sys.stderr", new_callable=io.StringIO)
def test_main_unparseable_command(mock_stderr, mock_stdin):
    mock_stdin.write(json.dumps({"tool_input": {"command": "git push origin 'openquote"}}))
    mock_stdin.seek(0)
    assert main() == 2
    assert "cannot tokenize dangerous command" in mock_stderr.getvalue()


@patch("sys.stdin", new_callable=io.StringIO)
@patch("sys.stderr", new_callable=io.StringIO)
def test_main_destinations_error(mock_stderr, mock_stdin, tmp_git_repo):
    with patch.dict(os.environ, {"CLAUDE_PROJECT_DIR": str(tmp_git_repo)}):
        mock_stdin.write(json.dumps({"tool_input": {"command": "git push --repo"}}))
        mock_stdin.seek(0)
        assert main() == 2
        assert "--repo has no value" in mock_stderr.getvalue()


@patch("sys.stdin", new_callable=io.StringIO)
@patch("sys.stderr", new_callable=io.StringIO)
def test_main_unknown_segment(mock_stderr, mock_stdin, tmp_git_repo):
    with patch.dict(os.environ, {"CLAUDE_PROJECT_DIR": str(tmp_git_repo)}):
        mock_stdin.write(json.dumps({"tool_input": {"command": "git log ; git push origin main"}}))
        mock_stdin.seek(0)
        with patch("harness.shared.governance.pretooluse_guard.destinations", return_value=[]):
            assert main() == 2
            assert "dangerous-shaped segment could not be attributed" in mock_stderr.getvalue()


@patch("sys.stdin", new_callable=io.StringIO)
@patch("subprocess.run")
def test_main_remote_allowed(mock_run, mock_stdin, tmp_git_repo):
    mock_run.return_value = MagicMock(returncode=0)
    with patch.dict(os.environ, {"CLAUDE_PROJECT_DIR": str(tmp_git_repo)}):
        mock_stdin.write(json.dumps({"tool_input": {"command": "git push origin main"}}))
        mock_stdin.seek(0)
        with patch("harness.shared.governance.pretooluse_guard.destinations", return_value=["https://github.com/org/repo.git"]):
            assert main() == 0


@patch("sys.stdin", new_callable=io.StringIO)
@patch("subprocess.run")
@patch("sys.stderr", new_callable=io.StringIO)
def test_main_remote_blocked(mock_stderr, mock_run, mock_stdin, tmp_git_repo):
    mock_run.return_value = MagicMock(returncode=2)
    with patch.dict(os.environ, {"CLAUDE_PROJECT_DIR": str(tmp_git_repo)}):
        mock_stdin.write(json.dumps({"tool_input": {"command": "git push origin main"}}))
        mock_stdin.seek(0)
        with patch("harness.shared.governance.pretooluse_guard.destinations", return_value=["https://github.com/org/repo.git"]):
            assert main() == 2
