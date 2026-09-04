"""MCP Server for Nemotron tools."""

from __future__ import annotations

import asyncio
import logging
import sys
import time
from pathlib import Path
from typing import Any, Callable, cast

try:
    import mcp.types as types
    from mcp.server import Server
    from mcp.server.stdio import stdio_server
    MCP_AVAILABLE = True
except ImportError:
    # No pragma: this arc is the Python 3.9 leg's real code path (the mcp SDK's
    # floor is 3.10) and `test_import_failure_sets_mcp_unavailable` executes it
    # directly, by blocking the SDK in sys.modules and re-running this module
    # from its path. Excluding it understated the file and hid whether the
    # fallback still leaves the module in a safe state (gate-truthfulness R-GT-3).
    MCP_AVAILABLE = False
    types = None  # type: ignore[assignment]
    Server = None  # type: ignore[assignment,misc]
    stdio_server = None  # type: ignore[assignment]

from harness.shared.agent_authority import tool_is_permitted, tools_for_role
from harness.shared.governance.broker import ExecutionBroker
from harness.shared.orchestrator.dispatcher import ToolDispatcher
from harness.shared.tool_arg_validation import invalid_arguments_reason, parameter_schemas
from harness.shared.tool_dispatch import _normalize_tool_arguments
from harness.shared.tool_executors import authorize_write
from harness.shared.tool_schemas import NEMOTRON_TOOLS

logger = logging.getLogger(__name__)

#: The authorization this module used to define for itself. It now lives beside
#: the executors it guards, so `ToolDispatcher` reaches the same function instead
#: of reaching nothing (R-CQ-5). Kept as a name here because the transport's own
#: tests address it, and because a reader following the write path through this
#: file should still find it named.
_broker_authorize_write = authorize_write


def _build_tool_handlers(
    workspace_dir: Path, broker: ExecutionBroker, role: str
) -> dict[str, Callable[[dict[str, Any]], str]]:
    """Tool dispatch registry for the MCP transport.

    This used to be a hand-written mirror of ``ToolDispatcher.tool_handlers``:
    the same six tools, the same ``tool_executors`` call sites, the same
    ``args.get(key) or ""`` null-normalisation, re-authored here so that the two
    transports could -- and did (R-CQ-5) -- drift apart. There is now one
    registry. The MCP transport instantiates the orchestrator's dispatcher with
    the acting role and serves *its* table, so a tool added to, removed from, or
    re-authorized in the dispatcher is added to, removed from, or re-authorized
    in the MCP server in the same commit (audit M8).

    The signature is unchanged: every caller that reached this function before
    (the credential-containment and Nemotron-triage regressions, the
    one-write-authorization-path test) reaches the same names through it now.
    ``tool_timeout`` is left at the dispatcher's default, which is what this
    transport passed to ``execute_run_command`` before the registry was shared.
    """
    dispatcher = ToolDispatcher(workspace_dir=workspace_dir, broker=broker)
    dispatcher.set_active_role(role)
    return dispatcher.tool_handlers


def _schema_argument_keys(name: str) -> frozenset[str]:
    """The argument names the tool's own schema declares.

    Only these may appear in a log line. A caller controls the raw dictionary,
    so an unknown key name is attacker-chosen text; logging it would let a
    credential travel in the *name* of a key even though values are never
    logged (Copilot review on PR #86).
    """
    for schema in NEMOTRON_TOOLS:
        func = cast(dict[str, Any], schema["function"])
        if func.get("name") == name:
            params = cast(dict[str, Any], func.get("parameters") or {})
            return frozenset(cast(dict[str, Any], params.get("properties") or {}))
    return frozenset()


def _loggable_argument_keys(name: str, arguments: Any) -> tuple[list[str], int]:
    """Schema-declared key names in sorted order, plus the count of keys that were not."""
    if not isinstance(arguments, dict):
        return [], 0
    declared = _schema_argument_keys(name)
    known = sorted(key for key in arguments if key in declared)
    return known, len(arguments) - len(known)


#: How the executors spell a refusal or a failure. ``write_file``/``read_file``
#: fold the write/read policy's denial into ``Error writing file …`` /
#: ``Error reading file …``; the broker's refusal of a command and the
#: dispatcher's argument validation carry their own prefixes.
_REFUSAL_PREFIXES = (
    "Denied",
    "Error writing file",
    "Error reading file",
    "Error patching file",
    "Error executing tool",
    "Error:",
)

#: The same per-tool schemas `ToolDispatcher` validates against, so the MCP
#: door cannot hand an executor a call the in-process door would refuse.
_PARAMETER_SCHEMAS = parameter_schemas(NEMOTRON_TOOLS)


