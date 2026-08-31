"""Tests for governance/process_backend: ProcessBackend, _cap, ExecutionResult."""
from __future__ import annotations

import subprocess
from dataclasses import FrozenInstanceError
from unittest.mock import patch

import pytest

from harness.shared.governance.process_backend import (
    DEFAULT_MAX_OUTPUT_BYTES,
    DEFAULT_TIMEOUT_SEC,
    ExecutionResult,
    ProcessBackend,
    _cap,
)

# -- ExecutionResult ---------------------------------------------------------

class TestExecutionResult:
    """ExecutionResult is frozen and carries the expected fields."""

    def test_success_result(self) -> None:
        r = ExecutionResult(status="SUCCESS", stdout="ok", stderr="", exit_code=0)
        assert r.status == "SUCCESS"
        assert r.exit_code == 0
        assert r.reason == ""

    def test_failed_result(self) -> None:
        r = ExecutionResult(status="FAILED", stdout="", stderr="err", exit_code=1, reason="timeout")
        assert r.status == "FAILED"
        assert r.reason == "timeout"

    def test_frozen(self) -> None:
        r = ExecutionResult(status="SUCCESS", stdout="", stderr="", exit_code=0)
        with pytest.raises(FrozenInstanceError):
            r.status = "FAILED"  # type: ignore[misc]


# -- _cap --------------------------------------------------------------------

class TestCap:
    """Output capping must work on bytes, not characters."""

    def test_short_text_unchanged(self) -> None:
        assert _cap("hello", 100) == "hello"

    def test_truncates_at_byte_limit(self) -> None:
        text = "a" * 200
        result = _cap(text, 50)
        assert len(result.encode("utf-8")) <= 50 + 50  # truncation message adds ~30 chars
        assert "[truncated at 50 bytes]" in result

    def test_multibyte_safe(self) -> None:
        # Each emoji is 4 bytes in UTF-8
        text = "\U0001f600" * 20  # 80 bytes
        result = _cap(text, 10)
        assert "[truncated at 10 bytes]" in result
        # The result should not contain partial characters
        result.encode("utf-8")  # must not raise

    def test_exact_limit_unchanged(self) -> None:
        text = "abc"
        assert _cap(text, 3) == "abc"


# -- Constants ---------------------------------------------------------------

class TestConstants:
    """Module constants must have governance-compatible values."""

    def test_max_output_bytes_positive(self) -> None:
        assert DEFAULT_MAX_OUTPUT_BYTES > 0

    def test_timeout_sec_positive(self) -> None:
        assert DEFAULT_TIMEOUT_SEC > 0


# -- ProcessBackend ----------------------------------------------------------

class TestProcessBackend:
    """ProcessBackend wraps subprocess with timeout, cap, and credential filtering."""

    def test_name_and_version(self) -> None:
        b = ProcessBackend()
        assert b.name == "process"
        assert b.version == "1.0.0"

    def test_available_caches_probe(self) -> None:
        b = ProcessBackend()
        with patch.object(b, "_probe", return_value=True) as mock_probe:
            assert b.available() is True
            assert b.available() is True  # second call should not re-probe
            mock_probe.assert_called_once()

    def test_run_success(self) -> None:
        b = ProcessBackend()
        mock_completed = subprocess.CompletedProcess(
            args=["bash", "-c", "echo hello"], returncode=0,
            stdout="hello\n", stderr="",
        )
        with patch.object(b, "_spawn", return_value=mock_completed):
            result = b.run("echo hello", cwd=None, timeout=10, max_output_bytes=1024)
        assert result.status == "SUCCESS"
        assert "hello" in result.stdout

    def test_run_failure(self) -> None:
        b = ProcessBackend()
        mock_completed = subprocess.CompletedProcess(
            args=["bash", "-c", "false"], returncode=1,
            stdout="", stderr="error\n",
        )
        with patch.object(b, "_spawn", return_value=mock_completed):
            result = b.run("false", cwd=None, timeout=10, max_output_bytes=1024)
        assert result.status == "FAILED"
        assert result.exit_code == 1

    def test_run_timeout(self) -> None:
        b = ProcessBackend()
        with patch.object(b, "_spawn", side_effect=subprocess.TimeoutExpired("cmd", 5)):
            result = b.run("sleep 100", cwd=None, timeout=5, max_output_bytes=1024)
        assert result.status == "FAILED"
        assert "timed out" in result.reason

    def test_run_exception(self) -> None:
        b = ProcessBackend()
        with patch.object(b, "_spawn", side_effect=OSError("not found")):
            result = b.run("missing", cwd=None, timeout=5, max_output_bytes=1024)
        assert result.status == "FAILED"
        assert "not found" in result.reason

    def test_run_caps_output(self) -> None:
        b = ProcessBackend()
        long_output = "x" * 500
        mock_completed = subprocess.CompletedProcess(
            args=[], returncode=0, stdout=long_output, stderr="",
        )
        with patch.object(b, "_spawn", return_value=mock_completed):
            result = b.run("cmd", cwd=None, timeout=10, max_output_bytes=100)
        assert "[truncated at 100 bytes]" in result.stdout
