import io
from pathlib import Path
from unittest.mock import MagicMock, PropertyMock, patch

import pytest

from harness.shared.remotes import (
    RemoteParseError,
    check_url,
    current_push_urls,
    load_allowlist,
    main,
    normalize_remote_url,
    parse_allowlist,
)


# --- Test normalize_remote_url() ---
def test_normalize_https_url():
    res = normalize_remote_url("https://github.com/Org/Repo.git")
    assert res.canonical == "github.com/Org/Repo"


def test_normalize_ssh_url():
    res = normalize_remote_url("git@github.com:Org/Repo.git")
    assert res.canonical == "github.com/Org/Repo"


def test_normalize_ssh_scheme_url():
    res = normalize_remote_url("ssh://git@github.com/Org/Repo.git")
    assert res.canonical == "github.com/Org/Repo"


def test_normalize_preserves_path_case():
    res = normalize_remote_url("https://GITHUB.COM/CamelCaseOrg/RepoName.git")
    assert res.canonical == "github.com/CamelCaseOrg/RepoName"


def test_normalize_preserves_significant_port():
    res = normalize_remote_url("ssh://git@github.com:2222/Org/Repo.git")
    assert res.canonical == "github.com:2222/Org/Repo"


def test_normalize_strips_default_port():
    res = normalize_remote_url("https://github.com:443/Org/Repo")
    assert res.canonical == "github.com/Org/Repo"


def test_normalize_empty_url_raises():
    with pytest.raises(RemoteParseError, match="empty remote URL"):
        normalize_remote_url("")


def test_normalize_local_path_raises():
    with pytest.raises(RemoteParseError, match="local/file remotes are not approved"):
        normalize_remote_url("/local/path/repo")


def test_normalize_embedded_password_raises():
    with pytest.raises(RemoteParseError, match="embedded password/token"):
        normalize_remote_url("https://user:password@github.com/Org/Repo.git")


def test_normalize_unparseable_url():
    with patch("harness.shared.remotes.urlsplit", side_effect=ValueError("bad url")):
        with pytest.raises(RemoteParseError, match="unparseable remote URL"):
            normalize_remote_url("https://[")


def test_normalize_invalid_port():
    with patch("urllib.parse.SplitResult.port", new_callable=PropertyMock) as mock_port:
        mock_port.side_effect = ValueError("bad port")
        with pytest.raises(RemoteParseError, match="invalid remote port"):
            normalize_remote_url("https://github.com:abc/repo")


def test_normalize_no_host():
    with pytest.raises(RemoteParseError, match="remote URL has no host"):
        normalize_remote_url("https:///repo")


def test_normalize_no_path():
    with pytest.raises(RemoteParseError, match="remote URL has no repository path"):
        normalize_remote_url("https://github.com/")


# --- Test parse_allowlist() ---
def test_parse_allowlist_valid():
    res = parse_allowlist("github.com/Org/Repo\ngitlab.com:2222/Org/Repo\n")
    assert res == ["github.com/Org/Repo", "gitlab.com:2222/Org/Repo"]


def test_parse_allowlist_ignores_comments():
    res = parse_allowlist("# comment\ngithub.com/Org/Repo\n")
    assert res == ["github.com/Org/Repo"]


def test_parse_allowlist_rejects_urls():
    with pytest.raises(RemoteParseError, match="not a URL"):
        parse_allowlist("https://github.com/Org/Repo")


def test_parse_allowlist_no_path():
    with pytest.raises(RemoteParseError, match="has no repository/owner path"):
        parse_allowlist("github.com")


def test_parse_allowlist_malformed_host():
    with pytest.raises(RemoteParseError, match="is malformed"):
        parse_allowlist("/Repo")
    with pytest.raises(RemoteParseError, match="is malformed"):
        parse_allowlist("github.com/")


def test_parse_allowlist_malformed_ipv6():
    with pytest.raises(RemoteParseError, match="malformed IPv6 host"):
        parse_allowlist("[1234::/Repo")


def test_parse_allowlist_invalid_port():
    with pytest.raises(RemoteParseError, match="invalid port"):
        parse_allowlist("github.com:abc/Repo")


def test_parse_allowlist_wildcard():
    res = parse_allowlist("github.com/Org/*")
    assert res == ["github.com/Org/*"]


# --- Test check_url() ---
def test_check_url_empty_allowlist():
    ok, msg = check_url("https://github.com/Org/Repo", [])
    assert not ok
    assert "allowlist is empty" in msg


def test_check_url_bad_url():
    ok, msg = check_url("bad_url", ["github.com/Org/Repo"])
    assert not ok
    assert "cannot normalize remote URL" in msg


