"""Tool dispatching and execution for the Mango MAS orchestrator."""

from __future__ import annotations

import logging
from collections.abc import Callable
from pathlib import Path
from typing import Any

from harness.shared.agent_authority import tool_is_permitted
from harness.shared.governance.broker import ExecutionBroker
from harness.shared.meta_tools import hypothesis_register, knowledge_gap_log
from harness.shared.tool_dispatch import (
    DEFAULT_HYPOTHESIS_CONFIDENCE,
    _normalize_tool_arguments,
)
from harness.shared.tool_executors import (
    authorize_write,
    execute_apply_patch,
    execute_read_file,
    execute_run_command,
    execute_write_file,
)

logger = logging.getLogger(__name__)


class ToolDispatcher:
    """Dispatches tool calls dynamically based on schema definitions."""

    def __init__(
        self,
        workspace_dir: Path,
        broker: ExecutionBroker,
        tool_timeout: int | None = None,
    ) -> None:
        self.workspace_dir = workspace_dir
        self.broker = broker
        self.tool_timeout = tool_timeout
        self.active_role: str = "nemotron-reasoner"

        self.tool_handlers: dict[str, Callable[[dict[str, Any]], str]] = {
            "write_file": lambda args: self._execute_write_file(
                args.get("filepath") or "", args.get("content") or ""
            ),
            "read_file": lambda args: self._execute_read_file(
                args.get("filepath") or "", args.get("start_line"), args.get("end_line")
            ),
            "apply_patch": lambda args: self._execute_apply_patch(
                args.get("filepath") or "", args.get("old_text") or "", args.get("new_text") or ""
            ),
            "run_command": lambda args: self._execute_run_command(args.get("command") or ""),
            "knowledge_gap_log": lambda args: knowledge_gap_log(
                args.get("question") or "", args.get("what_needed") or "", args.get("proposed_approach") or ""
            ),
            "hypothesis_register": lambda args: hypothesis_register(
                args.get("claim") or "", args.get("reasoning") or "",
                args.get("confidence", DEFAULT_HYPOTHESIS_CONFIDENCE),
            ),
        }

    def set_active_role(self, role: str) -> None:
        self.active_role = role

    def _execute_write_file(self, filepath: str, content: str) -> str:
        # The policy decision point is asked before the write policy, because the
        # two answer different questions: `write_denial_reason` decides whether
        # *anyone* may write this path, and the PDP decides whether *this role*
        # may write at all. Only the MCP transport asked the second one, so the
        # verifier -- which holds no `write` action -- was refused there and
        # permitted here (R-CQ-5).
        denial = authorize_write(self.broker, self.active_role, filepath)
        if denial is not None:
            logger.warning("Refused write for role %s: %s", self.active_role, denial)
            return f"Denied: {denial}"
        return execute_write_file(self.workspace_dir, filepath, content)

    def _execute_read_file(
        self, filepath: str, start_line: int | None = None, end_line: int | None = None
    ) -> str:
        return execute_read_file(self.workspace_dir, filepath, start_line, end_line)

    def _execute_apply_patch(self, filepath: str, old_text: str, new_text: str) -> str:
        denial = authorize_write(self.broker, self.active_role, filepath)
        if denial is not None:
            logger.warning("Refused patch for role %s: %s", self.active_role, denial)
            return f"Denied: {denial}"
        return execute_apply_patch(self.workspace_dir, filepath, old_text, new_text)

    def _execute_run_command(self, command: str) -> str:
        return execute_run_command(
            self.broker,
            self.active_role,
            self.workspace_dir,
            command,
            self.tool_timeout,
        )

    def dispatch(
        self, messages: list[dict[str, Any]], tool_calls: list[dict[str, Any]]
    ) -> None:
        """Execute each requested tool via the registry and append the results
        to ``messages`` so they feed back to the model."""
        for tc in tool_calls:
            tc_id = tc.get("id")
            func_obj = tc.get("function") or {}
            func_name = str(func_obj.get("name") or "")
            args = _normalize_tool_arguments(func_obj.get("arguments"), func_name)

            handler = self.tool_handlers.get(func_name)
            if handler is not None and not tool_is_permitted(self.active_role, func_name):
                logger.warning(
                    "Refused tool %s for role %s: not permitted by the authority model",
                    func_name, self.active_role,
                )
                handler = None
                tool_result = (
                    f"Error: tool '{func_name}' is not available to the {self.active_role} role"
                )
            elif handler is None:
                tool_result = f"Error: Unknown tool '{func_name}'"
            else:
                try:
                    tool_result = handler(args)
                except Exception as exc:
                    logger.exception("Tool %s raised", func_name)
                    tool_result = f"Error executing tool '{func_name}': {exc}"

            logger.info("Executed %s. Result length: %d", func_name, len(tool_result))
            messages.append({"role": "tool", "tool_call_id": tc_id, "name": func_name, "content": tool_result})
