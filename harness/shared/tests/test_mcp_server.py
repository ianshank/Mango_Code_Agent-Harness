"""Tests for MCP server."""

from __future__ import annotations

import asyncio
import contextlib
import logging
import threading
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any, Callable
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

import harness.shared.mcp_server as mcp_mod
from harness.shared.agent_authority import execution_identity, tools_for_role
from harness.shared.governance.broker import ExecutionBroker, ExecutionResult
from harness.shared.mcp_server import create_mcp_server, run_mcp_server
from harness.shared.orchestrator.dispatcher import ToolDispatcher
from harness.shared.policy_loader import orchestrator_defaults
from harness.shared.tool_schemas import NEMOTRON_TOOLS

pytestmark = pytest.mark.enable_socket


class MockTool:
    def __init__(
        self,
        *,
        name: str,
        description: str,
        input_schema: dict[str, Any] | None = None,
        inputSchema: dict[str, Any] | None = None,
    ):
        self.name = name
        self.description = description
        schema = inputSchema if inputSchema is not None else (input_schema or {})
        self.input_schema = schema
        self.inputSchema = schema


class MockTextContent:
    def __init__(self, *args: Any, **kwargs: Any):
        self.type = kwargs.get("type", "text")
        self.text = kwargs.get("text", "")


class MockServer:
    def __init__(self, name: str):
        self.name = name
        self._list_tools_handler: Callable | None = None
        self._call_tool_handler: Callable | None = None

    def list_tools(self) -> Callable:
        def decorator(fn: Callable) -> Callable:
            self._list_tools_handler = fn
            return fn
        return decorator

    def call_tool(self) -> Callable:
        def decorator(fn: Callable) -> Callable:
            self._call_tool_handler = fn
            return fn
        return decorator

    def create_initialization_options(self) -> dict[str, Any]:
        return {}

    async def run(self, read_stream: Any, write_stream: Any, init_options: Any) -> None:
        pass


class MockTypes:
    Tool = MockTool
    TextContent = MockTextContent


