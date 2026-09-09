"""Shared ``ExecutionRequest`` construction for isolation tests (C-AEI-2).

Timeout and output caps come from ``ProcessBackend`` defaults, which read
``orchestrator.tool_timeout_sec`` and ``orchestrator.max_output_bytes``. A
per-test literal here would be the unlinked threshold R-TDH-16 forbids.
"""

from __future__ import annotations

from pathlib import Path

from harness.shared.governance.execution_backend import ExecutionRequest
from harness.shared.governance.process_backend import DEFAULT_MAX_OUTPUT_BYTES, DEFAULT_TIMEOUT_SEC

TEST_EXECUTE_ACTION = "test_execute"


def isolation_request(
    workspace: Path | None,
    command: str,
    cwd: Path | None = None,
) -> ExecutionRequest:
    """Build a request with policy-sourced timeout and output cap."""
    return ExecutionRequest(
        command=command,
        workspace=workspace,
        cwd=cwd if cwd is not None else workspace,
        timeout=DEFAULT_TIMEOUT_SEC,
        max_output_bytes=DEFAULT_MAX_OUTPUT_BYTES,
        action=TEST_EXECUTE_ACTION,
    )
