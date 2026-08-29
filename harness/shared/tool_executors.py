"""Isolated executors for local tool operations (file writing & brokered command execution)."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING, Any

from harness.shared.agent_authority import execution_identity
from harness.shared.tool_result_format import format_execution_result
from harness.shared.write_policy import write_denial_reason

if TYPE_CHECKING:
    from harness.shared.governance.broker import ExecutionBroker

logger = logging.getLogger(__name__)


def execute_write_file(workspace_dir: Path, filepath: str, content: str) -> str:
    """Local tool implementation to write a file with workspace confinement & write policy.

    Two checks, in order:
    1. Confinement keeps the write inside the workspace;
    2. Write policy keeps it off the control surface within the workspace.
    """
    workspace = workspace_dir.resolve()
    target_path = (workspace / filepath).resolve()

    if not target_path.is_relative_to(workspace):
        logger.warning("Denied write outside the workspace: %s", filepath)
        return f"Error writing file {filepath}: path escapes workspace"

    denial = write_denial_reason(str(target_path.relative_to(workspace)))
    if denial is not None:
        logger.warning("Denied write to a governed path: %s (%s)", filepath, denial)
        return f"Error writing file {filepath}: {denial}"

    try:
        target_path.parent.mkdir(parents=True, exist_ok=True)
        target_path.write_text(content, encoding="utf-8")
        return f"Success: Wrote {len(content)} characters to {target_path.resolve()}"
    except Exception as e:  # noqa: BLE001 - a tool must always answer its call with a string
        return f"Error writing file {filepath}: {str(e)}"


def execute_run_command(
    broker: ExecutionBroker,
    active_role: str,
    workspace_dir: Path,
    command: str,
    timeout: int | None = None,
) -> str:
    """Run a command through the approved execution broker (INV-8)."""
    kwargs: dict[str, Any] = {
        "context": {"agent_id": execution_identity(active_role)},
        "cwd": workspace_dir,
    }
    if timeout is not None:
        kwargs["timeout"] = timeout
    result = broker.execute_command(command, **kwargs)
    if result.status == "BLOCKED":
        logger.warning("Broker denied command for role %s: %s", active_role, result.reason)
    return format_execution_result(result)


__all__ = [
    "execute_run_command",
    "execute_write_file",
]
