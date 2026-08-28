from __future__ import annotations

import json
import logging
import os
import subprocess
import time
import typing
from pathlib import Path

from harness.shared.debug_dump import write_dump
from harness.shared.meta_tools import META_TOOLS_SCHEMA, hypothesis_register, knowledge_gap_log
from harness.shared.nemotron_bridge import complete_chat
from harness.shared.shadow_planner import ShadowContext, run_shadow_comparison, shadow_planner_enabled

logger = logging.getLogger(__name__)

# How much of a task string is echoed into log lines (avoids flooding logs
# with full prompts while keeping enough to correlate runs).
TASK_LOG_PREVIEW_CHARS = 100
# Default confidence when the model omits it from a hypothesis_register call.
DEFAULT_HYPOTHESIS_CONFIDENCE = 0.5

def _normalize_tool_arguments(raw: typing.Any, func_name: typing.Any) -> dict[str, typing.Any]:
    """Coerce a tool call's ``arguments`` field into a dict of keyword args.

    The field is model-generated and only conventionally a JSON object string.
    Two shapes crashed the previous implementation:

    * ``null`` -> ``json.loads(None)`` raises TypeError, which the surrounding
      ``except json.JSONDecodeError`` did not catch;
    * ``"[]"`` -> parses cleanly to a list, then every registry lambda dies on
      ``.get``.

    Both now degrade to no arguments, so a malformed call produces a tool
    result the model can react to rather than an unhandled exception.
    """
    if isinstance(raw, dict):
        return raw
    if not isinstance(raw, str) or not raw.strip():
        if raw is not None:
            logger.warning("Tool %s sent non-string arguments %r; treating as empty", func_name, type(raw).__name__)
        return {}
    try:
        parsed = json.loads(raw)
    except (json.JSONDecodeError, TypeError, ValueError):
        logger.warning("Tool %s sent unparseable arguments; treating as empty", func_name)
        return {}
    if not isinstance(parsed, dict):
        logger.warning(
            "Tool %s sent JSON %s arguments, expected an object; treating as empty",
            func_name, type(parsed).__name__,
        )
        return {}
    return parsed


AUTONOMOUS_AGENT_GUARDRAIL = (
    "YOU ARE AN AUTONOMOUS AGENT. You must follow repository invariants "
    "and fail closed when approval is required."
)

PLANNER_PROMPT_TEMPLATE = (
    "Create a plan for the following task, ensuring no hardcoded values and strict testing: {task}\n"
    f"{AUTONOMOUS_AGENT_GUARDRAIL}"
)

REASONER_PROMPT_TEMPLATE = (
    "Execute the following plan using backward-compatible, modular code. "
    "You MUST use your 'write_file' and 'run_command' tools to actually implement and test it on the filesystem.\n"
    f"{AUTONOMOUS_AGENT_GUARDRAIL} "
    "Use run_command to run standard terminal commands like pip, uvicorn, and pytest.\n\n"
    "Plan:\n{plan}"
)

VERIFIER_PROMPT_TEMPLATE = (
    "Verify the generated codebase against our CI gates (ruff, mypy, pytest, vitest). "
    "Use your 'run_command' tool to execute them. Report PASS or FAIL.\n"
    f"{AUTONOMOUS_AGENT_GUARDRAIL}\n\n"
    "Reasoner Output:\n{code_output}"
)

