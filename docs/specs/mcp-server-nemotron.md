# Spec: NemotronClient MCP Server Integration

## Problem statement

The current `NemotronClient` and `nemotron_bridge.py` are tightly coupled within the `harness/shared/` orchestration layer. External IDEs (such as Claude Code, Cursor, and the Antigravity IDE) cannot natively leverage the live NVIDIA Nemotron API endpoints for multi-domain triage or sequential thinking loops without a standard integration interface. Packaging the client as a Model Context Protocol (MCP) server enables standardized integration across the AI ecosystem and fulfills milestone 2.1 defined in `NEXT_STEPS.md`.

## Requirements

- R-MCP-1: The system MUST implement an independent MCP server (`harness/shared/mcp_server.py`) that exposes the standard MAS tools via the STDIO transport protocol. This server is a tool-only integration layer; it does not wrap `NemotronClient` directly but exposes the same tools available to `NemotronClient` through the brokered execution path.
- R-MCP-2: The MCP server MUST expose the standard MAS tools (e.g., `write_file`, `read_file`, `apply_patch`, `run_command`) mapped dynamically from the existing `tool_schemas.py` and `tool_executors.py`, filtered to the active role's permitted tool set via `tools_for_role`.
- C-MCP-1: The MCP server MUST NOT bypass the `ExecutionBroker` or `pretooluse_guard.py` when handling tool execution requests; all operations must adhere to the existing fail-closed security posture (INV-8, INV-10). Write and patch mutations must be pre-authorized via the broker's PDP before the local executor is invoked.

## Acceptance criteria

- [x] AC-1: The `mcp_server.py` starts and successfully initializes an MCP STDIO session without errors. — verified by `pytest -k test_run_mcp_server`
      · stage: `make test-python` (R-MCP-1)
- [x] AC-2: Tool descriptions retrieved via the MCP server correctly match the schemas defined in `tool_schemas.py`, filtered by the active role. — verified by `pytest -k test_mcp_server_tools_sync_by_role`
      · stage: `make test-python` (R-MCP-2)
- [x] AC-3: Tool execution requests routed through the MCP server correctly hit the `ExecutionBroker` PDP and are denied if the broker blocks the write. — verified by `pytest -k test_mcp_server_broker_pdp_blocks_write`
      · stage: `make test-python` (C-MCP-1)

## Steps

1. Modify `harness/shared/mcp_server.py` (new) — produces the MCP server entry point wrapping `nemotron_bridge.py` and `tool_dispatch.py`.
2. Modify `harness/shared/tests/test_mcp_server.py` (new) — produces unit tests for MCP server instantiation and tool execution routing.

## Files touched

- `harness/shared/mcp_server.py`
- `harness/shared/tests/test_mcp_server.py`

## Invariants touched

- INV-8, INV-9, INV-10: Strict adherence to existing `ExecutionBroker` limits. The MCP server acts merely as an alternate transport interface, not a privileged executor.

## Validation matrix

- `make test-python`
- `make ci`
- coverage target: >90% lines

## Backward compatibility

This is a strictly additive feature. Existing local integrations (via `nemotron_bridge.py`) and API gateways (`harness/api_server/main.py`) remain untouched.

## Open questions

- Should the MCP server require an explicit API key passed via environment variables, or should it rely entirely on the local `.env` configuration shared by the MAS orchestrator?