@pytest.fixture(autouse=True)
def ensure_mock_mcp(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Ensure tests run consistently regardless of external mcp package presence."""
    monkeypatch.setattr(mcp_mod, "MCP_AVAILABLE", True)
    monkeypatch.setattr(mcp_mod, "Server", MockServer)
    monkeypatch.setattr(mcp_mod, "types", MockTypes)
    mock_mem = tmp_path / ".mango" / "memory"
    monkeypatch.setattr("harness.shared.meta_tools.MEMORY_DIR", mock_mem)
    monkeypatch.setattr("harness.shared.meta_tools.GAPS_FILE", mock_mem / "gaps.json")
    monkeypatch.setattr("harness.shared.meta_tools.HYPOTHESES_FILE", mock_mem / "hypotheses.json")


@pytest.fixture
def broker() -> ExecutionBroker:
    mock = MagicMock(spec=ExecutionBroker)
    mock.execute_command.return_value = ExecutionResult(
        status="SUCCESS", stdout="test stdout", stderr="", exit_code=0, reason="", action=""
    )
    # `authorize_action` is the public seam the write path now asks. It replaced a
    # `_policy_decision("tee <path>")` round-trip, where a filepath of `-find`
    # made the classifier answer `read` and let roles holding no `write` action
    # write files (DEC-042). `spec=ExecutionBroker` means this stub fails the
    # moment the real method is renamed or removed.
    mock.authorize_action.return_value = None  # PDP approves all writes by default
    return mock


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
    import sys
    from pathlib import Path

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


@pytest.mark.enable_socket
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


def test_every_declared_tool_has_a_handler(tmp_path: Path, broker: ExecutionBroker) -> None:
    """Declaration (NEMOTRON_TOOLS) and dispatch (_build_tool_handlers) must not
    drift -- mirrors mango_mas_orchestrator.py's identical registry-drift test
    for its own copy of this same six-tool dispatch table."""
    handlers = mcp_mod._build_tool_handlers(tmp_path, broker, "nemotron-reasoner")
    tools: list[dict[str, Any]] = NEMOTRON_TOOLS
    declared = {t["function"]["name"] for t in tools}
    registered = set(handlers)
    assert declared == registered, (
        f"declared-but-unhandled: {declared - registered}; "
        f"handled-but-undeclared: {registered - declared}"
    )


def test_mcp_server_tools_sync_by_role(tmp_path: Path, broker: ExecutionBroker) -> None:
    """AC-2: Tool descriptions match the schemas allowed for the active role."""
    server = create_mcp_server(tmp_path, role="nemotron-reasoner", broker=broker)
    assert server._list_tools_handler is not None

    tools = asyncio.run(server._list_tools_handler())
    expected_schemas = tools_for_role("nemotron-reasoner", NEMOTRON_TOOLS)
    assert len(tools) == len(expected_schemas)

    tool_names = {t.name for t in tools}
    schema_names = {schema["function"]["name"] for schema in expected_schemas}
    assert tool_names == schema_names
    assert {tool.name: tool.input_schema for tool in tools} == {
        schema["function"]["name"]: schema["function"]["parameters"] for schema in expected_schemas
    }


def test_mcp_server_role_unauthorized_tool_denied(tmp_path: Path, broker: ExecutionBroker) -> None:
    """AC-3: Calling a tool unauthorized for the role returns a permission denial message."""
    server = create_mcp_server(tmp_path, role="verifier", broker=broker)
    assert server._call_tool_handler is not None

    result = asyncio.run(server._call_tool_handler("write_file", {"filepath": "test.py", "content": "print(1)"}))
    assert len(result) == 1
    assert "not permitted for role 'verifier'" in result[0].text


@pytest.mark.parametrize(
    "tool_name, args, expected_snippet",
    [
        ("write_file", {"filepath": "sample.txt", "content": "hello"}, "Wrote"),
        ("read_file", {"filepath": "sample.txt"}, "hello"),
        ("apply_patch", {"filepath": "sample.txt", "old_text": "hello", "new_text": "world"}, "patched"),
        ("run_command", {"command": "echo test"}, "test stdout"),
        ("knowledge_gap_log", {"question": "q", "what_needed": "w", "proposed_approach": "p"}, "Knowledge gap logged"),
        ("hypothesis_register", {"claim": "c", "reasoning": "r", "confidence": 0.9}, "Hypothesis registered"),
    ],
)
def test_mcp_server_execute_tool_success(
    tmp_path: Path, broker: ExecutionBroker, tool_name: str, args: dict[str, Any], expected_snippet: str
) -> None:
    """Test standard success paths for each tool."""
    if tool_name in ("read_file", "apply_patch"):
        (tmp_path / "sample.txt").write_text("hello", encoding="utf-8")

    server = create_mcp_server(tmp_path, role="nemotron-reasoner", broker=broker)
    handler = server._call_tool_handler
    assert handler is not None

    res = asyncio.run(handler(tool_name, args))
    assert expected_snippet in res[0].text


def test_mcp_server_execute_tool_broker_crash(tmp_path: Path, broker: ExecutionBroker) -> None:
    """Test tools gracefully handle execution exceptions from the broker or executors."""
    server = create_mcp_server(tmp_path, role="nemotron-reasoner", broker=broker)
    handler = server._call_tool_handler
    assert handler is not None

    # The executor is reached through the dispatcher's registry now, so the seam
    # is the dispatcher module's import of it, not a name in mcp_server.
    with patch("harness.shared.orchestrator.dispatcher.execute_run_command", side_effect=RuntimeError("broker crash")):
        res = asyncio.run(handler("run_command", {"command": "broken"}))
        assert "Error executing tool" in res[0].text


def test_mcp_server_read_file_lines(tmp_path: Path, broker: ExecutionBroker) -> None:
    """Test read_file properly applies start_line and end_line bounds."""
    target = tmp_path / "lines.txt"
    target.write_text("one\ntwo\nthree\nfour\nfive", encoding="utf-8")
    server = create_mcp_server(tmp_path, role="nemotron-reasoner", broker=broker)
    handler = server._call_tool_handler
    assert handler is not None

    res = asyncio.run(handler("read_file", {"filepath": "lines.txt", "start_line": 2, "end_line": 4}))
    assert "two" in res[0].text
    assert "four" in res[0].text
    assert "one" not in res[0].text
    assert "five" not in res[0].text


def test_mcp_server_write_file_empty_path(tmp_path: Path, broker: ExecutionBroker) -> None:
    """Test write_file handles empty filepath cleanly (falls back to executor error)."""
    server = create_mcp_server(tmp_path, role="nemotron-reasoner", broker=broker)
    handler = server._call_tool_handler
    assert handler is not None

    # Empty string should pass through to executor which rejects it
    res = asyncio.run(handler("write_file", {"filepath": "", "content": "test"}))
    assert "Error" in res[0].text or "denied" in res[0].text.lower() or "missing" in res[0].text.lower()


def test_mcp_server_apply_patch_not_found(tmp_path: Path, broker: ExecutionBroker) -> None:
    """Test apply_patch properly handles when old_text is not found in file."""
    target = tmp_path / "notfound.txt"
    target.write_text("actual text", encoding="utf-8")
    server = create_mcp_server(tmp_path, role="nemotron-reasoner", broker=broker)
    handler = server._call_tool_handler
    assert handler is not None

    res = asyncio.run(
        handler("apply_patch", {"filepath": "notfound.txt", "old_text": "missing text", "new_text": "replacement"})
    )
    assert "error patching file" in res[0].text.lower() and "matched 0 times" in res[0].text.lower()


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


def test_mcp_server_broker_pdp_blocks_write(tmp_path: Path, broker: ExecutionBroker) -> None:
    """AC-3 (C-MCP-1): broker PDP denial for write_file is honoured before the write executes."""
    broker.authorize_action.return_value = (  # type: ignore[attr-defined]
        "action 'write' is not granted to implementer"
    )
    server = create_mcp_server(tmp_path, role="nemotron-reasoner", broker=broker)
    result = asyncio.run(server._call_tool_handler("write_file", {"filepath": "x.py", "content": ""}))
    assert len(result) == 1
    assert "Denied" in result[0].text
    assert not (tmp_path / "x.py").exists()


def test_mcp_server_broker_pdp_blocks_apply_patch(tmp_path: Path, broker: ExecutionBroker) -> None:
    """AC-3 (C-MCP-1): broker PDP denial applies to apply_patch too, not just write_file --
    both go through the same authorize_write check in _build_tool_handlers, but
    only write_file's denial path had a test before this."""
    target = tmp_path / "x.py"
    target.write_text("hello", encoding="utf-8")
    broker.authorize_action.return_value = (  # type: ignore[attr-defined]
        "action 'write' is not granted to implementer"
    )
    server = create_mcp_server(tmp_path, role="nemotron-reasoner", broker=broker)
    result = asyncio.run(
        server._call_tool_handler("apply_patch", {"filepath": "x.py", "old_text": "hello", "new_text": "world"})
    )
    assert len(result) == 1
    assert "Denied" in result[0].text
    assert target.read_text(encoding="utf-8") == "hello"


def test_mcp_server_unknown_tool_error_message_preserved(tmp_path: Path, broker: ExecutionBroker) -> None:
    """The registry refactor must not change the "Unknown tool" wire message: the
    dispatcher still raises internally and lets the outer except wrap it, rather than
    returning a differently-worded string straight from the registry-miss branch.

    Patches tool_is_permitted rather than picking a real tool name: an unmapped
    name is withheld by tool_is_permitted itself (agent_authority.py's own
    "undecided grant reads as no" rule), so a genuinely-unknown name never
    reaches the registry lookup this test targets -- it would hit the
    not-permitted branch first and never exercise the code under test.
    """
    with patch("harness.shared.mcp_server.tool_is_permitted", return_value=True):
        server = create_mcp_server(tmp_path, role="nemotron-reasoner", broker=broker)
        result = asyncio.run(server._call_tool_handler("not_a_real_tool", {}))
    assert len(result) == 1
    assert result[0].text == "Error executing tool 'not_a_real_tool': Unknown tool: not_a_real_tool"


def test_mcp_server_policy_lookup_failure_denies(tmp_path: Path, broker: ExecutionBroker) -> None:
    """Policy lookup errors inside the handler must return a structured denial, not raise."""
    server = create_mcp_server(tmp_path, role="nemotron-reasoner", broker=broker)
    with patch("harness.shared.mcp_server.tool_is_permitted", side_effect=RuntimeError("policy read failure")):
        result = asyncio.run(server._call_tool_handler("write_file", {"filepath": "x.py", "content": ""}))
    assert len(result) == 1
    assert "denied" in result[0].text.lower()


# --- One registry, two transports (audit M8) ---------------------------------


def _assert_registry_parity(mcp_names: set[str], dispatcher_names: set[str]) -> None:
    """The check the parity tests below share, so the negative variant can prove
    the check itself bites rather than re-deriving it with a different shape."""
    assert mcp_names == dispatcher_names, (
        f"mcp-only: {mcp_names - dispatcher_names}; dispatcher-only: {dispatcher_names - mcp_names}"
    )


def test_mcp_handler_names_equal_dispatcher_handler_names(tmp_path: Path, broker: ExecutionBroker) -> None:
    """A tool added to (or dropped from) ``ToolDispatcher.tool_handlers`` appears
    in (or leaves) the MCP registry in the same commit -- the two are one table."""
    dispatcher = ToolDispatcher(workspace_dir=tmp_path, broker=broker)
    mcp_names = set(mcp_mod._build_tool_handlers(tmp_path, broker, "nemotron-reasoner"))
    _assert_registry_parity(mcp_names, set(dispatcher.tool_handlers))
    # The helper raises on divergence; the equality is restated here so the test
    # carries its own assertion (test_test_quality's no-assertion-free-tests rule).
    assert mcp_names == set(dispatcher.tool_handlers)
    assert mcp_names, "an empty registry would satisfy parity vacuously"


def test_registry_parity_check_fails_when_a_name_is_dropped(tmp_path: Path, broker: ExecutionBroker) -> None:
    """Negative variant: the parity assertion is not vacuous. Removing one name
    from either side must make it raise."""
    dispatcher_names = set(ToolDispatcher(workspace_dir=tmp_path, broker=broker).tool_handlers)
    mcp_names = set(mcp_mod._build_tool_handlers(tmp_path, broker, "nemotron-reasoner"))
    dropped = mcp_names - {"run_command"}
    assert "run_command" in mcp_names, "precondition: the dropped name was registered"
    with pytest.raises(AssertionError, match="dispatcher-only: \\{'run_command'\\}"):
        _assert_registry_parity(dropped, dispatcher_names)


def test_mcp_registry_is_the_dispatcher_table_not_a_copy(
    tmp_path: Path, broker: ExecutionBroker, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The refactor's actual guarantee: mcp_server *derives* its table from the
    dispatcher rather than mirroring it by hand. A dispatcher that stops
    serving a tool must take that tool away from the MCP transport too.
    A hand-mirrored registry (the previous implementation) keeps serving it and
    fails here."""

    class DispatcherWithoutRunCommand(ToolDispatcher):
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            super().__init__(*args, **kwargs)
            del self.tool_handlers["run_command"]

    monkeypatch.setattr(mcp_mod, "ToolDispatcher", DispatcherWithoutRunCommand)
    handlers = mcp_mod._build_tool_handlers(tmp_path, broker, "nemotron-reasoner")
    assert "run_command" not in handlers
    assert set(handlers) == set(ToolDispatcher(workspace_dir=tmp_path, broker=broker).tool_handlers) - {"run_command"}


def test_shared_registry_carries_the_acting_role(tmp_path: Path, broker: ExecutionBroker) -> None:
    """Role scoping must survive the shared registry: the dispatcher's handlers
    read ``active_role`` at call time, so the MCP transport has to set it
    before serving the table. A verifier reaching the shared ``write_file``
    handler is refused by the same PDP question ``ToolDispatcher`` asks."""
    broker.authorize_action.return_value = "action 'write' is not granted to verifier"  # type: ignore[attr-defined]
    handlers = mcp_mod._build_tool_handlers(tmp_path, broker, "verifier")
    assert handlers["write_file"]({"filepath": "x.py", "content": ""}).startswith("Denied:")
    # The PDP is asked under the role's execution identity, the same mapping
    # `ToolDispatcher` uses -- not under the transport-facing role name.
    broker.authorize_action.assert_called_with(execution_identity("verifier"), "write")  # type: ignore[attr-defined]
    assert not (tmp_path / "x.py").exists()


# --- The handler leaves the event loop free (audit M9) ------------------------


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


# --- Structured per-call logging ----------------------------------------------


def _tool_call_records(caplog: pytest.LogCaptureFixture) -> list[logging.LogRecord]:
    return [r for r in caplog.records if r.name == mcp_mod.__name__ and r.getMessage().startswith("mcp_tool_call ")]


def test_permitted_call_logs_at_debug_with_keys_only(
    tmp_path: Path, broker: ExecutionBroker, caplog: pytest.LogCaptureFixture
) -> None:
    secret = "hunter2-do-not-log"
    server = create_mcp_server(tmp_path, role="nemotron-reasoner", broker=broker)
    with caplog.at_level(logging.DEBUG, logger=mcp_mod.__name__):
        asyncio.run(server._call_tool_handler("write_file", {"filepath": "note.txt", "content": secret}))

    records = _tool_call_records(caplog)
    assert len(records) == 1
    record = records[0]
    message = record.getMessage()
    assert record.levelno == logging.DEBUG
    assert "tool=write_file" in message
    assert "role=nemotron-reasoner" in message
    assert "permitted=True" in message
    assert "duration_ms=" in message
    assert "argument_keys=['content', 'filepath']" in message
    assert secret not in message, "argument values leaked into the log"
    assert secret not in caplog.text


def test_denied_call_logs_at_warning(tmp_path: Path, broker: ExecutionBroker, caplog: pytest.LogCaptureFixture) -> None:
    server = create_mcp_server(tmp_path, role="verifier", broker=broker)
    with caplog.at_level(logging.DEBUG, logger=mcp_mod.__name__):
        asyncio.run(server._call_tool_handler("write_file", {"filepath": "x.py", "content": "print(1)"}))

    records = _tool_call_records(caplog)
    assert len(records) == 1
    assert records[0].levelno == logging.WARNING
    message = records[0].getMessage()
    assert "tool=write_file" in message and "role=verifier" in message and "permitted=False" in message
    assert "print(1)" not in caplog.text


def test_policy_lookup_failure_logs_the_call_as_denied(
    tmp_path: Path, broker: ExecutionBroker, caplog: pytest.LogCaptureFixture
) -> None:
    server = create_mcp_server(tmp_path, role="nemotron-reasoner", broker=broker)
    with caplog.at_level(logging.DEBUG, logger=mcp_mod.__name__), patch(
        "harness.shared.mcp_server.tool_is_permitted", side_effect=RuntimeError("policy read failure")
    ):
        asyncio.run(server._call_tool_handler("write_file", None))

    records = _tool_call_records(caplog)
    assert len(records) == 1
    assert records[0].levelno == logging.WARNING
    assert "permitted=False" in records[0].getMessage()
    assert "argument_keys=[]" in records[0].getMessage()
