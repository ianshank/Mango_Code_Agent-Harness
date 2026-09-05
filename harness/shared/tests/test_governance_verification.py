"""Tests for governance/verification: VerificationRunner with mock broker."""

from __future__ import annotations

import os
import shutil
from dataclasses import dataclass
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from harness.shared.governance.verification import (
    DEFAULT_MAKEFILE,
    DEFAULT_TARGET,
    REENTRANCY_ENV,
    VerificationRunner,
)


@dataclass(frozen=True)
class _MockResult:
    """Minimal stand-in for ExecutionResult."""

    status: str
    exit_code: int
    stdout: str = ""
    stderr: str = ""
    reason: str = ""


def _make_broker(*, probe_ok: bool = True, run_ok: bool = True) -> MagicMock:
    """Build a mock broker that returns configurable results."""
    broker = MagicMock()

    def _execute_command(cmd: str, ctx: dict, *, cwd: Path | None = None, timeout: int = 300) -> _MockResult:
        if "-n" in cmd:
            # Dry run (probe)
            if probe_ok:
                return _MockResult(status="SUCCESS", exit_code=0, stdout="python -m pytest\n")
            return _MockResult(status="FAILED", exit_code=2, stderr="No rule")
        if "command -v" in cmd:
            # PATH census
            return _MockResult(status="SUCCESS", exit_code=0, stdout="/usr/bin/pytest\n")
        # Real run
        if run_ok:
            return _MockResult(status="SUCCESS", exit_code=0, stdout="all tests passed\n")
        return _MockResult(status="FAILED", exit_code=1, stderr="test failed\n")

    broker.execute_command = MagicMock(side_effect=_execute_command)
    return broker


def _mock_which(program: str) -> str | None:
    """Pretend make is always on PATH, to decouple from host machine."""
    if program == "make":
        return "/usr/bin/make"
    return shutil.which(program)


class TestVerificationRunner:
    """VerificationRunner exercises probe, run, and reentrancy detection."""

    def test_command_includes_makefile(self) -> None:
        broker = _make_broker()
        runner = VerificationRunner(broker, "verifier")
        assert DEFAULT_MAKEFILE in runner.command
        assert DEFAULT_TARGET in runner.command

    def test_target_property(self) -> None:
        broker = _make_broker()
        runner = VerificationRunner(broker, "verifier", target="custom-target")
        assert runner.target == "custom-target"

    def test_is_reentrant_false_by_default(self) -> None:
        broker = _make_broker()
        runner = VerificationRunner(broker, "verifier")
        assert runner.is_reentrant({}) is False

    def test_is_reentrant_true_when_set(self) -> None:
        broker = _make_broker()
        runner = VerificationRunner(broker, "verifier")
        assert runner.is_reentrant({REENTRANCY_ENV: "1"}) is True

    @patch("shutil.which", side_effect=_mock_which)
    def test_probe_success(self, mock_which: MagicMock, tmp_path: Path) -> None:
        broker = _make_broker(probe_ok=True)
        runner = VerificationRunner(broker, "verifier")
        ok, detail = runner.probe(tmp_path)
        assert ok is True
        assert detail == ""

    @patch("shutil.which", side_effect=_mock_which)
    def test_probe_failure(self, mock_which: MagicMock, tmp_path: Path) -> None:
        broker = _make_broker(probe_ok=False)
        runner = VerificationRunner(broker, "verifier")
        ok, detail = runner.probe(tmp_path)
        assert ok is False
        assert "not a target" in detail

    def test_probe_no_make_installed(self, tmp_path: Path) -> None:
        """On Windows without make, the probe returns a specific message."""
        broker = _make_broker()
        runner = VerificationRunner(broker, "verifier")
        with patch("shutil.which", return_value=None):
            ok, detail = runner.probe(tmp_path)
        assert ok is False
        assert "make is not installed" in detail

    @patch("shutil.which", side_effect=_mock_which)
    def test_run_success(self, mock_which: MagicMock, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv(REENTRANCY_ENV, raising=False)
        broker = _make_broker(probe_ok=True, run_ok=True)
        runner = VerificationRunner(broker, "verifier")
        check = runner.run(tmp_path)
        assert check.status == "SUCCESS"
        assert check.probe_ok is True
        assert check.latency_ms >= 0

    @patch("shutil.which", side_effect=_mock_which)
    def test_run_failure(self, mock_which: MagicMock, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv(REENTRANCY_ENV, raising=False)
        broker = _make_broker(probe_ok=True, run_ok=False)
        runner = VerificationRunner(broker, "verifier")
        check = runner.run(tmp_path)
        assert check.status == "FAILED"
        assert check.probe_ok is True

    @patch("shutil.which", side_effect=_mock_which)
    def test_run_blocked_by_probe(self, mock_which: MagicMock, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv(REENTRANCY_ENV, raising=False)
        broker = _make_broker(probe_ok=False)
        runner = VerificationRunner(broker, "verifier")
        check = runner.run(tmp_path)
        assert check.status == "BLOCKED"
        assert check.probe_ok is False

    @patch("shutil.which", side_effect=_mock_which)
    def test_reentrancy_env_set_during_run(
        self,
        mock_which: MagicMock,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """REENTRANCY_ENV must be set during the actual run and restored after."""
        monkeypatch.delenv(REENTRANCY_ENV, raising=False)
        seen_env: list[str | None] = []

        def _capture_env(cmd: str, ctx: dict, *, cwd: Path | None = None, timeout: int = 300) -> _MockResult:
            if "-n" not in cmd and "command -v" not in cmd:
                seen_env.append(os.environ.get(REENTRANCY_ENV))
            # Probe returns success
            if "-n" in cmd:
                return _MockResult(status="SUCCESS", exit_code=0, stdout="python -m pytest\n")
            if "command -v" in cmd:
                return _MockResult(status="SUCCESS", exit_code=0, stdout="/usr/bin/pytest\n")
            return _MockResult(status="SUCCESS", exit_code=0, stdout="ok\n")

        broker = MagicMock()
        broker.execute_command = MagicMock(side_effect=_capture_env)
        runner = VerificationRunner(broker, "verifier")
        runner.run(tmp_path)
        assert seen_env == ["1"]
        # After run, env should be restored
        assert os.environ.get(REENTRANCY_ENV) is None
