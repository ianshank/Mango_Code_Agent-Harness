"""Tests for MCP server."""

from __future__ import annotations

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
    def __init__(self, name: str, description: str, inputSchema: dict[str, Any]):
        self.name = name
        self.description = description
        self.inputSchema = inputSchema


class MockTextContent:
    def __init__(self, type_: str, text: str):
        self.type = type_
        self.text = text


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
    return mock


def test_create_mcp_server_missing_package(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Test create_mcp_server raises ImportError when mcp is unavailable."""
    monkeypatch.setattr(mcp_mod, "MCP_AVAILABLE", False)
    with pytest.raises(ImportError, match="The 'mcp' package is required"):
        create_mcp_server(tmp_path)


@pytest.mark.asyncio
async def test_mcp_server_tools_sync_by_role(tmp_path: Path, broker: ExecutionBroker) -> None:
    """AC-2: Tool descriptions match the schemas allowed for the active role."""
    server = create_mcp_server(tmp_path, role="nemotron-reasoner", broker=broker)
    assert server._list_tools_handler is not None

    tools = await server._list_tools_handler()
    expected_schemas = tools_for_role("nemotron-reasoner", NEMOTRON_TOOLS)
    assert len(tools) == len(expected_schemas)

    tool_names = {t.name for t in tools}
    schema_names = {schema["function"]["name"] for schema in expected_schemas}
    assert tool_names == schema_names


@pytest.mark.asyncio
async def test_mcp_server_role_unauthorized_tool_denied(tmp_path: Path, broker: ExecutionBroker) -> None:
    """AC-3: Calling a tool unauthorized for the role returns a permission denial message."""
    server = create_mcp_server(tmp_path, role="verifier", broker=broker)
    assert server._call_tool_handler is not None

    result = await server._call_tool_handler("write_file", {"filepath": "test.py", "content": "print(1)"})
    assert len(result) == 1
    assert "not permitted for role 'verifier'" in result[0].text


@pytest.mark.asyncio
async def test_mcp_server_execute_all_tools(tmp_path: Path, broker: ExecutionBroker) -> None:
    """Test all tool execution paths through handle_call_tool."""
    server = create_mcp_server(tmp_path, role="nemotron-reasoner", broker=broker)
    handler = server._call_tool_handler
    assert handler is not None

    # write_file
    res = await handler("write_file", {"filepath": "sample.txt", "content": "hello"})
    assert "Wrote" in res[0].text

    # read_file
    res = await handler("read_file", {"filepath": "sample.txt"})
    assert "hello" in res[0].text

    # apply_patch
    res = await handler("apply_patch", {"filepath": "sample.txt", "old_text": "hello", "new_text": "world"})
    assert "patched" in res[0].text

    # run_command
    res = await handler("run_command", {"command": "echo test"})
    assert "test stdout" in res[0].text

    # knowledge_gap_log
    res = await handler("knowledge_gap_log", {"question": "q", "what_needed": "w", "proposed_approach": "p"})
    assert "Knowledge gap logged" in res[0].text

    # hypothesis_register
    res = await handler("hypothesis_register", {"claim": "c", "reasoning": "r", "confidence": 0.9})
    assert "Hypothesis registered" in res[0].text

    # execution error handling
    with patch("harness.shared.mcp_server.execute_run_command", side_effect=RuntimeError("broker crash")):
        res = await handler("run_command", {"command": "broken"})
        assert "Error executing tool" in res[0].text


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


