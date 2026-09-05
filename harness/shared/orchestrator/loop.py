"""ReAct Loop execution for the Mango MAS orchestrator."""

from __future__ import annotations

import logging
import time
import uuid
from collections.abc import Callable
from pathlib import Path
from typing import Any

from harness.shared.agent_authority import tools_for_role
from harness.shared.agent_prompts import (
    PLANNER_PROMPT_TEMPLATE,
    PRE_RUN_HOOK,
    REASONER_PROMPT_TEMPLATE,
    TASK_LOG_PREVIEW_CHARS,
    VERIFIER_PROMPT_TEMPLATE,
)
from harness.shared.debug_dump import write_dump
from harness.shared.governance.verdict import LoopOutcome, Verdict, derive_verdict, not_configured, reentrant
from harness.shared.governance.verification import VerificationRunner
from harness.shared.nemotron_bridge import complete_chat
from harness.shared.orchestrator.dispatcher import ToolDispatcher
from harness.shared.orchestrator.hook_runner import HookRunner
from harness.shared.policy_loader import max_tool_calls_per_task as policy_max_tool_calls_per_task
from harness.shared.policy_loader import orchestrator_defaults
from harness.shared.shadow_planner import ShadowContext, run_shadow_comparison, shadow_planner_enabled
from harness.shared.tool_budget import ToolBudget
from harness.shared.tool_schemas import NEMOTRON_TOOLS

logger = logging.getLogger(__name__)


