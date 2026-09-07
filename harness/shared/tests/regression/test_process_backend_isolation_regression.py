"""AQA-006: Regression pin for ProcessBackend xdist isolation defect (RCA-7).

When pytest-xdist runs broker tests in parallel, the ProcessBackend._probed
instance-level cache can become contaminated by a real bash probe timeout
on Windows, causing subsequent tests to receive BLOCKED results even when
they provide a RecordingBackend.

This regression pin verifies:
1. RecordingBackend overrides _probe() to always return True (no real bash call)
2. A RecordingBackend-based broker reports SUCCESS for permitted commands
   even when bash is absent from PATH

Spec: INV-9 (fail-closed only on *real* unavailability), RCA-7.
"""

from __future__ import annotations

import subprocess
import sys
import typing
from pathlib import Path
from unittest.mock import patch

import pytest

from harness.shared.governance.broker import ExecutionBroker, ProcessBackend
from harness.shared.governance.process_backend import ProcessBackend as _PB


class _MinimalRecordingBackend(ProcessBackend):
    """Minimal recording backend without _probe override — used to assert the defect pattern."""

    def __init__(self) -> None:
        super().__init__()
        self.spawned: list[str] = []

    def _spawn(self, command: str, cwd: Path | None, timeout: int) -> typing.Any:
        self.spawned.append(command)
        return subprocess.CompletedProcess(args=command, returncode=0, stdout="ok", stderr="")


class _FixedRecordingBackend(_MinimalRecordingBackend):
    """Recording backend with _probe() fixed to return True unconditionally."""

    def _probe(self) -> bool:
        return True


def test_recording_backend_with_probe_override_is_always_available() -> None:
    """RecordingBackend._probe() must return True without invoking bash (RCA-7 fix)."""
    backend = _FixedRecordingBackend()
    assert backend.available() is True, (
        "RecordingBackend.available() returned False. "
        "_probe() must be overridden to return True so no bash process is spawned."
    )


def test_recording_backend_without_probe_override_may_fail_on_windows() -> None:
    """Document the pre-fix defect: a recording backend without _probe override
    will probe bash, which may not exist on Windows (informational only — not a FAIL gate)."""
    if sys.platform != "win32":
        pytest.skip("This defect only manifests on Windows without bash in PATH")

    import shutil

    if shutil.which("bash") is not None:
        pytest.skip("bash is present in PATH; defect does not manifest")

    backend = _MinimalRecordingBackend()
    # Without bash, _probe returns False → available() returns False
    # This is the defect: a broker using this backend will BLOCK all commands
    result = backend.available()
    # We assert False here only to document the defect. If this ever fails
    # (bash is present), the _FixedRecordingBackend is equally safe.
    assert result is False, (
        "Expected _probe() to return False on Windows without bash "
        "(pre-fix defect reproduction)"
    )


def test_broker_with_fixed_backend_reports_success_on_permitted_command() -> None:
    """With _probe overridden to True, the broker correctly reaches the backend
    for a permitted command even on Windows without bash (RCA-7 regression gate)."""
    backend = _FixedRecordingBackend()
    broker = ExecutionBroker(backend=backend)
    result = broker.execute_command("pytest -q", {"agent_id": "implementer"})
    assert result.status == "SUCCESS", (
        f"Broker returned {result.status!r} instead of SUCCESS. "
        "RecordingBackend._probe must return True to prevent bash availability "
        "from leaking into test assertions (RCA-7)."
    )
    assert "pytest -q" in backend.spawned


def test_recording_backend_probe_override_does_not_invoke_subprocess() -> None:
    """_probe() override must not call subprocess.run (no real process spawned)."""
    backend = _FixedRecordingBackend()
    with patch("subprocess.run", side_effect=AssertionError("subprocess.run was called")) as mock_run:
        result = backend._probe()
    assert result is True
    mock_run.assert_not_called()


def test_process_backend_probe_caching_is_per_instance() -> None:
    """Each ProcessBackend instance has its own _probed cache.
    A True result on one instance must not bleed into a fresh instance."""
    backend_a = _FixedRecordingBackend()
    _ = backend_a.available()  # cache True on instance A

    backend_b = _MinimalRecordingBackend()
    # backend_b._probed should be None (uncached), not True from backend_a
    assert backend_b._probed is None, (
        "ProcessBackend._probed is shared across instances. "
        "The cache must be per-instance (instance attribute, not class attribute)."
    )
