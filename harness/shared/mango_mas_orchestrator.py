"""Multi-Agent System (MAS) orchestrator for autonomous agent execution.

Orchestrates planner, reasoner, and verifier roles with governed tool execution,
credential redaction, loop outcomes, and policy-sourced limits.

This file serves as a backwards-compatible facade. The actual orchestration
logic has been decomposed into the `harness.shared.orchestrator` package.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from harness.shared.agent_authority import execution_identity
from harness.shared.agent_prompts import (
    AUTONOMOUS_AGENT_GUARDRAIL as AUTONOMOUS_AGENT_GUARDRAIL,
)
from harness.shared.agent_prompts import (
    PERMITTED_HOOK_NAMES as PERMITTED_HOOK_NAMES,
)
from harness.shared.agent_prompts import (
    PLANNER_PROMPT_TEMPLATE as PLANNER_PROMPT_TEMPLATE,
)
from harness.shared.agent_prompts import (
    PRE_RUN_HOOK as PRE_RUN_HOOK,
)
from harness.shared.agent_prompts import (
    REASONER_PROMPT_TEMPLATE as REASONER_PROMPT_TEMPLATE,
)
from harness.shared.agent_prompts import (
    TASK_LOG_PREVIEW_CHARS as TASK_LOG_PREVIEW_CHARS,
)
from harness.shared.agent_prompts import (
    VERIFIER_PROMPT_TEMPLATE as VERIFIER_PROMPT_TEMPLATE,
)
from harness.shared.governance.broker import ExecutionBroker
from harness.shared.governance.verdict import LoopOutcome, Verdict
from harness.shared.governance.verification import VerificationRunner

# For backwards compatibility with tests mocking complete_chat on this module
from harness.shared.nemotron_bridge import complete_chat as complete_chat

# New decomposed internals
from harness.shared.orchestrator.dispatcher import ToolDispatcher
from harness.shared.orchestrator.hook_runner import HookRunner
from harness.shared.orchestrator.loop import ExecutionLoop
from harness.shared.policy_loader import max_tool_calls_per_task, orchestrator_defaults
from harness.shared.tool_budget import ToolBudget
from harness.shared.tool_dispatch import (
    DEFAULT_HYPOTHESIS_CONFIDENCE as DEFAULT_HYPOTHESIS_CONFIDENCE,
)
from harness.shared.tool_dispatch import (
    _normalize_tool_arguments as _normalize_tool_arguments,
)
from harness.shared.tool_schemas import NEMOTRON_TOOLS as NEMOTRON_TOOLS

logger = logging.getLogger(__name__)


class MangoMASOrchestrator:
    """
    Orchestrates the .mango Multi-Agent System using the NVIDIA Nemotron API.
    Implements a ReAct loop to intercept tool_calls and execute them locally
    via subprocess and file I/O.

    NOTE: V2.4.0 extracted the internal execution loops into the `harness.shared.orchestrator`
    package. This class remains as a backwards-compatible facade for external tooling.
    """

    def __init__(
        self,
        workspace_dir: Path,
        api_key: str | None = None,
        model: str | None = None,
        max_iterations: int | None = None,
        api_timeout: int | None = None,
        tool_timeout: int | None = None,
        broker: ExecutionBroker | None = None,
        active_role: str = "nemotron-reasoner",
        verification: VerificationRunner | None = None,
        verification_cwd: Path | None = None,
    ) -> None:
        limits = orchestrator_defaults()
        self.workspace_dir = workspace_dir
        self.api_key = api_key
        self.model = model
        self.max_iterations = max_iterations if max_iterations is not None else limits["max_iterations"]
        self.api_timeout = api_timeout if api_timeout is not None else limits["api_timeout_sec"]
        self.tool_timeout = tool_timeout if tool_timeout is not None else limits["tool_timeout_sec"]
        # The verification run is a test suite, not a model round-trip, so it
        # has its own ceiling (2026 standards audit H16). Passing `api_timeout`
        # here made a slow runner's passing suite a BLOCKED/harness_fault.
        self.verification_timeout = limits["verification_timeout_sec"]
        self.max_tool_calls_per_task = max_tool_calls_per_task()
        self._broker = broker or ExecutionBroker()
        self._verification = verification or VerificationRunner(
            self._broker, execution_identity("verifier"), timeout=self.verification_timeout
        )
        self._verification_cwd = verification_cwd if verification_cwd is not None else workspace_dir
        self._active_role = active_role
        self.agents_dir = self.workspace_dir / ".mango" / "agents"
        self.hooks_dir = self.workspace_dir / ".mango" / "hooks"

        self.dispatcher = ToolDispatcher(
            workspace_dir=self.workspace_dir,
            broker=self._broker,
            tool_timeout=self.tool_timeout,
        )
        self.dispatcher.set_active_role(self._active_role)

        self.hook_runner = HookRunner(
            workspace_dir=self.workspace_dir,
            hooks_dir=self.hooks_dir,
            tool_timeout=self.tool_timeout,
        )

        import sys
        self.execution_loop = ExecutionLoop(
            workspace_dir=self.workspace_dir,
            agents_dir=self.agents_dir,
            dispatcher=self.dispatcher,
            hook_runner=self.hook_runner,
            verification=self._verification,
            verification_cwd=self._verification_cwd,
            api_key=self.api_key,
            model=self.model,
            max_iterations=self.max_iterations,
            api_timeout=self.api_timeout,
            max_tool_calls_per_task=self.max_tool_calls_per_task,
            complete_chat_fn=sys.modules[__name__].complete_chat,
        )

    # conversation_history is part of the public surface R-ORCH-4 pins. The
    # private pass-throughs that used to sit here (_tool_handlers, _run_hook,
    # _dispatch_tool_calls) existed only so tests could poke the facade; those
    # tests now address `dispatcher` and `hook_runner` directly (R-TDH-18).
    @property
    def conversation_history(self) -> list[dict[str, Any]]:
        return self.execution_loop.conversation_history

    @property
    def run_id(self) -> str | None:
        """The identifier every structured event of the current loop carries.

        Minted by ``execute_loop``; ``None`` until a loop or agent has run.
        """
        return self.execution_loop.run_id

    def load_agent_prompt(self, agent_name: str) -> str:
        return self.execution_loop.load_agent_prompt(agent_name)

    def _execute_write_file(self, filepath: str, content: str) -> str:
        return self.dispatcher._execute_write_file(filepath, content)

    def _execute_read_file(self, filepath: str, start_line: int | None = None, end_line: int | None = None) -> str:
        return self.dispatcher._execute_read_file(filepath, start_line, end_line)

    def _execute_apply_patch(self, filepath: str, old_text: str, new_text: str) -> str:
        return self.dispatcher._execute_apply_patch(filepath, old_text, new_text)

    def _execute_run_command(self, command: str) -> str:
        return self.dispatcher._execute_run_command(command)

    def _finalize_response(self, messages: list[dict[str, Any]], content: Any) -> str:
        return self.execution_loop._finalize_response(messages, content)

    def _dump_debug_history(self, agent_name: str) -> None:
        self.execution_loop._dump_debug_history(agent_name)

    def execute_agent(
        self,
        agent_name: str,
        task: str,
        tools: list[dict[str, Any]] | None = None,
        budget: ToolBudget | None = None,
    ) -> str:
        return self.execution_loop.execute_agent(agent_name, task, tools, budget)

    def execute_loop(self, initial_task: str) -> LoopOutcome:
        return self.execution_loop.execute_loop(initial_task)

    def _harness_verdict(self) -> Verdict:
        return self.execution_loop._harness_verdict()

    def execute_sequential_thinking_loop(self, initial_task: str) -> str:
        return self.execution_loop.execute_loop(initial_task).verifier_message


__all__ = [
    "AUTONOMOUS_AGENT_GUARDRAIL",
    "DEFAULT_HYPOTHESIS_CONFIDENCE",
    "MangoMASOrchestrator",
    "NEMOTRON_TOOLS",
    "PERMITTED_HOOK_NAMES",
    "PLANNER_PROMPT_TEMPLATE",
    "PRE_RUN_HOOK",
    "REASONER_PROMPT_TEMPLATE",
    "TASK_LOG_PREVIEW_CHARS",
    "VERIFIER_PROMPT_TEMPLATE",
    "_normalize_tool_arguments",
]