def test_check_url_exact_match():
    ok, msg = check_url("https://github.com/Org/Repo", ["github.com/Org/Repo"])
    assert ok
    assert "exact allowlist match" in msg


def test_check_url_wildcard_match():
    ok, msg = check_url("https://github.com/Org/Repo", ["github.com/Org/*"])
    assert ok
    assert "owner-scoped allowlist match" in msg


def test_check_url_no_match():
    ok, msg = check_url("https://github.com/Org/Repo", ["github.com/Other/Repo"])
    assert not ok
    assert "is not on the allowlist" in msg


# --- Test load_allowlist() ---
def test_load_allowlist(tmp_path):
    f = tmp_path / "allowlist.txt"
    f.write_text("github.com/Org/Repo\n")
    assert load_allowlist(f) == ["github.com/Org/Repo"]


def test_load_allowlist_error(tmp_path):
    f = tmp_path / "missing.txt"
    with pytest.raises(RemoteParseError, match="cannot read/parse allowlist"):
        load_allowlist(f)


# --- Test current_push_urls() ---
@patch("subprocess.run")
def test_current_push_urls(mock_run):
    mock_run.side_effect = [
        MagicMock(stdout="origin\nupstream\n", returncode=0),
        MagicMock(stdout="https://github.com/org/repo\n", returncode=0),
        MagicMock(stdout="https://github.com/upstream/repo\n", returncode=0),
    ]
    res = current_push_urls(Path("."))
    assert res == [("origin", "https://github.com/org/repo"), ("upstream", "https://github.com/upstream/repo")]


@patch("subprocess.run")
def test_current_push_urls_error_enumerating(mock_run):
    mock_run.side_effect = Exception("git failed")
    with pytest.raises(RemoteParseError, match="cannot enumerate git remotes"):
        current_push_urls(Path("."))


@patch("subprocess.run")
def test_current_push_urls_no_remotes(mock_run):
    mock_run.return_value = MagicMock(stdout="", returncode=0)
    with pytest.raises(RemoteParseError, match="repository has no configured remotes"):
        current_push_urls(Path("."))


@patch("subprocess.run")
def test_current_push_urls_fallback(mock_run):
    mock_run.side_effect = [
        MagicMock(stdout="origin\n", returncode=0),
        MagicMock(returncode=1),
        MagicMock(stdout="https://github.com/org/repo\n", returncode=0),
    ]
    res = current_push_urls(Path("."))
    assert res == [("origin", "https://github.com/org/repo")]


@patch("subprocess.run")
def test_current_push_urls_cannot_resolve(mock_run):
    mock_run.side_effect = [
        MagicMock(stdout="origin\n", returncode=0),
        MagicMock(returncode=1),
        MagicMock(returncode=1),
    ]
    with pytest.raises(RemoteParseError, match="cannot resolve push URL for remote origin"):
        current_push_urls(Path("."))


# --- Test main() ---
@patch("sys.stderr", new_callable=io.StringIO)
def test_main_allowlist_error(mock_stderr, tmp_path):
    assert main(["--check-url", "https://github.com/repo", "--allowlist", str(tmp_path / "missing")]) == 1
    assert "BLOCKED: cannot read/parse allowlist" in mock_stderr.getvalue()


@patch("sys.stdout", new_callable=io.StringIO)
def test_main_json_output(mock_stdout, tmp_path):
    f = tmp_path / "allow.txt"
    f.write_text("github.com/repo\n")
    assert main(["--json", "--allowlist", str(f)]) == 0
    assert "github.com/repo" in mock_stdout.getvalue()


@patch("sys.stderr", new_callable=io.StringIO)
def test_main_check_url_blocked(mock_stderr, tmp_path):
    f = tmp_path / "allow.txt"
    f.write_text("github.com/other\n")
    assert main(["--check-url", "https://github.com/repo", "--allowlist", str(f)]) == 1
    assert "BLOCKED" in mock_stderr.getvalue()


@patch("sys.stderr", new_callable=io.StringIO)
def test_main_check_current_remotes_blocked(mock_stderr, tmp_path):
    f = tmp_path / "allow.txt"
    f.write_text("github.com/other\n")
    with patch("harness.shared.remotes.current_push_urls", return_value=[("origin", "https://github.com/repo")]):
        assert main(["--check-current-remotes", "--allowlist", str(f)]) == 1
        assert "BLOCKED: origin: destination github.com/repo is not on the allowlist" in mock_stderr.getvalue()


def test_main_check_current_remotes_allowed(tmp_path):
    f = tmp_path / "allow.txt"
    f.write_text("github.com/repo\n")
    with patch("harness.shared.remotes.current_push_urls", return_value=[("origin", "https://github.com/repo")]):
        assert main(["--check-current-remotes", "--allowlist", str(f)]) == 0