class ExecutionLoop:
    """Manages the full ReAct loop and agent interactions."""

    def __init__(
        self,
        workspace_dir: Path,
        agents_dir: Path,
        dispatcher: ToolDispatcher,
        hook_runner: HookRunner,
        verification: VerificationRunner,
        verification_cwd: Path,
        api_key: str | None = None,
        model: str | None = None,
        max_iterations: int | None = None,
        api_timeout: int | None = None,
        max_tool_calls_per_task: int | None = None,
        complete_chat_fn: Callable[..., Any] | None = None,
        policy_path: Path | None = None,
    ) -> None:
        """Budgets left as ``None`` resolve from ``governance-policy.json`` here,
        at construction time, never at import: ``orchestrator.max_iterations``,
        ``orchestrator.api_timeout_sec`` and
        ``agent_defaults.max_tool_calls_per_task`` (tech-debt-hardening-plan
        R-TDH-12, closing policy-single-source AC-1). Callers that pass explicit
        values, as the ``MangoMASOrchestrator`` facade does, are unaffected. The
        previous literal defaults (15 / 30 / 50) disagreed with the policy
        (10 / 300 / 100) and were reachable by any direct constructor call.
        ``policy_path`` points the resolution at another policy file, for tests
        and adopters; the loader fails closed on a malformed one.
        """
        self.workspace_dir = workspace_dir
        self.agents_dir = agents_dir
        self.dispatcher = dispatcher
        self.hook_runner = hook_runner
        self.verification = verification
        self.verification_cwd = verification_cwd
        self.api_key = api_key
        self.model = model
        if max_iterations is None or api_timeout is None:
            limits = orchestrator_defaults(policy_path)
            logger.debug(
                "ExecutionLoop budgets resolved from policy: max_iterations=%s api_timeout_sec=%s",
                limits["max_iterations"],
                limits["api_timeout_sec"],
            )
            if max_iterations is None:
                max_iterations = limits["max_iterations"]
            if api_timeout is None:
                api_timeout = limits["api_timeout_sec"]
        if max_tool_calls_per_task is None:
            max_tool_calls_per_task = policy_max_tool_calls_per_task(policy_path)
            logger.debug("ExecutionLoop tool-call budget resolved from policy: %s", max_tool_calls_per_task)
        self.max_iterations = max_iterations
        self.api_timeout = api_timeout
        self.max_tool_calls_per_task = max_tool_calls_per_task
        self.conversation_history: list[dict[str, Any]] = []
        #: One identifier per `execute_loop`, carried by every structured model
        #: and tool event of that run (2026 standards audit H6). A bare
        #: `execute_agent` outside a loop mints one and keeps it until the next
        #: loop replaces it, so no event is ever emitted without one.
        self.run_id: str | None = None

        if complete_chat_fn is None:
            self.complete_chat_fn = complete_chat
        else:
            self.complete_chat_fn = complete_chat_fn

    def load_agent_prompt(self, agent_name: str) -> str:
        """Dynamically loads the agent instructions from the .mango directory."""
        agent_file = self.agents_dir / f"{agent_name}.md"
        if not agent_file.exists():
            repo_agents_dir = Path(__file__).resolve().parent.parent.parent.parent / ".mango" / "agents"
            fallback_file = repo_agents_dir / f"{agent_name}.md"
            if fallback_file.exists():
                return fallback_file.read_text(encoding="utf-8")
            raise FileNotFoundError(f"Agent definition not found: {agent_file}")
        return agent_file.read_text(encoding="utf-8")

    def _finalize_response(self, messages: list[dict[str, Any]], content: Any) -> str:
        final_content = str(content or "")
        if not final_content.strip() and len(messages) > 3:
            last_msg = messages[-2]
            if last_msg.get("role") == "tool":
                final_content = f"Completed via tool execution. Last tool result: {last_msg.get('content')}"

        if messages and messages[-1].get("role") == "assistant":
            messages[-1]["content"] = final_content
        return final_content

    def _dump_debug_history(self, agent_name: str) -> None:
        write_dump(self.conversation_history, agent_name, api_key=self.api_key)

    def _ensure_run_id(self) -> str:
        if self.run_id is None:
            self.run_id = uuid.uuid4().hex
        return self.run_id

    @staticmethod
    def _log_model_call(
        run_id: str,
        agent_name: str,
        iteration: int,
        started: float,
        response: Any,
        error: BaseException | None = None,
    ) -> None:
        """One structured event per model round-trip, on success and on failure:
        who, which turn, how long, the outcome, and the token counts the
        response reports. Never the messages. A failed request emits the same
        event with ``outcome=error`` so error rate and latency stay correlatable
        by ``run_id`` (Copilot review on PR #86)."""
        usage = response.get("usage") if isinstance(response, dict) else None
        if not isinstance(usage, dict):
            usage = {}
        logger.log(
            logging.WARNING if error is not None else logging.DEBUG,
            "model call by %s (iteration %d)%s",
            agent_name,
            iteration,
            f" failed: {type(error).__name__}" if error is not None else "",
            extra={
                "event": "model_call",
                "run_id": run_id,
                "agent": agent_name,
                "iteration": iteration,
                "latency_ms": int((time.monotonic() - started) * 1000),
                "outcome": "error" if error is not None else "ok",
                "error_type": type(error).__name__ if error is not None else None,
                "prompt_tokens": usage.get("prompt_tokens"),
                "completion_tokens": usage.get("completion_tokens"),
            },
        )

    def execute_agent(
        self,
        agent_name: str,
        task: str,
        tools: list[dict[str, Any]] | None = None,
        budget: ToolBudget | None = None,
    ) -> str:
        run_id = self._ensure_run_id()
        self.dispatcher.set_active_role(agent_name)
        self.hook_runner.run_hook(PRE_RUN_HOOK, task=task, agent=agent_name)
        logger.info("Executing agent [%s] with task: %s...", agent_name, task[:TASK_LOG_PREVIEW_CHARS])

        messages: list[dict[str, Any]] = [
            {"role": "system", "content": self.load_agent_prompt(agent_name)},
            {"role": "user", "content": task},
        ]
        self.conversation_history.extend(messages)

        active_tools = tools if tools is not None else tools_for_role(agent_name, NEMOTRON_TOOLS)
        turn_budget = budget if budget is not None else ToolBudget(self.max_tool_calls_per_task)

        for iteration in range(self.max_iterations):
            started = time.monotonic()
            try:
                kwargs: dict[str, Any] = {
                    "messages": self.conversation_history,
                    "tools": active_tools,
                    "timeout_sec": self.api_timeout,
                    "api_key": self.api_key,
                }
                if self.model:
                    kwargs["model"] = self.model

                if self.api_key is None:
                    kwargs.pop("api_key")

                response = self.complete_chat_fn(**kwargs)
            except Exception as e:
                self._log_model_call(run_id, agent_name, iteration, started, None, error=e)
                logger.error("[%s] API failed: %s", agent_name, e)
                raise RuntimeError(f"Agent {agent_name} API failed: {str(e)}") from e
            self._log_model_call(run_id, agent_name, iteration, started, response)

            choices = response.get("choices") or [{}]
            first_choice = choices[0] if choices else {}
            message_obj = first_choice.get("message") or {}
            content = message_obj.get("content", "")
            tool_calls = message_obj.get("tool_calls") or []

            self.conversation_history.append(message_obj)

            if not tool_calls:
                final_content = self._finalize_response(self.conversation_history, content)
                self._dump_debug_history(agent_name)
                self.hook_runner.run_hook(f"post-{agent_name}-run", status="success")
                return final_content

            logger.info("[%s] requested %d tool calls.", agent_name, len(tool_calls))
            if not turn_budget.consume(len(tool_calls)):
                self.hook_runner.run_hook(f"post-{agent_name}-run", status="budget_exceeded")
                raise RuntimeError(
                    f"Agent {agent_name} exceeded the tool-call budget "
                    f"({turn_budget.limit} per task; policy agent_defaults.max_tool_calls_per_task)."
                )
            self.dispatcher.dispatch(self.conversation_history, tool_calls, run_id=run_id)

        self.hook_runner.run_hook(f"post-{agent_name}-run", status="timeout")
        raise RuntimeError(f"Agent {agent_name} exceeded maximum tool iterations.")

    def _harness_verdict(self) -> Verdict:
        runner = self.verification
        if runner.target is None:
            return not_configured()
        if runner.is_reentrant():
            return reentrant(runner.target)
        return derive_verdict(runner.run(self.verification_cwd))

    def _record_enforcement_baseline(self) -> None:
        """Digest the protected files before any agent has had a turn.

        The verdict at the end of the loop is refused if any of them changed in
        between, so this has to run first: a baseline taken after the reasoner
        would record the forgery as the reference. Guarded the same way
        `_harness_verdict` is, so a loop that will not verify does not walk the
        tree for nothing. A baseline that cannot be taken is left to `run`,
        which refuses the verdict for the same reason rather than raising here
        and losing the agents' work.
        """
        runner = self.verification
        if runner.target is None or runner.is_reentrant():
            return
        try:
            runner.snapshot_enforcement(self.verification_cwd)
        except Exception:
            # Broad on purpose: `run` refuses the verdict for the same fault.
            logger.exception("The enforcement baseline could not be recorded; the verdict will refuse")

    def execute_loop(self, initial_task: str) -> LoopOutcome:
        self.run_id = uuid.uuid4().hex
        # One budget for the task, spent by all three roles. `tool_budget.py`
        # was written for exactly this and the loop then handed each role a
        # fresh allowance, so `max_tool_calls_per_task` was enforced as three
        # times its declared value (2026 standards audit M1).
        budget = ToolBudget(self.max_tool_calls_per_task)
        logger.debug("loop started", extra={"event": "loop_start", "run_id": self.run_id, "tool_budget": budget.limit})
        self._record_enforcement_baseline()
        planner_prompt = PLANNER_PROMPT_TEMPLATE.format(task=initial_task)
        plan_started = time.monotonic()
        plan = self.execute_agent("planner", planner_prompt, tools=[], budget=budget)
        logger.info("Plan generated: %d bytes", len(plan))

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
                logger.exception("Orchestrator-level guard caught a shadow planner failure")

        reasoner_prompt = REASONER_PROMPT_TEMPLATE.format(plan=plan)
        code_output = self.execute_agent("nemotron-reasoner", reasoner_prompt, budget=budget)
        logger.info("Code generation completed via tools: %d bytes", len(code_output))

        verifier_prompt = VERIFIER_PROMPT_TEMPLATE.format(code_output=code_output)
        verification = self.execute_agent("verifier", verifier_prompt, budget=budget)
        logger.info("Verification result: %d bytes", len(verification))

        return LoopOutcome(self._harness_verdict(), verification, plan, code_output)