# Combine orchestrator baseline tools with meta tools for continuous learning
NEMOTRON_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "write_file",
            "description": "Write or overwrite a file on the filesystem with the provided content.",
            "parameters": {
                "type": "object",
                "properties": {
                    "filepath": {"type": "string", "description": "The path to the file to write."},
                    "content": {"type": "string", "description": "The full content to write to the file."},
                },
                "required": ["filepath", "content"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "run_command",
            "description": "Run a shell command and return its output.",
            "parameters": {
                "type": "object",
                "properties": {"command": {"type": "string", "description": "The shell command to execute."}},
                "required": ["command"],
                "additionalProperties": False,
            },
        },
    },
] + META_TOOLS_SCHEMA


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
        max_iterations: int = 10,
        api_timeout: int = 300,
        tool_timeout: int = 30,
    ) -> None:
        self.workspace_dir = workspace_dir
        self.api_key = api_key
        self.model = model
        self.max_iterations = max_iterations
        self.api_timeout = api_timeout
        self.tool_timeout = tool_timeout
        self.agents_dir = self.workspace_dir / ".mango" / "agents"
        self.hooks_dir = self.workspace_dir / ".mango" / "hooks"
        self.conversation_history: list[dict[str, str]] = []
        # Tool dispatch registry: every function name declared in
        # NEMOTRON_TOOLS must have an entry here (pinned by a unit test), so
        # declaration and dispatch cannot drift apart.
        self._tool_handlers: dict[str, typing.Callable[[dict[str, typing.Any]], str]] = {
            "write_file": lambda args: self._execute_write_file(args.get("filepath", ""), args.get("content", "")),
            "run_command": lambda args: self._execute_run_command(args.get("command", "")),
            "knowledge_gap_log": lambda args: knowledge_gap_log(
                args.get("question", ""), args.get("what_needed", ""), args.get("proposed_approach", "")
            ),
            "hypothesis_register": lambda args: hypothesis_register(
                args.get("claim", ""), args.get("reasoning", ""),
                args.get("confidence", DEFAULT_HYPOTHESIS_CONFIDENCE),
            ),
        }

    def _run_hook(self, hook_name: str, **kwargs: typing.Any) -> None:
        """Executes a pre- or post- hook script if it exists."""
        hook_path = self.hooks_dir / f"{hook_name}.sh"
        if hook_path.exists():
            logger.info("Executing hook: %s", hook_name)
            try:
                env = os.environ.copy()
                for k, v in kwargs.items():
                    env[f"MANGO_HOOK_{k.upper()}"] = str(v)
                subprocess.run(
                    ["bash", str(hook_path)], cwd=self.workspace_dir, env=env, check=True, timeout=self.tool_timeout
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
        workspace = self.workspace_dir.resolve()
        target_path = (workspace / filepath).resolve()

        if not target_path.is_relative_to(workspace):
            return f"Error writing file {filepath}: path escapes workspace"

        try:
            target_path.parent.mkdir(parents=True, exist_ok=True)
            target_path.write_text(content, encoding="utf-8")
            return f"Success: Wrote {len(content)} characters to {target_path.resolve()}"
        except Exception as e:  # noqa: BLE001 - a tool must always answer its call
            # with a string; an escaping exception would leave the model's
            # tool_calls message unanswered and stall the conversation.
            return f"Error writing file {filepath}: {str(e)}"

    def _execute_run_command(self, command: str) -> str:
        """Local tool implementation to execute a command."""
        try:
            # Route command execution through pretooluse guard
            guard_script = self.workspace_dir / "harness" / "shared" / "pretooluse_guard.py"
            if guard_script.exists():
                payload = json.dumps({"tool": "run_command", "args": {"command": command}})
                env = os.environ.copy()
                env["PYTHONPATH"] = str(self.workspace_dir)
                guard_result = subprocess.run(
                    ["python", str(guard_script)],
                    input=payload,
                    cwd=self.workspace_dir,
                    env=env,
                    capture_output=True,
                    text=True,
                    timeout=self.tool_timeout,
                )
                if guard_result.returncode != 0:
                    return (
                        f"Error: Command blocked by policy guard. Guard output:\n"
                        f"{guard_result.stdout}\n{guard_result.stderr}"
                    )

            # If guard passes (or doesn't exist), execute the command
            result = subprocess.run(
                ["bash", "-c", command],
                cwd=self.workspace_dir,
                capture_output=True,
                text=True,
                timeout=self.tool_timeout,
            )

            output = result.stdout
            if result.stderr:
                output += "\n[STDERR]\n" + result.stderr

            if not output.strip():
                return f"Command executed with return code {result.returncode}, but generated no output."
            return output
        except subprocess.TimeoutExpired:
            return f"Error: Command '{command}' timed out after {self.tool_timeout} seconds."
        except Exception as e:  # noqa: BLE001 - same tool-result contract as
            # _execute_write_file: report the failure, never propagate it.
            return f"Error executing command '{command}': {str(e)}"

    def _dispatch_tool_calls(
        self, messages: list[dict[str, typing.Any]], tool_calls: list[dict[str, typing.Any]]
    ) -> None:
        """Execute each requested tool via the registry and append the results
        to ``messages`` so they feed back to the model."""
        for tc in tool_calls:
            tc_id = tc.get("id")
            func_name = tc.get("function", {}).get("name")
            args = _normalize_tool_arguments(tc.get("function", {}).get("arguments"), func_name)

            handler = self._tool_handlers.get(func_name)
            if handler is None:
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

    def _finalize_response(self, messages: list[dict[str, typing.Any]], content: typing.Any) -> str:
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

    def execute_agent(self, agent_name: str, task: str, tools: list[dict[str, typing.Any]] | None = None) -> str:
        """
        Executes a single agent's reasoning loop using ReAct (Reasoning and Acting).
        Returns the final string output from the agent.
        """
        self._run_hook("pre-nemotron-run", task=task, agent=agent_name)
        logger.info("Executing agent [%s] with task: %s...", agent_name, task[:TASK_LOG_PREVIEW_CHARS])

        messages: list[dict[str, typing.Any]] = [
            {"role": "system", "content": self.load_agent_prompt(agent_name)},
            {"role": "user", "content": task},
        ]

        # Keep track of conversation for debugging
        self.conversation_history.extend(messages)

        active_tools = tools if tools is not None else NEMOTRON_TOOLS

        for _iteration in range(self.max_iterations):
            try:
                kwargs: dict[str, typing.Any] = {
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

            message_obj = response.get("choices", [{}])[0].get("message", {})
            content = message_obj.get("content", "")
            tool_calls = message_obj.get("tool_calls", [])

            # Append the model's message to context
            # Even if content is None (only tool_calls), we must append it.
            messages.append(message_obj)

            if not tool_calls:
                final_content = self._finalize_response(messages, content)
                self._dump_debug_history(agent_name)
                self._run_hook(f"post-{agent_name}-run", status="success")
                return final_content

            logger.info("[%s] requested %d tool calls.", agent_name, len(tool_calls))
            self._dispatch_tool_calls(messages, tool_calls)

        self._run_hook(f"post-{agent_name}-run", status="timeout")
        raise RuntimeError(f"Agent {agent_name} exceeded maximum tool iterations.")

    def execute_sequential_thinking_loop(self, initial_task: str) -> str:
        """Executes the full MAS loop: Planner -> Nemotron-Reasoner -> Verifier."""
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

        return verification
