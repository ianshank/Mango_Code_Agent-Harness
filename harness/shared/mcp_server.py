"""MCP Server for Nemotron tools."""

from __future__ import annotations

import asyncio
import logging
import sys
from pathlib import Path

try:
    import mcp.types as types
    from mcp.server import Server
    from mcp.server.stdio import stdio_server
    MCP_AVAILABLE = True
except ImportError:  # pragma: no cover
    MCP_AVAILABLE = False
    types = None  # type: ignore[assignment]
    Server = None  # type: ignore[assignment,misc]
    stdio_server = None  # type: ignore[assignment]

from harness.shared.agent_authority import tool_is_permitted, tools_for_role
from harness.shared.governance.broker import ExecutionBroker
from harness.shared.meta_tools import hypothesis_register, knowledge_gap_log
from harness.shared.tool_dispatch import DEFAULT_HYPOTHESIS_CONFIDENCE, _normalize_tool_arguments
from harness.shared.tool_executors import (
    execute_apply_patch,
    execute_read_file,
    execute_run_command,
    execute_write_file,
)
from harness.shared.tool_schemas import NEMOTRON_TOOLS

logger = logging.getLogger(__name__)

def _broker_authorize_write(broker: ExecutionBroker, role: str, filepath: str) -> str | None:
    """Return a denial reason string if the broker's PDP blocks the write, else None."""
    denial = broker._policy_decision(
        f"tee {filepath}", {"agent_id": role}
    )
    if denial is not None:
        return denial.reason
    return None


def create_mcp_server(
    workspace_dir: Path,
    role: str = "nemotron-reasoner",
    broker: ExecutionBroker | None = None
) -> Server:
    """Create and configure the MCP server instance."""
    if not MCP_AVAILABLE or Server is None:
        raise ImportError("The 'mcp' package is required to run the MCP server. Install it with `pip install mcp`.")

    server = Server("nemotron-mcp-server")
    actual_broker = broker or ExecutionBroker()

    @server.list_tools()
    async def handle_list_tools() -> list[types.Tool]:
        from typing import Any, cast
        allowed_schemas = tools_for_role(role, NEMOTRON_TOOLS)
        tools = []
        for schema in allowed_schemas:
            func = cast(dict[str, Any], schema["function"])
            tools.append(
                types.Tool(
                    name=func["name"],
                    description=func["description"],
                    inputSchema=func["parameters"],
                )
            )
        return tools

    @server.call_tool()
    async def handle_call_tool(name: str, arguments: dict | None) -> list[types.TextContent]:
        try:
            if not tool_is_permitted(role, name):
                return [types.TextContent(type="text", text=f"Tool '{name}' is not permitted for role '{role}'.")]
        except Exception as e:  # noqa: BLE001
            logger.error("Policy lookup failed for tool '%s': %s", name, e)
            return [types.TextContent(type="text", text=f"Tool '{name}' denied: policy lookup failed.")]

        args = _normalize_tool_arguments(arguments, name)

        try:
            if name == "write_file":
                filepath = args.get("filepath") or ""
                denial_reason = _broker_authorize_write(actual_broker, role, filepath)
                if denial_reason is not None:
                    return [types.TextContent(type="text", text=f"Denied: {denial_reason}")]
                result = execute_write_file(workspace_dir, filepath, args.get("content") or "")
            elif name == "read_file":
                result = execute_read_file(
                    workspace_dir, args.get("filepath") or "", args.get("start_line"), args.get("end_line")
                )
            elif name == "apply_patch":
                filepath = args.get("filepath") or ""
                denial_reason = _broker_authorize_write(actual_broker, role, filepath)
                if denial_reason is not None:
                    return [types.TextContent(type="text", text=f"Denied: {denial_reason}")]
                result = execute_apply_patch(
                    workspace_dir, filepath, args.get("old_text") or "", args.get("new_text") or ""
                )
            elif name == "run_command":
                result = execute_run_command(actual_broker, role, workspace_dir, args.get("command") or "")
            elif name == "knowledge_gap_log":
                result = knowledge_gap_log(
                    args.get("question") or "", args.get("what_needed") or "", args.get("proposed_approach") or ""
                )
            elif name == "hypothesis_register":
                result = hypothesis_register(
                    args.get("claim") or "",
                    args.get("reasoning") or "",
                    args.get("confidence", DEFAULT_HYPOTHESIS_CONFIDENCE),
                )
            else:
                raise ValueError(f"Unknown tool: {name}")

        except Exception as e:
            logger.exception("Error executing tool %s", name)
            result = f"Error executing tool '{name}': {e}"

        return [types.TextContent(type="text", text=str(result))]

    return server


def run_mcp_server(workspace_dir: Path, role: str = "nemotron-reasoner") -> None:
    """Run the MCP server wrapping Nemotron tools using STDIO transport."""
    server = create_mcp_server(workspace_dir, role)

    async def main() -> None:
        async with stdio_server() as (read_stream, write_stream):
            await server.run(read_stream, write_stream, server.create_initialization_options())

    asyncio.run(main())

if __name__ == "__main__":  # pragma: no cover
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--workspace", type=str, default=".", help="Workspace directory")
    parser.add_argument("--role", type=str, default="nemotron-reasoner", help="Active agent role")
    args = parser.parse_args()

    # Configure logging to stderr so it doesn't pollute MCP stdio transport
    logging.basicConfig(level=logging.WARNING, stream=sys.stderr)

    run_mcp_server(Path(args.workspace).resolve(), args.role)
