"""Shared test doubles and helper factories for MCP server tests."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable
from unittest.mock import MagicMock

import pytest

import harness.shared.mcp_server as mcp_mod
from harness.shared.governance.broker import ExecutionBroker, ExecutionResult


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


def setup_mock_mcp(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Ensure tests run consistently regardless of external mcp package presence."""
    monkeypatch.setattr(mcp_mod, "MCP_AVAILABLE", True)
    monkeypatch.setattr(mcp_mod, "Server", MockServer)
    monkeypatch.setattr(mcp_mod, "types", MockTypes)
    mock_mem = tmp_path / ".mango" / "memory"
    monkeypatch.setattr("harness.shared.meta_tools.MEMORY_DIR", mock_mem)
    monkeypatch.setattr("harness.shared.meta_tools.GAPS_FILE", mock_mem / "gaps.json")
    monkeypatch.setattr("harness.shared.meta_tools.HYPOTHESES_FILE", mock_mem / "hypotheses.json")


def make_mock_broker() -> ExecutionBroker:
    """Create a mock ExecutionBroker with permissive defaults."""
    mock = MagicMock(spec=ExecutionBroker)
    mock.execute_command.return_value = ExecutionResult(
        status="SUCCESS", stdout="test stdout", stderr="", exit_code=0, reason="", action=""
    )
    # `authorize_action` is the public seam the write path asks (DEC-042).
    # `spec=ExecutionBroker` means this stub fails the moment the real method is renamed.
    mock.authorize_action.return_value = None  # PDP approves all writes by default
    return mock
