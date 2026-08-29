"""Tests for enforce_coverage.py (dynamic coverage gate enforcer)."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from harness.shared import enforce_coverage


def test_resolve_policy_path_custom():
    custom = Path("/custom/path/policy.json")
    assert enforce_coverage.resolve_policy_path(custom) == custom


def test_resolve_policy_path_default():
    default_path = enforce_coverage.resolve_policy_path()
    assert default_path.name == "governance-policy.json"
    assert default_path.exists()


def test_load_coverage_threshold_missing_file(tmp_path: Path):
    missing = tmp_path / "missing.json"
    with pytest.raises(FileNotFoundError, match="does not exist"):
        enforce_coverage.load_coverage_threshold(missing)


def test_load_coverage_threshold_bad_json(tmp_path: Path):
    bad = tmp_path / "bad.json"
    bad.write_text("{not-valid-json", encoding="utf-8")
    with pytest.raises(ValueError, match="Failed to parse coverage policy"):
        enforce_coverage.load_coverage_threshold(bad)


def test_load_coverage_threshold_missing_key(tmp_path: Path):
    no_lines = tmp_path / "no_lines.json"
    no_lines.write_text('{"coverage": {}}', encoding="utf-8")
    with pytest.raises(ValueError, match="Missing 'coverage.lines'"):
        enforce_coverage.load_coverage_threshold(no_lines)


def test_load_coverage_threshold_valid(tmp_path: Path):
    valid = tmp_path / "valid.json"
    valid.write_text('{"coverage": {"lines": 88}}', encoding="utf-8")
    assert enforce_coverage.load_coverage_threshold(valid) == 88


def test_main_fails_on_missing_policy(tmp_path: Path, capsys):
    missing = tmp_path / "missing.json"
    assert enforce_coverage.main(policy_path=missing) == 1
    err = capsys.readouterr().err
    assert "does not exist" in err


def test_main_fails_on_bad_policy(tmp_path: Path, capsys):
    bad = tmp_path / "bad.json"
    bad.write_text("invalid json", encoding="utf-8")
    assert enforce_coverage.main(policy_path=bad) == 1
    err = capsys.readouterr().err
    assert "Failed to parse coverage policy" in err


def test_main_runs_pytest_with_injected_cov_flag(tmp_path: Path):
    policy = tmp_path / "policy.json"
    policy.write_text('{"coverage": {"lines": 92}}', encoding="utf-8")

    with patch("subprocess.call", return_value=0) as mock_call:
        code = enforce_coverage.main(argv=["pytest", "tests/"], policy_path=policy)
        assert code == 0
        mock_call.assert_called_once_with(["pytest", "tests/", "--cov-fail-under=92"])


def test_main_defaults_argv(tmp_path: Path):
    policy = tmp_path / "policy.json"
    policy.write_text('{"coverage": {"lines": 90}}', encoding="utf-8")

    with patch("subprocess.call", return_value=0) as mock_call:
        code = enforce_coverage.main(argv=[], policy_path=policy)
        assert code == 0
        mock_call.assert_called_once_with(["python", "-m", "pytest", "--cov-fail-under=90"])


def test_main_handles_keyboard_interrupt(tmp_path: Path):
    policy = tmp_path / "policy.json"
    policy.write_text('{"coverage": {"lines": 90}}', encoding="utf-8")

    with patch("subprocess.call", side_effect=KeyboardInterrupt):
        assert enforce_coverage.main(argv=["pytest"], policy_path=policy) == 1


def test_main_handles_subprocess_error(tmp_path: Path, capsys):
    policy = tmp_path / "policy.json"
    policy.write_text('{"coverage": {"lines": 90}}', encoding="utf-8")

    with patch("subprocess.call", side_effect=OSError("Command not found")):
        assert enforce_coverage.main(argv=["pytest"], policy_path=policy) == 1
    err = capsys.readouterr().err
    assert "Failed to execute coverage command" in err
