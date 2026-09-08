"""Tests for MCP server lifecycle, transport, and execution isolation."""

from __future__ import annotations

import asyncio
import contextlib
import sys
import threading
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

import harness.shared.mcp_server as mcp_mod
from harness.shared.governance.broker import ExecutionBroker
from harness.shared.mcp_server import create_mcp_server, run_mcp_server
from harness.shared.policy_loader import orchestrator_defaults
from harness.shared.tests._mcp_helpers import make_mock_broker, setup_mock_mcp

# No socket exemption here on Linux CI. The asyncio event loop these tests
# drive needs a unix socketpair (its self-pipe), which `--allow-unix-socket` in
# addopts permits; the module-wide `enable_socket` that stood here re-opened
# TCP for every test in the file for a need that was never TCP (audit M12).
#
# Windows portability note (DEC-062): on Windows Python builds without AF_UNIX,
# Python's asyncio self-pipe falls back to a loopback TCP socketpair. The
# SelectorEventLoop uses the same fallback. `enable_socket` is enabled below
# *only on win32* so the self-pipe can be established; it does not affect
# Linux CI where AF_UNIX is always available and the TCP floor holds.
if sys.platform == "win32":
    pytestmark = pytest.mark.enable_socket


@pytest.fixture(autouse=True)
def ensure_mock_mcp(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    setup_mock_mcp(monkeypatch, tmp_path)


@pytest.fixture
def broker() -> ExecutionBroker:
    return make_mock_broker()


def test_create_mcp_server_missing_package(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Test create_mcp_server raises ImportError when mcp is unavailable."""
    monkeypatch.setattr(mcp_mod, "MCP_AVAILABLE", False)
    with pytest.raises(ImportError, match="The 'mcp' package is required"):
        create_mcp_server(tmp_path)


def test_import_failure_sets_mcp_unavailable(monkeypatch: pytest.MonkeyPatch) -> None:
    """The real try/except ImportError guard (not a monkeypatched flag) must leave the
    module in a safe, fully-None state when `mcp` cannot be imported -- this is the
    Python 3.9 CI leg's actual code path, otherwise untested.

    Loads a throwaway copy of mcp_server.py under a private module name via
    importlib.util, rather than deleting/reimporting `sys.modules["harness.shared
    .mcp_server"]` -- the latter briefly replaces the one module object every
    other test in this file (and `unittest.mock.patch("harness.shared.mcp_server
    .X", ...)`'s own string-path resolution) depends on. That replace-then-restore
    passed in this sandbox and in isolation, but proved to leave `patch(...)`
    silently no-op-ing for two other tests on real CI (3.9/3.10/3.11, not 3.12) --
    this throwaway-module approach never touches the shared cache entry at all.
    """
    import importlib.util

    for name in ("mcp", "mcp.types", "mcp.server", "mcp.server.stdio"):
        monkeypatch.setitem(sys.modules, name, None)

    module_path = Path(__file__).resolve().parents[1] / "mcp_server.py"
    spec = importlib.util.spec_from_file_location("_mcp_server_import_guard_probe", module_path)
    assert spec is not None and spec.loader is not None
    probe = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(probe)

    assert probe.MCP_AVAILABLE is False
    assert probe.types is None
    assert probe.Server is None
    assert probe.stdio_server is None


def test_real_mcp_tool_accepts_the_kwargs_mcp_server_passes() -> None:
    """Pins the real SDK's Tool constructor field names directly, bypassing MockTool
    entirely -- this is the one test that would have caught the original
    inputSchema/input_schema mismatch, and only runs where `mcp` is actually
    installed (CI's 3.10/3.12/build-full legs).

    Deliberately does NOT check `mcp_mod.MCP_AVAILABLE`: the autouse
    `ensure_mock_mcp` fixture above unconditionally monkeypatches that flag to
    `True` for every test in this file, real package or not -- exactly the
    kind of always-mocked check this test exists to route around. Import the
    real package directly and skip only on a genuine ImportError.
    """
    try:
        import mcp.types as real_types
    except ImportError:
        pytest.skip("mcp package not installed (DEC-026)")

    schema = {"type": "object"}
    schema_key = (
        "inputSchema"
        if hasattr(real_types.Tool, "model_fields") and "inputSchema" in real_types.Tool.model_fields
        else "input_schema"
    )
    tool_kwargs: dict[str, Any] = {
        "name": "x",
        "description": "y",
        schema_key: schema,
    }
    tool = real_types.Tool(**tool_kwargs)
    assert tool.name == "x"
    assert tool.description == "y"
    assert getattr(tool, "inputSchema", getattr(tool, "input_schema", None)) == schema


def test_run_mcp_server(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Test run_mcp_server starts the stdio server."""
    mock_stdio = MagicMock()
    mock_stdio.return_value.__aenter__ = AsyncMock(return_value=(MagicMock(), MagicMock()))
    mock_stdio.return_value.__aexit__ = AsyncMock()
    monkeypatch.setattr(mcp_mod, "stdio_server", mock_stdio)

    def fake_run(coro: Any) -> None:
        coro.close()

    with patch("asyncio.run", side_effect=fake_run) as mock_run:
        run_mcp_server(tmp_path, "nemotron-reasoner")
        assert mock_run.called


def test_run_mcp_server_awaits_the_server_on_the_stdio_streams(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """The body of the async runner (mcp_server.py lines 158-159): the stdio
    transport is entered, the two streams it yields and the server's own
    initialization options are what ``server.run`` is awaited with, and the
    transport is exited afterwards. ``test_run_mcp_server`` above closes the
    coroutine unawaited, so the body never ran there. No real transport is opened:
    the stdio context manager and the server are both doubles, while
    ``asyncio.run`` is the real one."""
    read_stream, write_stream = object(), object()
    transitions: list[str] = []

    @contextlib.asynccontextmanager
    async def fake_stdio_server() -> AsyncIterator[tuple[object, object]]:
        transitions.append("enter")
        try:
            yield read_stream, write_stream
        finally:
            transitions.append("exit")

    server = MagicMock()
    server.run = AsyncMock()
    server.create_initialization_options.return_value = {"init": "options"}
    factory = MagicMock(return_value=server)
    monkeypatch.setattr(mcp_mod, "stdio_server", fake_stdio_server)
    monkeypatch.setattr(mcp_mod, "create_mcp_server", factory)

    run_mcp_server(tmp_path, "verifier")

    factory.assert_called_once_with(tmp_path, "verifier")
    server.run.assert_awaited_once_with(read_stream, write_stream, {"init": "options"})
    assert transitions == ["enter", "exit"]


def test_call_tool_runs_the_handler_off_the_event_loop_thread(
    tmp_path: Path, broker: ExecutionBroker, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Handlers are synchronous and ``run_command`` blocks on ``subprocess.run``;
    run inline they froze the transport. The handler must execute on a worker
    thread, never on the thread that owns the loop."""
    seen: dict[str, Any] = {}

    def probe(_args: dict[str, Any]) -> str:
        seen["thread"] = threading.current_thread()
        return "probed"

    monkeypatch.setattr(mcp_mod, "_build_tool_handlers", lambda *_a, **_k: {"read_file": probe})
    server = create_mcp_server(tmp_path, role="nemotron-reasoner", broker=broker)

    async def call() -> Any:
        seen["loop_thread"] = threading.current_thread()
        return await server._call_tool_handler("read_file", {"filepath": "x"})

    res = asyncio.run(call())
    assert res[0].text == "probed"
    assert seen["thread"] is not seen["loop_thread"], "handler ran on the event-loop thread"


def test_two_concurrent_tool_calls_overlap(
    tmp_path: Path, broker: ExecutionBroker, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Two calls whose handlers each wait for the *other* to arrive can only
    both finish if the loop keeps scheduling while one of them blocks. Inline
    execution makes the first handler wait out the barrier alone, and the
    result carries the ``BrokenBarrierError`` instead of the payload. The
    barrier's give-up time is the policy's tool timeout, not a literal."""
    barrier = threading.Barrier(2, timeout=orchestrator_defaults()["tool_timeout_sec"])

    def rendezvous(_args: dict[str, Any]) -> str:
        barrier.wait()
        return "met"

    monkeypatch.setattr(mcp_mod, "_build_tool_handlers", lambda *_a, **_k: {"read_file": rendezvous})
    server = create_mcp_server(tmp_path, role="nemotron-reasoner", broker=broker)

    async def both() -> Any:
        return await asyncio.gather(
            server._call_tool_handler("read_file", {"filepath": "a"}),
            server._call_tool_handler("read_file", {"filepath": "b"}),
        )

    first, second = asyncio.run(both())
    assert (first[0].text, second[0].text) == ("met", "met")


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))