def _handler_refused(result: Any) -> bool:
    """Whether the shared handler refused or failed the call after the static
    role check passed: a read/write-policy denial, a broker PDP refusal, a
    validation failure, or an execution error. The registry lambdas return the
    executor's string verbatim, so the prefix is the structural signal."""
    return isinstance(result, str) and result.startswith(_REFUSAL_PREFIXES)


def _log_tool_call(
    *,
    name: str,
    role: str,
    permitted: bool,
    duration_ms: float,
    argument_keys: list[str],
    unknown_key_count: int = 0,
) -> None:
    """One structured line per call, sink-agnostic (``json_logging`` wraps the
    root handler; this only chooses the fields and the level).

    Argument *names* are logged; argument *values* never are. ``write_file``'s
    ``content`` and ``run_command``'s ``command`` are exactly the kind of
    payload that carries credentials, and a log line is the one place a
    credential-containment gate does not look.
    """
    level = logging.DEBUG if permitted else logging.WARNING
    logger.log(
        level,
        "mcp_tool_call tool=%s role=%s permitted=%s duration_ms=%.3f argument_keys=%s unknown_key_count=%d",
        name, role, permitted, duration_ms, argument_keys,
        unknown_key_count,
    )


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
            tool_kwargs: dict[str, Any] = {
                "name": func["name"],
                "description": func["description"],
            }
            if hasattr(types.Tool, "model_fields") and "inputSchema" in types.Tool.model_fields:
                tool_kwargs["inputSchema"] = func["parameters"]
            else:
                tool_kwargs["input_schema"] = func["parameters"]
            try:
                tools.append(types.Tool(**tool_kwargs))
            except (TypeError, ValueError):
                alt_field = "input_schema" if "inputSchema" in tool_kwargs else "inputSchema"
                alt_kwargs = {
                    "name": func["name"],
                    "description": func["description"],
                    alt_field: func["parameters"],
                }
                tools.append(types.Tool(**alt_kwargs))
        return tools

    @server.call_tool()
    async def handle_call_tool(name: str, arguments: dict | None) -> list[types.TextContent]:
        started = time.perf_counter()
        argument_keys, unknown_key_count = _loggable_argument_keys(name, arguments)
        try:
            if not tool_is_permitted(role, name):
                _log_tool_call(
                    name=name, role=role, permitted=False,
                    duration_ms=(time.perf_counter() - started) * 1000.0, argument_keys=argument_keys,
                    unknown_key_count=unknown_key_count,
                )
                return [types.TextContent(type="text", text=f"Tool '{name}' is not permitted for role '{role}'.")]
        except Exception as e:  # noqa: BLE001
            logger.error("Policy lookup failed for tool '%s': %s", name, e)
            _log_tool_call(
                name=name, role=role, permitted=False,
                duration_ms=(time.perf_counter() - started) * 1000.0, argument_keys=argument_keys,
                unknown_key_count=unknown_key_count,
            )
            return [types.TextContent(type="text", text=f"Tool '{name}' denied: policy lookup failed.")]

        args = _normalize_tool_arguments(arguments, name)

        # The schema gate `ToolDispatcher.dispatch` applies, applied here too:
        # this path calls the handlers directly, so without it an MCP
        # `write_file` missing `content` still reached the executor and
        # `additionalProperties: false` was advertised, not enforced (Copilot
        # review on PR #86). A refused call never starts the handler thread.
        schema = _PARAMETER_SCHEMAS.get(name)
        reason = invalid_arguments_reason(schema, args) if schema is not None else None
        if reason is not None:
            _log_tool_call(
                name=name, role=role, permitted=False,
                duration_ms=(time.perf_counter() - started) * 1000.0, argument_keys=argument_keys,
                unknown_key_count=unknown_key_count,
            )
            return [types.TextContent(type="text", text=f"Error: invalid_arguments: {reason}")]

        try:
            handler = tool_handlers.get(name)
            if handler is None:
                raise ValueError(f"Unknown tool: {name}")
            # Every handler is synchronous and `run_command` blocks on
            # `subprocess.run`; awaited inline, one long command froze the
            # transport for every other request on the loop (audit M9). The
            # default executor keeps the loop free to serve them.
            result = await asyncio.to_thread(handler, args)
        except Exception as e:
            logger.exception("Error executing tool %s", name)
            result = f"Error executing tool '{name}': {e}"

        # The static role check above is necessary, not sufficient: the shared
        # handler consults the read/write policy and the broker PDP, and a
        # denial there must be logged as one (Copilot review on PR #86).
        _log_tool_call(
            name=name, role=role, permitted=not _handler_refused(result),
            duration_ms=(time.perf_counter() - started) * 1000.0, argument_keys=argument_keys,
            unknown_key_count=unknown_key_count,
        )
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
