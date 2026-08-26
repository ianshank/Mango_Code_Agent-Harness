from __future__ import annotations

import json
import logging
import os
import subprocess
import typing
from pathlib import Path

from harness.shared.meta_tools import META_TOOLS_SCHEMA, hypothesis_register, knowledge_gap_log
from harness.shared.nemotron_bridge import complete_chat

logger = logging.getLogger(__name__)

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
    ):
        self.workspace_dir = workspace_dir
        self.api_key = api_key
        self.model = model
        self.max_iterations = max_iterations
        self.api_timeout = api_timeout
        self.tool_timeout = tool_timeout
        self.agents_dir = self.workspace_dir / ".mango" / "agents"
        self.hooks_dir = self.workspace_dir / ".mango" / "hooks"
        self.conversation_history: list[dict[str, str]] = []

    def _run_hook(self, hook_name: str, **kwargs: typing.Any) -> None:
        """Executes a pre- or post- hook script if it exists."""
        hook_path = self.hooks_dir / f"{hook_name}.sh"
        if hook_path.exists():
            logger.info(f"Executing hook: {hook_name}")
            try:
                env = os.environ.copy()
                for k, v in kwargs.items():
                    env[f"MANGO_HOOK_{k.upper()}"] = str(v)
                subprocess.run(
                    ["bash", str(hook_path)], cwd=self.workspace_dir, env=env, check=True, timeout=self.tool_timeout
                )
            except Exception:
                logger.exception(f"Hook {hook_name} failed")
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
        except Exception as e:
            return f"Error writing file {filepath}: {str(e)}"

    def _execute_run_command(self, command: str) -> str:
        """Local tool implementation to execute a command."""
        try:
            # Route command execution through pretooluse guard
            guard_script = self.workspace_dir / "harness" / "shared" / "pretooluse_guard.py"
            if guard_script.exists():
                import json

                payload = json.dumps({"tool": "run_command", "args": {"command": command}})
                guard_result = subprocess.run(
                    ["python", str(guard_script)],
                    input=payload,
                    cwd=self.workspace_dir,
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
        except Exception as e:
            return f"Error executing command '{command}': {str(e)}"

    def execute_agent(self, agent_name: str, task: str, tools: list[dict[str, typing.Any]] | None = None) -> str:
        """
        Executes a single agent's reasoning loop using ReAct (Reasoning and Acting).
        Returns the final string output from the agent.
        """
        self._run_hook("pre-nemotron-run", task=task, agent=agent_name)
        logger.info(f"Executing agent [{agent_name}] with task: {task[:100]}...")

        messages = [
            {"role": "system", "content": self.load_agent_prompt(agent_name)},
            {"role": "user", "content": task},
        ]

        # Keep track of conversation for debugging
        self.conversation_history.extend(messages)

        active_tools = tools if tools is not None else NEMOTRON_TOOLS

        for i in range(self.max_iterations):
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
                logger.error(f"[{agent_name}] API failed: {e}")
                raise RuntimeError(f"Agent {agent_name} API failed: {str(e)}") from e

            message_obj = response.get("choices", [{}])[0].get("message", {})
            content = message_obj.get("content", "")
            tool_calls = message_obj.get("tool_calls", [])

            # Append the model's message to context
            # Even if content is None (only tool_calls), we must append it.
            messages.append(message_obj)

            if not tool_calls:
                # No more tool calls, we are done
                final_content = str(content or "")

                # Fallback if model just returns an empty string but we had tool executions
                if not final_content.strip() and len(messages) > 3:
                    last_msg = messages[-2]  # the tool result is immediately before the current model empty message
                    if last_msg.get("role") == "tool":
                        final_content = f"Completed via tool execution. Last tool result: {last_msg.get('content')}"

                self.conversation_history.append({"role": "assistant", "content": final_content})

                # Debug dump
                if os.environ.get("MANGO_DEBUG_DUMP") == "1":
                    import copy
                    import tempfile

                    # Create a redacted copy of the history
                    redacted_history = copy.deepcopy(self.conversation_history)
                    if self.api_key:
                        for msg in redacted_history:
                            if "content" in msg and isinstance(msg["content"], str):
                                msg["content"] = msg["content"].replace(self.api_key, "<REDACTED_API_KEY>")

                    dump_dir = Path(tempfile.gettempdir()) / "mango_debug"
                    dump_dir.mkdir(parents=True, exist_ok=True)

                    # Use a unique timestamp or run id for the dump
                    import time

                    dump_file = dump_dir / f"debug_{agent_name}_{int(time.time() * 1000)}.json"

                    with open(dump_file, "w") as f:
                        json.dump(redacted_history, f, indent=2)

                self._run_hook(f"post-{agent_name}-run", status="success")
                return final_content

            logger.info(f"[{agent_name}] requested {len(tool_calls)} tool calls.")

            # Execute tools
            for tc in tool_calls:
                tc_id = tc.get("id")
                func_name = tc.get("function", {}).get("name")
                func_args_str = tc.get("function", {}).get("arguments", "{}")

                try:
                    args = json.loads(func_args_str)
                except json.JSONDecodeError:
                    args = {}

                tool_result = ""
                if func_name == "write_file":
                    tool_result = self._execute_write_file(args.get("filepath", ""), args.get("content", ""))
                elif func_name == "run_command":
                    tool_result = self._execute_run_command(args.get("command", ""))
                elif func_name == "knowledge_gap_log":
                    tool_result = knowledge_gap_log(
                        args.get("question", ""), args.get("what_needed", ""), args.get("proposed_approach", "")
                    )
                elif func_name == "hypothesis_register":
                    tool_result = hypothesis_register(
                        args.get("claim", ""), args.get("reasoning", ""), args.get("confidence", 0.5)
                    )
                elif func_name == "query_docs":
                    from harness.shared.meta_tools import query_docs
                    tool_result = query_docs(
                        args.get("query", ""), args.get("library_id", None)
                    )
                else:
                    tool_result = f"Error: Unknown tool '{func_name}'"

                logger.info(f"Executed {func_name}. Result length: {len(tool_result)}")

                # Append tool result to messages to feed back to model
                messages.append({"role": "tool", "tool_call_id": tc_id, "name": func_name, "content": tool_result})

        self._run_hook(f"post-{agent_name}-run", status="timeout")
        raise RuntimeError(f"Agent {agent_name} exceeded maximum tool iterations.")

    def execute_sequential_thinking_loop(self, initial_task: str) -> str:
        """Executes the full MAS loop: Planner -> Nemotron-Reasoner -> Verifier."""
        # 1. Planner
        planner_prompt = PLANNER_PROMPT_TEMPLATE.format(task=initial_task)
        plan = self.execute_agent("planner", planner_prompt, tools=[])
        logger.info(f"Plan generated: {len(plan)} bytes")

        # 2. Reasoner (Code Generation / Fixes using Tools)
        reasoner_prompt = REASONER_PROMPT_TEMPLATE.format(plan=plan)
        code_output = self.execute_agent("nemotron-reasoner", reasoner_prompt)
        logger.info(f"Code generation completed via tools: {len(code_output)} bytes")

        # 3. Verifier (Testing & Hygiene using Tools)
        verifier_prompt = VERIFIER_PROMPT_TEMPLATE.format(code_output=code_output)
        verification = self.execute_agent("verifier", verifier_prompt)
        logger.info(f"Verification result: {len(verification)} bytes")

        return verification
