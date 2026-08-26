import os
import tempfile
from pathlib import Path
from unittest import mock

import pytest

from harness.shared.validate_invariants import main


@pytest.fixture
def mock_workspace():
    with tempfile.TemporaryDirectory() as td:
        workspace = Path(td)
        gov_dir = workspace / "harness" / "shared"
        gov_dir.mkdir(parents=True)
        gov_policy_path = gov_dir / "governance-policy.json"
        gov_policy_path.write_text('{"protected_paths": [".github/**"]}', encoding="utf-8")
        yield workspace


class ExitException(Exception):
    pass



@mock.patch("harness.shared.validate_invariants.subprocess.check_output")
@mock.patch("harness.shared.validate_invariants.Path")
@mock.patch("harness.shared.validate_invariants.sys.exit")
def test_main_passes_with_no_issues(mock_exit, mock_path, mock_check_output, mock_workspace):
    mock_exit.side_effect = ExitException
    mock_path.return_value.resolve.return_value.parent.parent.parent = mock_workspace
    mock_check_output.return_value = ""
    os.environ["MAX_FILE_LINES"] = "500"

    with pytest.raises(ExitException):
        main()

    mock_exit.assert_called_with(0)


@mock.patch("harness.shared.validate_invariants.subprocess.check_output")
@mock.patch("harness.shared.validate_invariants.Path")
@mock.patch("harness.shared.validate_invariants.sys.exit")
def test_main_fails_on_protected_path_modification(mock_exit, mock_path, mock_check_output, mock_workspace):
    mock_exit.side_effect = ExitException
    mock_path.return_value.resolve.return_value.parent.parent.parent = mock_workspace
    # Simulate a protected file being modified
    mock_check_output.return_value = ".github/workflows/ci.yml\n"
    os.environ["ALLOW_GITHUB_CHANGES"] = "0"
    os.environ["MAX_FILE_LINES"] = "500"

    with pytest.raises(ExitException):
        main()

    mock_exit.assert_called_with(1)


@mock.patch("harness.shared.validate_invariants.subprocess.check_output")
@mock.patch("harness.shared.validate_invariants.Path")
@mock.patch("harness.shared.validate_invariants.sys.exit")
def test_main_passes_with_protected_path_and_allow_env(mock_exit, mock_path, mock_check_output, mock_workspace):
    mock_exit.side_effect = ExitException
    mock_path.return_value.resolve.return_value.parent.parent.parent = mock_workspace
    mock_check_output.return_value = ".github/workflows/ci.yml\n"
    os.environ["ALLOW_GITHUB_CHANGES"] = "1"
    os.environ["MAX_FILE_LINES"] = "500"

    with pytest.raises(ExitException):
        main()

    mock_exit.assert_called_with(0)


@mock.patch("harness.shared.validate_invariants.subprocess.check_output")
@mock.patch("harness.shared.validate_invariants.Path")
@mock.patch("harness.shared.validate_invariants.sys.exit")
def test_main_fails_on_hardcoded_secret(mock_exit, mock_path, mock_check_output, mock_workspace):
    mock_exit.side_effect = ExitException
    mock_path.return_value.resolve.return_value.parent.parent.parent = mock_workspace
    mock_check_output.return_value = ""
    os.environ["MAX_FILE_LINES"] = "500"

    bad_file = mock_workspace / "bad_file.py"
    bad_file.write_text('OPENAI_API_KEY = "s' + 'k-1234"', encoding="utf-8")

    with pytest.raises(ExitException):
        main()

    mock_exit.assert_called_with(1)


@mock.patch("harness.shared.validate_invariants.subprocess.check_output")
@mock.patch("harness.shared.validate_invariants.Path")
@mock.patch("harness.shared.validate_invariants.sys.exit")
def test_main_fails_on_size_budget_exceeded(mock_exit, mock_path, mock_check_output, mock_workspace):
    mock_exit.side_effect = ExitException
    mock_path.return_value.resolve.return_value.parent.parent.parent = mock_workspace
    mock_check_output.return_value = ""
    os.environ["MAX_FILE_LINES"] = "10"

    big_file = mock_workspace / "big_file.py"
    big_file.write_text("\n".join([f"print({i})" for i in range(15)]), encoding="utf-8")

    with pytest.raises(ExitException):
        main()

    mock_exit.assert_called_with(1)


@mock.patch("harness.shared.validate_invariants.subprocess.check_output")
@mock.patch("harness.shared.validate_invariants.Path")
@mock.patch("harness.shared.validate_invariants.sys.exit")
def test_main_fails_on_missing_policy(mock_exit, mock_path, mock_check_output, mock_workspace):
    mock_exit.side_effect = ExitException
    mock_path.return_value.resolve.return_value.parent.parent.parent = mock_workspace
    mock_check_output.return_value = ""

    # Delete policy to simulate error
    (mock_workspace / "harness" / "shared" / "governance-policy.json").unlink()

    with pytest.raises(ExitException):
        main()

    mock_exit.assert_called_with(1)
