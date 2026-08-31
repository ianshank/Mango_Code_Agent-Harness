"""Tests for MCP server."""

from pathlib import Path
from typing import Any, cast
from unittest.mock import MagicMock

import mcp.types as types
import pytest

from harness.shared.governance.broker import ExecutionBroker, ExecutionResult
from harness.shared.mcp_server import create_mcp_server
from harness.shared.tool_schemas import NEMOTRON_TOOLS

pytestmark = pytest.mark.enable_socket

@pytest.fixture
def broker(mocker):
    # Depending on how I want to test it. Wait, I can just create a real broker.
    # The broker requires a workspace, etc. Or I can mock it.
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
async def test_mcp_server_tools_sync(tmp_path: Path, broker: ExecutionBroker) -> None:
    """AC-2: Tool descriptions retrieved via the MCP server correctly match the schemas defined in tool_schemas.py."""
    server = create_mcp_server(tmp_path, broker=broker)
    handler = server.request_handlers[types.ListToolsRequest]

    # We call the wrapper with an empty request
    req = types.ListToolsRequest(method="tools/list")

    # Wait, the wrapper returns a Result object or list?
    # Let's inspect the type
    result = await handler(req)

    # In mcp SDK, it returns a ListToolsResult or list of Tools.
    # Pydantic v2 / MCP might return a RootModel or something where the inner object is in .root
    inner_result = result.root if hasattr(result, "root") else result
    tools = getattr(inner_result, "tools", inner_result)

    # Number of tools must match
    tools_list = list(tools) if not isinstance(tools, list) else tools
    assert len(tools_list) == len(NEMOTRON_TOOLS)

    tool_names = {t.name for t in tools_list}
    schema_names = {str(cast(dict[str, Any], schema)["function"]["name"]) for schema in NEMOTRON_TOOLS}
    assert tool_names == schema_names


@pytest.mark.asyncio
async def test_mcp_server_security_containment(tmp_path: Path, broker: ExecutionBroker) -> None:
    """AC-3: Tool execution requests routed through the MCP server correctly hit the ExecutionBroker."""
    server = create_mcp_server(tmp_path, broker=broker)
    handler = server.request_handlers[types.CallToolRequest]

    req = types.CallToolRequest(
        params=types.CallToolRequestParams(
            name="run_command",
            arguments={"command": "echo hello"}
        )
    )

    result = await handler(req)

    from typing import cast
    # Broker should have been called
    cast(MagicMock, broker.execute_command).assert_called_once_with(
        "echo hello",
        context={"agent_id": "implementer"},
        cwd=tmp_path
    )

    # The result should contain the mocked broker output
    inner_result = result.root if hasattr(result, "root") else result
    content = getattr(inner_result, "content", inner_result)

    content_list = list(content) if not isinstance(content, list) else content
    assert len(content_list) == 1
    assert "test stdout" in content_list[0].text
