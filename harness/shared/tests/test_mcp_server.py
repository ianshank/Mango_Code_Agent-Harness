"""Tests for MCP server."""

from __future__ import annotations

import asyncio
import contextlib
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any, Callable
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

import harness.shared.mcp_server as mcp_mod
from harness.shared.agent_authority import tools_for_role
from harness.shared.governance.broker import ExecutionBroker, ExecutionResult
from harness.shared.mcp_server import create_mcp_server, run_mcp_server
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
    mock._policy_decision.return_value = None  # PDP approves all writes by default
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

    with patch("harness.shared.mcp_server.execute_run_command", side_effect=RuntimeError("broker crash")):
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
    from harness.shared.governance.broker import ExecutionResult as ER
    broker._policy_decision.return_value = ER(  # type: ignore[attr-defined]
        status="BLOCKED", stdout="", stderr="", exit_code=1,
        reason="BLOCKED: write denied by policy", action="write",
    )
    server = create_mcp_server(tmp_path, role="nemotron-reasoner", broker=broker)
    result = asyncio.run(server._call_tool_handler("write_file", {"filepath": "x.py", "content": ""}))
    assert len(result) == 1
    assert "Denied" in result[0].text
    assert not (tmp_path / "x.py").exists()


def test_mcp_server_broker_pdp_blocks_apply_patch(tmp_path: Path, broker: ExecutionBroker) -> None:
    """AC-3 (C-MCP-1): broker PDP denial applies to apply_patch too, not just write_file --
    both go through the same _broker_authorize_write check in _build_tool_handlers, but
    only write_file's denial path had a test before this."""
    from harness.shared.governance.broker import ExecutionResult as ER
    target = tmp_path / "x.py"
    target.write_text("hello", encoding="utf-8")
    broker._policy_decision.return_value = ER(  # type: ignore[attr-defined]
        status="BLOCKED", stdout="", stderr="", exit_code=1,
        reason="BLOCKED: write denied by policy", action="write",
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
