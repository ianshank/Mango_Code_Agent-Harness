from __future__ import annotations

import json
import logging
import os
import subprocess
import time
import typing
from pathlib import Path

from harness.shared.agent_authority import ACTIVE_TO_CANONICAL, execution_identity, tools_for_role
from harness.shared.debug_dump import credential_env_names, write_dump
from harness.shared.governance.broker import ExecutionBroker, ExecutionResult
from harness.shared.meta_tools import META_TOOLS_SCHEMA, hypothesis_register, knowledge_gap_log
from harness.shared.nemotron_bridge import complete_chat
from harness.shared.policy_loader import max_tool_calls_per_task, orchestrator_defaults
from harness.shared.shadow_planner import ShadowContext, run_shadow_comparison, shadow_planner_enabled
from harness.shared.write_policy import write_denial_reason

logger = logging.getLogger(__name__)

# How much of a task string is echoed into log lines (avoids flooding logs
# with full prompts while keeping enough to correlate runs).
TASK_LOG_PREVIEW_CHARS = 100

#: The hook fired once at the start of every agent turn. Named rather than
#: repeated so the allowlist below and the call site cannot drift apart.
PRE_RUN_HOOK = "pre-nemotron-run"

#: Hook names `_run_hook` will execute. Derived from the active roles rather
#: than listed: a role added to `ACTIVE_TO_CANONICAL` gets its post-hook without
#: a second edit, and a list maintained by hand is exactly the thing that goes
#: stale into a permission. Every name here is one this module constructs
#: itself; nothing a caller passes can widen the set.
PERMITTED_HOOK_NAMES = frozenset(
    {PRE_RUN_HOOK} | {f"post-{role}-run" for role in ACTIVE_TO_CANONICAL}
)
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


def _format_execution_result(result: ExecutionResult) -> str:
    """Render a broker result as the tool message the model receives.

    Kept pure and separate from execution so the three output shapes stay
    testable without spawning a process.
    """
    if result.status == "BLOCKED":
        return f"Error: Command blocked by policy guard. {result.reason or result.stderr}".strip()
    if result.reason:
        return f"Error: {result.reason}"
    output = result.stdout
    if result.stderr:
        output += "\n[STDERR]\n" + result.stderr
    if not output.strip():
        return f"Command executed with return code {result.exit_code}, but generated no output."
    return output


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
    "Use run_command to run the repository's own gates -- pytest, make, ruff, mypy. Commands that "
    "install packages or reach the network are classified as external actions and will be denied; "
    "if you need one, record the need with knowledge_gap_log rather than retrying.\n\n"
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
        max_iterations: int | None = None,
        api_timeout: int | None = None,
        tool_timeout: int | None = None,
        broker: ExecutionBroker | None = None,
        active_role: str = "nemotron-reasoner",
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
        # `execute_agent` overrides this per turn. The default is the implementer
        # contract, which is what a directly-driven orchestrator is doing; it is
        # not the widest role -- it holds neither external_write, destructive nor
        # secret_access.
        self._active_role = active_role
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
        """Local tool implementation to write a file.

        Two checks, in order. Confinement keeps the write inside the workspace;
        the write policy keeps it off the control surface *within* the workspace.
        The second is not redundant: in the deployed path the workspace is the
        repository root, so confinement alone permits writing the guard, the
        policy decision point, the orchestrator's own hooks and the agent
        personas (spec R-AC-6, R-AC-7).
        """
        workspace = self.workspace_dir.resolve()
        target_path = (workspace / filepath).resolve()

        if not target_path.is_relative_to(workspace):
            # Previously returned silently. An escape attempt is the single most
            # interesting thing this tool can do and it left no trace anywhere.
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
        except Exception as e:  # noqa: BLE001 - a tool must always answer its call
            # with a string; an escaping exception would leave the model's
            # tool_calls message unanswered and stall the conversation.
            return f"Error writing file {filepath}: {str(e)}"

    def _execute_run_command(self, command: str) -> str:
        """Run a command through the approved execution broker (INV-8).

        Previously this shelled out directly. The broker is what makes INV-8 true
        on the live path: it derives the action from the command, asks the
        authority model for a verdict, runs the command guard, and pins the
        working directory, the timeout and the captured output size. It never
        falls back to host execution when its backend is unavailable (INV-9), and
        a denial is terminal -- nothing here retries or downgrades one (INV-10).

        The guard is no longer called here as well: it is on the broker's path,
        and calling it twice would mean two places to keep in step.
        """
        result = self._broker.execute_command(
            command,
            {"agent_id": execution_identity(self._active_role)},
            cwd=self.workspace_dir,
            timeout=self.tool_timeout,
        )
        if result.status == "BLOCKED":
            logger.warning("Broker denied command for role %s: %s", self._active_role, result.reason)
        return _format_execution_result(result)

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
        # The tool handlers are zero-argument closures over `self`, so the acting
        # role has to be recorded here for `_execute_run_command` to name it. A
        # verifier turn must be evaluated as the verifier, not as whatever role
        # ran last.
        self._active_role = agent_name
        self._run_hook(PRE_RUN_HOOK, task=task, agent=agent_name)
        logger.info("Executing agent [%s] with task: %s...", agent_name, task[:TASK_LOG_PREVIEW_CHARS])

        messages: list[dict[str, typing.Any]] = [
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
        # Cumulative budget across the whole task, from
        # agent_defaults.max_tool_calls_per_task in governance-policy.json.
        executed_tool_calls = 0

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
            executed_tool_calls += len(tool_calls)
            if executed_tool_calls > self.max_tool_calls_per_task:
                self._run_hook(f"post-{agent_name}-run", status="budget_exceeded")
                raise RuntimeError(
                    f"Agent {agent_name} exceeded the tool-call budget "
                    f"({self.max_tool_calls_per_task} per task; policy agent_defaults.max_tool_calls_per_task)."
                )
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
