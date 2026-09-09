"""Escape corpus: open on ProcessBackend, closed or BLOCKED on Landlock (AC-15).

Each route is asserted in both states so the suite stays green before and after
the isolation backend (R-AEI-16). Network cases use an in-process loopback
listener behind a positive control (R-AEI-17). No skips: a host without bash
is asserted non-success on the process side (INV-2), not a skip marker.
"""

from __future__ import annotations

import ast
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


def _py(script: str) -> str:
    """Interpreter ``-c`` payload. ``ProcessBackend`` still spawns via bash."""
    return f"{shlex.quote(sys.executable)} -c {shlex.quote(script)}"


def _read_outside(path: Path) -> str:
    return _py(f"from pathlib import Path; print(Path({str(path)!r}).read_text(encoding='utf-8'), end='')")


def _write_outside(path: Path) -> str:
    return _py(f"from pathlib import Path; Path({str(path)!r}).write_text('x', encoding='utf-8')")


def _closed_or_blocked(result: ExecutionResult, token: str | None = None) -> None:
    if result.status == BROKER_BLOCKED:
        return
    assert result.status != BROKER_SUCCESS
    if token is not None:
        assert token not in (result.stdout or "")


def _assert_process_side(
    process: ProcessBackend,
    opened: ExecutionResult,
    *,
    open_token: str | None = None,
    open_check: Callable[[ExecutionResult], None] | None = None,
) -> None:
    """SUCCESS iff bash can spawn; otherwise a determination, never a skip."""
    if process.available():
        assert opened.status == BROKER_SUCCESS, opened.reason or opened.stderr
        if open_token is not None:
            assert open_token in opened.stdout
        if open_check is not None:
            open_check(opened)
        return
    assert opened.status != BROKER_SUCCESS


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
    _assert_process_side(
        process,
        opened,
        open_token=open_token,
        open_check=open_check,
    )
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
    opened, closed = _dual(workspace, _read_outside(secret), open_token="SECRET")
    if ProcessBackend().available():
        assert opened.status == BROKER_SUCCESS
    else:
        assert opened.status != BROKER_SUCCESS
    assert closed.status != BROKER_SUCCESS


def test_escape_corpus_outside_write(tmp_path: Path) -> None:
    workspace = tmp_path / "ws"
    workspace.mkdir()
    target = tmp_path / "out" / "pwned.txt"
    target.parent.mkdir()
    command = _write_outside(target)
    process = ProcessBackend()
    opened = process.execute(_request(workspace, command))
    _assert_process_side(process, opened)
    if process.available():
        assert target.read_text(encoding="utf-8") == "x"
        target.unlink()
    else:
        assert not target.exists()
    isolated = LandlockBackend()
    closed = isolated.execute(_request(workspace, command))
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
        _dual(workspace, _py(script), open_token="CONNECTED")
    finally:
        listener.close()


def test_escape_corpus_without_bash_is_asserted_not_skipped(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Missing bash is a determination (INV-2), not a module skip."""
    workspace = tmp_path / "ws"
    workspace.mkdir()
    secret = tmp_path / "out" / "secret.txt"
    secret.parent.mkdir()
    secret.write_text("SECRET\n", encoding="utf-8")

    def _probe(_self: ProcessBackend) -> bool:
        return False

    def _spawn(
        _self: ProcessBackend,
        _command: str,
        _cwd: Path | None,
        _timeout: int,
    ) -> object:
        raise FileNotFoundError(2, "No such file or directory: 'bash'")

    monkeypatch.setattr(ProcessBackend, "_probe", _probe)
    monkeypatch.setattr(ProcessBackend, "_spawn", _spawn)
    opened, closed = _dual(workspace, _read_outside(secret), open_token="SECRET")
    assert opened.status != BROKER_SUCCESS
    assert closed.status != BROKER_SUCCESS


def test_escape_corpus_module_does_not_skip() -> None:
    """AC-15 forbids skipif / skip markers on this module (INV-2)."""
    tree = ast.parse(Path(__file__).read_text(encoding="utf-8"))
    offenders: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Name) and node.id == "POSIX_ONLY":
            offenders.append("POSIX_ONLY")
        if isinstance(node, ast.Attribute) and node.attr in {"skip", "skipif", "xfail"}:
            offenders.append(f"pytest.{node.attr}")
    assert offenders == []
