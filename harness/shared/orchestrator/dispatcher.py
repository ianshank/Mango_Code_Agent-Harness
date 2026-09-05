"""Tool dispatching and execution for the Mango MAS orchestrator."""

from __future__ import annotations

import logging
import time
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

from harness.shared.agent_authority import tool_is_permitted
from harness.shared.governance.broker import ExecutionBroker
from harness.shared.meta_tools import hypothesis_register, knowledge_gap_log
from harness.shared.tool_arg_validation import invalid_arguments_reason, parameter_schemas
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
from harness.shared.tool_result_format import (
    DENIED_ROLE,
    INVALID_ARGUMENTS,
    RAISED,
    UNKNOWN_TOOL,
    denied,
    is_permitted,
    tool_outcome,
)
from harness.shared.tool_schemas import NEMOTRON_TOOLS

logger = logging.getLogger(__name__)


class ToolDispatcher:
    """Dispatches tool calls dynamically based on schema definitions."""

    def __init__(
        self,
        workspace_dir: Path,
        broker: ExecutionBroker,
        tool_timeout: int | None = None,
        tools: list[dict[str, Any]] | None = None,
        policy_path: Path | None = None,
    ) -> None:
        self.workspace_dir = workspace_dir
        self.broker = broker
        self.tool_timeout = tool_timeout
        self.policy_path = policy_path
        self.active_role: str = "nemotron-reasoner"
        # The schemas the model is shown are the schemas its arguments are
        # checked against (2026 standards audit H7): one declaration, in
        # `tool_schemas`, read by both the offer and the check.
        self.parameter_schemas: dict[str, Mapping[str, Any]] = parameter_schemas(
            NEMOTRON_TOOLS if tools is None else tools
        )

        self.tool_handlers: dict[str, Callable[[dict[str, Any]], str]] = {
            "write_file": lambda args: self._execute_write_file(args.get("filepath") or "", args.get("content") or ""),
            "read_file": lambda args: self._execute_read_file(
                args.get("filepath") or "", args.get("start_line"), args.get("end_line")
            ),
            "apply_patch": lambda args: self._execute_apply_patch(
                args.get("filepath") or "", args.get("old_text") or "", args.get("new_text") or ""
            ),
            "run_command": lambda args: self._execute_run_command(args.get("command") or ""),
            "knowledge_gap_log": lambda args: knowledge_gap_log(
                args.get("question") or "",
                args.get("what_needed") or "",
                args.get("proposed_approach") or "",
                workspace_dir=self.workspace_dir,
                policy_path=self.policy_path,
            ),
            "hypothesis_register": lambda args: hypothesis_register(
                args.get("claim") or "",
                args.get("reasoning") or "",
                args.get("confidence", DEFAULT_HYPOTHESIS_CONFIDENCE),
                workspace_dir=self.workspace_dir,
                policy_path=self.policy_path,
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
            return denied(f"Denied: {denial}")
        return execute_write_file(self.workspace_dir, filepath, content)

    def _execute_read_file(self, filepath: str, start_line: int | None = None, end_line: int | None = None) -> str:
        return execute_read_file(self.workspace_dir, filepath, start_line, end_line)

    def _execute_apply_patch(self, filepath: str, old_text: str, new_text: str) -> str:
        denial = authorize_write(self.broker, self.active_role, filepath)
        if denial is not None:
            logger.warning("Refused patch for role %s: %s", self.active_role, denial)
            return denied(f"Denied: {denial}")
        return execute_apply_patch(self.workspace_dir, filepath, old_text, new_text)

    def _execute_run_command(self, command: str) -> str:
        return execute_run_command(
            self.broker,
            self.active_role,
            self.workspace_dir,
            command,
            self.tool_timeout,
        )

    def _argument_denial(self, func_name: str, args: Mapping[str, Any]) -> str | None:
        """Why the call must not reach its handler, or ``None`` when it may.

        A handled tool with no advertised schema is refused too: the schema is
        what the model was told, and a call that can only be checked against
        nothing is not a call this module can vouch for.
        """
        schema = self.parameter_schemas.get(func_name)
        if schema is None:
            return f"tool {func_name!r} advertises no parameter schema"
        return invalid_arguments_reason(schema, args)

    def dispatch(
        self,
        messages: list[dict[str, Any]],
        tool_calls: list[dict[str, Any]],
        run_id: str | None = None,
    ) -> None:
        """Execute each requested tool via the registry and append the results
        to ``messages`` so they feed back to the model.

        One structured event per call carries ``run_id``, the tool name, whether
        the call was permitted, its outcome and its duration -- and nothing
        from the arguments or the result (2026 standards audit H6). Denials
        are logged at WARNING, the rest at DEBUG.

        The outcome is the handler's own, not "the handler returned": the
        executors report a policy denial or a failure as text for the model,
        and that text carries its outcome (``ToolText``), so a refused write
        is logged as the denial it was (Copilot review on PR #86).
        """
        for tc in tool_calls:
            started = time.monotonic()
            tc_id = tc.get("id")
            func_obj = tc.get("function") or {}
            func_name = str(func_obj.get("name") or "")
            args = _normalize_tool_arguments(func_obj.get("arguments"), func_name)

            handler = self.tool_handlers.get(func_name)
            if handler is not None and not tool_is_permitted(self.active_role, func_name):
                outcome = DENIED_ROLE
                tool_result = f"Error: tool '{func_name}' is not available to the {self.active_role} role"
            elif handler is None:
                outcome = UNKNOWN_TOOL
                tool_result = f"Error: Unknown tool '{func_name}'"
            else:
                reason = self._argument_denial(func_name, args)
                if reason is not None:
                    outcome = INVALID_ARGUMENTS
                    tool_result = f"Error: invalid_arguments: {reason}"
                else:
                    try:
                        tool_result = handler(args)
                        outcome = tool_outcome(tool_result)
                    except Exception as exc:
                        logger.exception("Tool %s raised", func_name)
                        tool_result = f"Error executing tool '{func_name}': {exc}"
                        outcome = RAISED

            permitted = is_permitted(outcome)
            event = logger.debug if permitted else logger.warning
            event(
                "tool call %s: %s for role %s",
                func_name,
                outcome,
                self.active_role,
                extra={
                    "event": "tool_call",
                    "run_id": run_id,
                    "tool": func_name,
                    "role": self.active_role,
                    "permitted": permitted,
                    "outcome": outcome,
                    "duration_ms": int((time.monotonic() - started) * 1000),
                },
            )
            logger.info("Executed %s. Result length: %d", func_name, len(tool_result))
            messages.append({"role": "tool", "tool_call_id": tc_id, "name": func_name, "content": tool_result})
