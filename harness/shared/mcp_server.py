"""MCP Server for Nemotron tools."""

from __future__ import annotations

import asyncio
import logging
import sys
from pathlib import Path
from typing import Any, Callable, cast

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

from harness.shared.agent_authority import execution_identity, tool_is_permitted, tools_for_role
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
        f"tee {filepath}", {"agent_id": execution_identity(role)}
    )
    if denial is not None:
        return denial.reason
    return None


def _build_tool_handlers(
    workspace_dir: Path, broker: ExecutionBroker, role: str
) -> dict[str, Callable[[dict[str, Any]], str]]:
    """Tool dispatch registry: every function name declared in NEMOTRON_TOOLS
    must have an entry here (pinned by test_every_declared_tool_has_a_handler,
    mirroring mango_mas_orchestrator.py's identical registry so the two
    dispatch tables -- same six tools, same tool_executors call sites -- can't
    silently drift apart the way an if/elif chain re-authored by hand could).

    ``args.get(key) or ""`` rather than ``args.get(key, "")``: a *present* key
    whose value is JSON ``null`` returns ``None`` from ``.get(key, default)``,
    since the default only applies to a *missing* key -- ``or ""`` normalises
    both to the empty string every executor already treats as "nothing
    supplied". Not applied to ``confidence`` (``0.0`` is a legitimate value
    ``or DEFAULT`` would silently discard).
    """

    def _write_file(args: dict[str, Any]) -> str:
        filepath = args.get("filepath") or ""
        denial_reason = _broker_authorize_write(broker, role, filepath)
        if denial_reason is not None:
            return f"Denied: {denial_reason}"
        return execute_write_file(workspace_dir, filepath, args.get("content") or "")

    def _apply_patch(args: dict[str, Any]) -> str:
        filepath = args.get("filepath") or ""
        denial_reason = _broker_authorize_write(broker, role, filepath)
        if denial_reason is not None:
            return f"Denied: {denial_reason}"
        return execute_apply_patch(
            workspace_dir, filepath, args.get("old_text") or "", args.get("new_text") or ""
        )

    return {
        "write_file": _write_file,
        "read_file": lambda args: execute_read_file(
            workspace_dir, args.get("filepath") or "", args.get("start_line"), args.get("end_line")
        ),
        "apply_patch": _apply_patch,
        "run_command": lambda args: execute_run_command(
            broker, role, workspace_dir, args.get("command") or ""
        ),
        "knowledge_gap_log": lambda args: knowledge_gap_log(
            args.get("question") or "", args.get("what_needed") or "", args.get("proposed_approach") or ""
        ),
        "hypothesis_register": lambda args: hypothesis_register(
            args.get("claim") or "",
            args.get("reasoning") or "",
            args.get("confidence", DEFAULT_HYPOTHESIS_CONFIDENCE),
        ),
    }


def create_mcp_server(
    workspace_dir: Path,
    role: str = "nemotron-reasoner",
    broker: ExecutionBroker | None = None
) -> Any:
    """Create and configure the MCP server instance."""
    if not MCP_AVAILABLE or Server is None:
        raise ImportError("The 'mcp' package is required to run the MCP server. Install it with `pip install mcp`.")

    server: Any = Server("nemotron-mcp-server")
    actual_broker = broker or ExecutionBroker()
    tool_handlers = _build_tool_handlers(workspace_dir, actual_broker, role)

    @server.list_tools()
    async def handle_list_tools() -> list[types.Tool]:
        allowed_schemas = tools_for_role(role, NEMOTRON_TOOLS)
        tools = []
        for schema in allowed_schemas:
            func = cast(dict[str, Any], schema["function"])
            tools.append(
                types.Tool(
                    name=func["name"],
                    description=func["description"],
                    input_schema=func["parameters"],
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
            handler = tool_handlers.get(name)
            if handler is None:
                raise ValueError(f"Unknown tool: {name}")
            result = handler(args)
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
