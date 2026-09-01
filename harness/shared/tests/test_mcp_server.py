"""Tests for MCP server."""

from __future__ import annotations

from pathlib import Path
from typing import Any, cast
from unittest.mock import MagicMock

import pytest

pytest.importorskip("mcp")

import mcp.types as types  # noqa: E402

from harness.shared.agent_authority import tools_for_role  # noqa: E402
from harness.shared.governance.broker import ExecutionBroker, ExecutionResult  # noqa: E402
from harness.shared.mcp_server import create_mcp_server  # noqa: E402
from harness.shared.tool_schemas import NEMOTRON_TOOLS  # noqa: E402

pytestmark = pytest.mark.enable_socket


@pytest.fixture
def broker() -> ExecutionBroker:
    mock = MagicMock(spec=ExecutionBroker)
    mock.execute_command.return_value = ExecutionResult(
        status="SUCCESS", stdout="test stdout", stderr="", exit_code=0, reason="", action=""
    )
    return mock


@pytest.mark.asyncio
async def test_mcp_server_initialization(tmp_path: Path, broker: ExecutionBroker) -> None:
    """AC-1: The mcp_server.py starts and successfully initializes an MCP STDIO session without errors."""
    server = create_mcp_server(tmp_path, broker=broker)
    assert server.name == "nemotron-mcp-server"
    assert types.ListToolsRequest in server.request_handlers
    assert types.CallToolRequest in server.request_handlers


@pytest.mark.asyncio
async def test_mcp_server_tools_sync_by_role(tmp_path: Path, broker: ExecutionBroker) -> None:
    """AC-2: Tool descriptions retrieved via the MCP server correctly match the schemas allowed for the active role."""
    server = create_mcp_server(tmp_path, role="nemotron-reasoner", broker=broker)
    handler = server.request_handlers[types.ListToolsRequest]

    req = types.ListToolsRequest(method="tools/list")
    result = await handler(req)

    inner_result = result.root if hasattr(result, "root") else result
    tools = getattr(inner_result, "tools", inner_result)

    expected_schemas = tools_for_role("nemotron-reasoner", NEMOTRON_TOOLS)
    tools_list = list(tools) if not isinstance(tools, list) else tools
    assert len(tools_list) == len(expected_schemas)

    tool_names = {t.name for t in tools_list}
    schema_names = {str(cast(dict[str, Any], schema)["function"]["name"]) for schema in expected_schemas}
    assert tool_names == schema_names


@pytest.mark.asyncio
async def test_mcp_server_role_unauthorized_tool_denied(tmp_path: Path, broker: ExecutionBroker) -> None:
    """AC-3: Calling a tool unauthorized for the role returns a permission denial message."""
    server = create_mcp_server(tmp_path, role="verifier", broker=broker)
    handler = server.request_handlers[types.CallToolRequest]

    req = types.CallToolRequest(
        params=types.CallToolRequestParams(
            name="write_file",
            arguments={"filepath": "test.py", "content": "print(1)"}
        )
    )

    result = await handler(req)
    inner_result = result.root if hasattr(result, "root") else result
    content = getattr(inner_result, "content", inner_result)
    content_list = list(content) if not isinstance(content, list) else content
    assert len(content_list) == 1
    assert "not permitted for role 'verifier'" in content_list[0].text


@pytest.mark.asyncio
async def test_mcp_server_security_containment(tmp_path: Path, broker: ExecutionBroker) -> None:
    """AC-4: Tool execution requests routed through the MCP server correctly hit the ExecutionBroker."""
    server = create_mcp_server(tmp_path, broker=broker)
    handler = server.request_handlers[types.CallToolRequest]

    req = types.CallToolRequest(
        params=types.CallToolRequestParams(
            name="run_command",
            arguments={"command": "echo hello"}
        )
    )

    result = await handler(req)

    cast(MagicMock, broker.execute_command).assert_called_once_with(
        "echo hello",
        context={"agent_id": "implementer"},
        cwd=tmp_path
    )

    inner_result = result.root if hasattr(result, "root") else result
    content = getattr(inner_result, "content", inner_result)

    content_list = list(content) if not isinstance(content, list) else content
    assert len(content_list) == 1
    assert "test stdout" in content_list[0].text
