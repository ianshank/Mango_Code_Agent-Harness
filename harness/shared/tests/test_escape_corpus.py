"""Escape corpus: open on ProcessBackend, closed or BLOCKED on Landlock (AC-15).

Each route is asserted in both states so the suite stays green before and after
the isolation backend (R-AEI-16). Network cases use an in-process loopback
listener behind a positive control (R-AEI-17). No skips.
"""

from __future__ import annotations

import shlex
import socket
import sys
from collections.abc import Callable
from pathlib import Path

import pytest

from harness.shared.governance.execution_backend import ExecutionRequest, ExecutionResult
from harness.shared.governance.landlock_backend import LandlockBackend
from harness.shared.governance.process_backend import ProcessBackend
from harness.shared.governance.verdict import BROKER_BLOCKED, BROKER_SUCCESS

pytestmark = pytest.mark.security


def _request(workspace: Path, command: str) -> ExecutionRequest:
    return ExecutionRequest(
        command=command,
        workspace=workspace,
        cwd=workspace,
        timeout=8,
        max_output_bytes=4096,
        action="test_execute",
    )


def _closed_or_blocked(result: ExecutionResult, token: str | None = None) -> None:
    if result.status == BROKER_BLOCKED:
        return
    assert result.status != BROKER_SUCCESS
    if token is not None:
        assert token not in (result.stdout or "")


def _dual(
    workspace: Path,
    command: str,
    *,
    open_token: str | None = None,
    closed_token: str | None = None,
    open_check: Callable[[ExecutionResult], None] | None = None,
) -> tuple[ExecutionResult, ExecutionResult]:
    process = ProcessBackend()
    opened = process.execute(_request(workspace, command))
    assert opened.status == BROKER_SUCCESS, opened.reason or opened.stderr
    if open_token is not None:
        assert open_token in opened.stdout
    if open_check is not None:
        open_check(opened)
    isolated = LandlockBackend()
    closed = isolated.execute(_request(workspace, command))
    _closed_or_blocked(closed, closed_token if closed_token is not None else open_token)
    return opened, closed


def test_escape_corpus_outside_read(tmp_path: Path) -> None:
    workspace = tmp_path / "ws"
    workspace.mkdir()
    secret = tmp_path / "out" / "secret.txt"
    secret.parent.mkdir()
    secret.write_text("SECRET\n", encoding="utf-8")
    opened, closed = _dual(workspace, f"cat {shlex.quote(str(secret))}", open_token="SECRET")
    assert opened.status == BROKER_SUCCESS
    assert closed.status != BROKER_SUCCESS


def test_escape_corpus_outside_write(tmp_path: Path) -> None:
    workspace = tmp_path / "ws"
    workspace.mkdir()
    target = tmp_path / "out" / "pwned.txt"
    target.parent.mkdir()
    process = ProcessBackend()
    opened = process.execute(_request(workspace, f"printf x > {shlex.quote(str(target))}"))
    assert opened.status == BROKER_SUCCESS, opened.stderr
    assert target.read_text(encoding="utf-8") == "x"
    target.unlink()
    isolated = LandlockBackend()
    closed = isolated.execute(_request(workspace, f"printf x > {shlex.quote(str(target))}"))
    _closed_or_blocked(closed)
    assert not target.exists()


@pytest.mark.enable_socket
def test_escape_corpus_tcp_connect(tmp_path: Path) -> None:
    workspace = tmp_path / "ws"
    workspace.mkdir()
    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    listener.bind(("127.0.0.1", 0))
    listener.listen(5)
    port = listener.getsockname()[1]
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=1) as control:
            assert control.fileno() >= 0
        script = (
            "import socket; "
            f"s=socket.create_connection(('127.0.0.1', {port}), timeout=2); "
            "s.close(); print('CONNECTED')"
        )
        command = f"{shlex.quote(sys.executable)} -c {shlex.quote(script)}"
        _dual(workspace, command, open_token="CONNECTED")
    finally:
        listener.close()
