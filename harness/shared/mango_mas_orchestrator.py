"""Multi-Agent System (MAS) orchestrator for autonomous agent execution.

Orchestrates planner, reasoner, and verifier roles with governed tool execution,
credential redaction, loop outcomes, and policy-sourced limits.
"""

from __future__ import annotations

import logging
import os
import subprocess
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from harness.shared.agent_authority import (
    execution_identity,
    tool_is_permitted,
    tools_for_role,
)
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
from harness.shared.debug_dump import credential_env_names, write_dump
from harness.shared.governance.broker import ExecutionBroker
from harness.shared.governance.verdict import LoopOutcome, Verdict, derive_verdict, not_configured, reentrant
from harness.shared.governance.verification import VerificationRunner
from harness.shared.meta_tools import hypothesis_register, knowledge_gap_log
from harness.shared.nemotron_bridge import complete_chat
from harness.shared.policy_loader import max_tool_calls_per_task, orchestrator_defaults
from harness.shared.shadow_planner import ShadowContext, run_shadow_comparison, shadow_planner_enabled
from harness.shared.tool_budget import ToolBudget
from harness.shared.tool_dispatch import (
    DEFAULT_HYPOTHESIS_CONFIDENCE as DEFAULT_HYPOTHESIS_CONFIDENCE,
)
from harness.shared.tool_dispatch import (
    _normalize_tool_arguments as _normalize_tool_arguments,
)
from harness.shared.tool_executors import (
    execute_apply_patch,
    execute_read_file,
    execute_run_command,
    execute_write_file,
)
from harness.shared.tool_schemas import NEMOTRON_TOOLS as NEMOTRON_TOOLS

logger = logging.getLogger(__name__)


class MangoMASOrchestrator:
    """
    Orchestrates the .mango Multi-Agent System using the NVIDIA Nemotron API.
    Implements a ReAct loop to intercept tool_calls and execute them locally
    via subprocess and file I/O.
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
    ) -> None:
        # Operational limits come from governance-policy.json (the
        # `orchestrator` block); explicit constructor arguments still override
        # (spec: policy-single-source). The policy loader's built-in defaults
        # mirror the previous literals, so adopters without a policy file see
        # identical behavior.
        limits = orchestrator_defaults()
        self.workspace_dir = workspace_dir
        self.api_key = api_key
        self.model = model
        self.max_iterations = max_iterations if max_iterations is not None else limits["max_iterations"]
        self.api_timeout = api_timeout if api_timeout is not None else limits["api_timeout_sec"]
        self.tool_timeout = tool_timeout if tool_timeout is not None else limits["tool_timeout_sec"]
        self.max_tool_calls_per_task = max_tool_calls_per_task()
        # Injected rather than imported at the call site so an adopter can supply
        # their own broker -- `harness/CONTRACT.md` places the authoritative
        # broker outside the governed repository -- and so tests can drive the
        # unavailable path without spawning anything.
        self._broker = broker or ExecutionBroker()
        # The check that earns a verdict; injected so a caller can retarget it.
        self._verification = verification or VerificationRunner(
            self._broker, execution_identity("verifier"), timeout=self.api_timeout
        )
        # `execute_agent` overrides this per turn. The default is the implementer
        # contract, which is what a directly-driven orchestrator is doing; it is
        # not the widest role -- it holds neither external_write, destructive nor
        # secret_access.
        self._active_role = active_role
        self.agents_dir = self.workspace_dir / ".mango" / "agents"
        self.hooks_dir = self.workspace_dir / ".mango" / "hooks"
        self.conversation_history: list[dict[str, Any]] = []
        # Tool dispatch registry: every function name declared in
        # NEMOTRON_TOOLS must have an entry here (pinned by a unit test), so
        # declaration and dispatch cannot drift apart.
        self._tool_handlers: dict[str, Callable[[dict[str, Any]], str]] = {
            "write_file": lambda args: self._execute_write_file(args.get("filepath", ""), args.get("content", "")),
            "read_file": lambda args: self._execute_read_file(
                args.get("filepath", ""), args.get("start_line"), args.get("end_line")
            ),
            "apply_patch": lambda args: self._execute_apply_patch(
                args.get("filepath", ""), args.get("old_text", ""), args.get("new_text", "")
            ),
            "run_command": lambda args: self._execute_run_command(args.get("command", "")),
            "knowledge_gap_log": lambda args: knowledge_gap_log(
                args.get("question", ""), args.get("what_needed", ""), args.get("proposed_approach", "")
            ),
            "hypothesis_register": lambda args: hypothesis_register(
                args.get("claim", ""), args.get("reasoning", ""),
                args.get("confidence", DEFAULT_HYPOTHESIS_CONFIDENCE),
            ),
        }

    def _run_hook(self, hook_name: str, **kwargs: Any) -> None:
        """Executes a pre- or post- hook script if it exists.

        The name is checked against the set the orchestrator can legitimately
        construct. `hooks_dir` is inside the workspace, and in the deployed
        configuration the workspace is the repository -- so "run whatever `.sh`
        matches this name" is a host-execution primitive keyed on a string that
        `execute_agent` interpolates a caller-supplied role into. The write
        policy already refuses to *create* a file there; this refuses to *run*
        one, and the two failures required to reach host code are then
        independent rather than sequential.
        """
        if hook_name not in PERMITTED_HOOK_NAMES:
            # Raise rather than skip: an unrecognised name is the orchestrator
            # asking for something it never legitimately asks for. Returning
            # quietly would make a typo look like a hook that simply is not
            # installed -- the failure mode this repository keeps finding.
            raise ValueError(
                f"refusing to run unrecognised hook {hook_name!r}; "
                f"permitted names are {sorted(PERMITTED_HOOK_NAMES)}"
            )
        hook_path = self.hooks_dir / f"{hook_name}.sh"
        if hook_path.exists():
            logger.info("Executing hook: %s", hook_name)
            try:
                # `agent-policy.json` declares
                # `secrets_may_not_be_propagated_to_subagents: true`, and nothing
                # enforced it: every hook inherited the full environment, so a
                # hook ran on the host holding NVIDIA_API_KEY, API_SERVER_KEY and
                # AGENT_EVIDENCE_KEY. The hooks this repository ships need none of
                # them -- `pre-nemotron-run.sh` runs validate_invariants.py.
                denied = set(credential_env_names())
                env = {k: v for k, v in os.environ.items() if k not in denied}
                for k, v in kwargs.items():
                    env[f"MANGO_HOOK_{k.upper()}"] = str(v)
                try:
                    hook_arg = hook_path.relative_to(self.workspace_dir).as_posix()
                except ValueError:
                    hook_arg = hook_path.as_posix()
                subprocess.run(
                    ["bash", hook_arg], cwd=self.workspace_dir, env=env, check=True, timeout=self.tool_timeout
                )
            except Exception:
                logger.exception("Hook %s failed", hook_name)
                raise

    def load_agent_prompt(self, agent_name: str) -> str:
        """Dynamically loads the agent instructions from the .mango directory."""
        agent_file = self.agents_dir / f"{agent_name}.md"
        if not agent_file.exists():
            raise FileNotFoundError(f"Agent definition not found: {agent_file}")
        return agent_file.read_text(encoding="utf-8")

    def _execute_write_file(self, filepath: str, content: str) -> str:
        """Local tool implementation to write a file."""
        return execute_write_file(self.workspace_dir, filepath, content)

    def _execute_read_file(
        self, filepath: str, start_line: int | None = None, end_line: int | None = None
    ) -> str:
        """Local tool implementation to read a file."""
        return execute_read_file(self.workspace_dir, filepath, start_line, end_line)

    def _execute_apply_patch(self, filepath: str, old_text: str, new_text: str) -> str:
        """Local tool implementation to replace one unique substring in a file."""
        return execute_apply_patch(self.workspace_dir, filepath, old_text, new_text)

    def _execute_run_command(self, command: str) -> str:
        """Run a command through the approved execution broker (INV-8)."""
        return execute_run_command(
            self._broker,
            self._active_role,
            self.workspace_dir,
            command,
            self.tool_timeout,
        )

    def _dispatch_tool_calls(
        self, messages: list[dict[str, Any]], tool_calls: list[dict[str, Any]]
    ) -> None:
        """Execute each requested tool via the registry and append the results
        to ``messages`` so they feed back to the model."""
        for tc in tool_calls:
            tc_id = tc.get("id")
            func_obj = tc.get("function") or {}
            func_name = str(func_obj.get("name") or "")
            args = _normalize_tool_arguments(func_obj.get("arguments"), func_name)

            handler = self._tool_handlers.get(func_name)
            if handler is not None and not tool_is_permitted(self._active_role, func_name):
                # Filtering the advertised schema decides what the model is told
                # about; it does not decide what runs. The verifier's schema omits
                # `write_file`, but the name is in `conversation_history` from the
                # reasoner's turn, and this dispatcher looked handlers up by name.
                # R-AC-8 -- "the role that judges the work cannot edit the work" --
                # was enforced by omission from a prompt until this check existed.
                logger.warning(
                    "Refused tool %s for role %s: not permitted by the authority model",
                    func_name, self._active_role,
                )
                handler = None
                tool_result = (
                    f"Error: tool '{func_name}' is not available to the {self._active_role} role"
                )
            elif handler is None:
                tool_result = f"Error: Unknown tool '{func_name}'"
            else:
                try:
                    tool_result = handler(args)
                except Exception as exc:
                    # The wire protocol requires exactly one tool message per
                    # requested tool call. An escaping handler exception (a
                    # meta-tool lock timeout, say) would abandon execute_agent
                    # mid-loop: the post-run hook never fires and the model's
                    # tool_calls message is left unanswered, which the API
                    # rejects on the next turn. Report the failure as the tool's
                    # result instead -- the same contract _execute_write_file
                    # and _execute_run_command already follow.
                    logger.exception("Tool %s raised", func_name)
                    tool_result = f"Error executing tool '{func_name}': {exc}"

            logger.info("Executed %s. Result length: %d", func_name, len(tool_result))
            messages.append({"role": "tool", "tool_call_id": tc_id, "name": func_name, "content": tool_result})

    def _finalize_response(self, messages: list[dict[str, Any]], content: Any) -> str:
        """Derive the agent's final answer once the model stops requesting tools."""
        final_content = str(content or "")

        # Fallback if model just returns an empty string but we had tool executions
        if not final_content.strip() and len(messages) > 3:
            last_msg = messages[-2]  # the tool result is immediately before the current model empty message
            if last_msg.get("role") == "tool":
                final_content = f"Completed via tool execution. Last tool result: {last_msg.get('content')}"

        self.conversation_history.append({"role": "assistant", "content": final_content})
        return final_content

    def _dump_debug_history(self, agent_name: str) -> None:
        """Write the conversation history (credentials redacted) to a temp file
        when MANGO_DEBUG_DUMP=1.

        Redaction lives in ``debug_dump`` and no longer depends on
        ``self.api_key`` being set: it usually is not, because the bridge
        resolves the credential downstream, which meant the previous
        implementation wrote the history unredacted.
        """
        write_dump(self.conversation_history, agent_name, api_key=self.api_key)

    def execute_agent(
        self,
        agent_name: str,
        task: str,
        tools: list[dict[str, Any]] | None = None,
        budget: ToolBudget | None = None,
    ) -> str:
        """
        Executes a single agent's reasoning loop using ReAct (Reasoning and Acting).
        Returns the final string output from the agent.
        """
        # The tool handlers are zero-argument closures over `self`, so the acting
        # role has to be recorded here for `_execute_run_command` to name it. A
        # verifier turn must be evaluated as the verifier, not as whatever role
        # ran last.
        self._active_role = agent_name
        self._run_hook(PRE_RUN_HOOK, task=task, agent=agent_name)
        logger.info("Executing agent [%s] with task: %s...", agent_name, task[:TASK_LOG_PREVIEW_CHARS])

        messages: list[dict[str, Any]] = [
            {"role": "system", "content": self.load_agent_prompt(agent_name)},
            {"role": "user", "content": task},
        ]

        # Keep track of conversation for debugging
        self.conversation_history.extend(messages)

        # Default exposure is derived from `agent-policy.json`, not the full
        # schema. Defaulting to NEMOTRON_TOOLS is how the verifier came to hold
        # `write_file` while every canonical contract it maps to denies
        # implementation changes (spec R-AC-8). An explicit `tools=` argument still
        # wins, so a caller can narrow further but never widen by omission.
        active_tools = tools if tools is not None else tools_for_role(agent_name, NEMOTRON_TOOLS)
        # Cumulative across the task when the caller supplies one, from
        # agent_defaults.max_tool_calls_per_task. `None` means a fresh budget for
        # this turn alone, which is what every caller had before the budget became
        # an argument (see tool_budget.ToolBudget).
        turn_budget = budget if budget is not None else ToolBudget(self.max_tool_calls_per_task)

        for _iteration in range(self.max_iterations):
            try:
                kwargs: dict[str, Any] = {
                    "messages": messages,
                    "tools": active_tools,
                    "timeout_sec": self.api_timeout,
                    "api_key": self.api_key,
                }
                if self.model:
                    kwargs["model"] = self.model

                response = complete_chat(**kwargs)
            except Exception as e:
                logger.error("[%s] API failed: %s", agent_name, e)
                raise RuntimeError(f"Agent {agent_name} API failed: {str(e)}") from e

            choices = response.get("choices") or [{}]
            first_choice = choices[0] if choices else {}
            message_obj = first_choice.get("message") or {}
            content = message_obj.get("content", "")
            tool_calls = message_obj.get("tool_calls") or []

            # Append the model's message to context
            # Even if content is None (only tool_calls), we must append it.
            messages.append(message_obj)

            if not tool_calls:
                final_content = self._finalize_response(messages, content)
                self._dump_debug_history(agent_name)
                self._run_hook(f"post-{agent_name}-run", status="success")
                return final_content

            logger.info("[%s] requested %d tool calls.", agent_name, len(tool_calls))
            if not turn_budget.consume(len(tool_calls)):
                self._run_hook(f"post-{agent_name}-run", status="budget_exceeded")
                raise RuntimeError(
                    f"Agent {agent_name} exceeded the tool-call budget "
                    f"({turn_budget.limit} per task; policy agent_defaults.max_tool_calls_per_task)."
                )
            self._dispatch_tool_calls(messages, tool_calls)

        self._run_hook(f"post-{agent_name}-run", status="timeout")
        raise RuntimeError(f"Agent {agent_name} exceeded maximum tool iterations.")

    def execute_loop(self, initial_task: str) -> LoopOutcome:
        """Run the MAS loop and return what it produced, verdict included.

        The verdict is earned by a check this method runs itself, never from the
        agent's own commands: the model selects those (spec R-VP-1).
        """
        # 1. Planner
        planner_prompt = PLANNER_PROMPT_TEMPLATE.format(task=initial_task)
        plan_started = time.monotonic()
        plan = self.execute_agent("planner", planner_prompt, tools=[])
        logger.info("Plan generated: %d bytes", len(plan))

        # Observation-only shadow comparison (docs/specs/mangomas-integration-core.md).
        # Off by default; a value object crosses the boundary, never `self`.
        if shadow_planner_enabled():
            try:
                run_shadow_comparison(
                    ShadowContext(
                        workspace_dir=self.workspace_dir,
                        api_key=self.api_key,
                        model=self.model,
                        api_timeout=self.api_timeout,
                        planner_system_prompt=self.load_agent_prompt("planner"),
                        planner_user_prompt=planner_prompt,
                        task=initial_task,
                        incumbent_plan=plan,
                        incumbent_elapsed_ms=int((time.monotonic() - plan_started) * 1000),
                    )
                )
            except Exception:
                logger.exception(
                    "Orchestrator-level guard caught a shadow planner failure "
                    "the channel itself did not contain; incumbent plan is unaffected"
                )

        # 2. Reasoner (Code Generation / Fixes using Tools)
        reasoner_prompt = REASONER_PROMPT_TEMPLATE.format(plan=plan)
        code_output = self.execute_agent("nemotron-reasoner", reasoner_prompt)
        logger.info("Code generation completed via tools: %d bytes", len(code_output))

        # 3. Verifier (Testing & Hygiene using Tools)
        verifier_prompt = VERIFIER_PROMPT_TEMPLATE.format(code_output=code_output)
        verification = self.execute_agent("verifier", verifier_prompt)
        logger.info("Verification result: %d bytes", len(verification))

        # 4. The harness earns the verdict itself.
        return LoopOutcome(self._harness_verdict(), verification, plan, code_output)

    def _harness_verdict(self) -> Verdict:
        """Run the configured check and grade it, or say why it could not run."""
        runner = self._verification
        if runner.target is None:
            return not_configured()
        if runner.is_reentrant():
            return reentrant(runner.target)
        return derive_verdict(runner.run(self.workspace_dir))

    def execute_sequential_thinking_loop(self, initial_task: str) -> str:
        """The verifier agent's own message, as this method has always returned.

        Byte-compatible for callers on `main` (R-ORCH-4); the verdict is on
        `execute_loop`.
        """
        return self.execute_loop(initial_task).verifier_message


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
