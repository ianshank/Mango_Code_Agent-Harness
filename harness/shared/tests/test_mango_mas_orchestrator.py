"""Coverage-focused tests for MangoMASOrchestrator.

All tests mock the Nemotron bridge (``complete_chat``) and the local tool
subprocess boundaries so NO real NVIDIA API call or network access happens.
Tests that would require a real ``NVIDIA_API_KEY`` are marked ``@pytest.mark.live``
and are deselected by default (``-m "not live"``).
"""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path
from typing import Any

import pytest

from harness.shared import mango_mas_orchestrator as orch_module
from harness.shared.mango_mas_orchestrator import MangoMASOrchestrator

# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------


def _mk_agent_dirs(workspace: Path, names: list[str]) -> None:
    """Create ``.mango/agents/<name>.md`` prompt files inside *workspace*."""
    agents = workspace / ".mango" / "agents"
    agents.mkdir(parents=True, exist_ok=True)
    for name in names:
        (agents / f"{name}.md").write_text(f"# {name}\nYou are the {name} agent.", encoding="utf-8")


@pytest.fixture
def mock_workspace(tmp_path: Path) -> Path:
    """A temp workspace pre-populated with the agents the MAS loop expects."""
    _mk_agent_dirs(
        tmp_path, ["planner", "nemotron-reasoner", "verifier", "test-agent"]
    )
    return tmp_path


def _resp(content: str | None = None, tool_calls: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    """Build an OpenAI-style chat completion response for the mocked bridge."""
    message: dict[str, Any] = {"role": "assistant", "content": content}
    if tool_calls:
        message["tool_calls"] = tool_calls
    return {"choices": [{"message": message}]}


def _tool_call(
    name: str,
    arguments: dict[str, Any] | str | None = None,
    call_id: str = "call_1",
) -> dict[str, Any]:
    """Build a single ``tool_calls`` entry.

    ``arguments`` may be a dict (will be JSON-encoded) or a raw string (used
    verbatim, to exercise the JSONDecodeError branch).
    """
    if arguments is None:
        args_str = "{}"
    elif isinstance(arguments, str):
        args_str = arguments
    else:
        args_str = json.dumps(arguments)
    return {
        "id": call_id,
        "function": {"name": name, "arguments": args_str},
    }


@pytest.fixture
def mock_complete_chat(mocker):
    """Patch the Nemotron bridge inside the orchestrator; return the mock."""
    return mocker.patch.object(orch_module, "complete_chat")


# ---------------------------------------------------------------------------
# __init__
# ---------------------------------------------------------------------------


class TestInit:
    def test_defaults(self, mock_workspace: Path) -> None:
        orch = MangoMASOrchestrator(workspace_dir=mock_workspace)
        assert orch.workspace_dir == mock_workspace
        assert orch.api_key is None
        assert orch.model is None
        assert orch.max_iterations == 10
        assert orch.api_timeout == 300
        assert orch.tool_timeout == 30
        assert orch.agents_dir == mock_workspace / ".mango" / "agents"
        assert orch.hooks_dir == mock_workspace / ".mango" / "hooks"
        assert orch.conversation_history == []

    def test_param_overrides(self, mock_workspace: Path) -> None:
        orch = MangoMASOrchestrator(
            workspace_dir=mock_workspace,
            api_key="fake-key",
            model="my-model",
            max_iterations=3,
            api_timeout=42,
            tool_timeout=7,
        )
        assert orch.api_key == "fake-key"
        assert orch.model == "my-model"
        assert orch.max_iterations == 3
        assert orch.api_timeout == 42
        assert orch.tool_timeout == 7


# ---------------------------------------------------------------------------
# load_agent_prompt
# ---------------------------------------------------------------------------


class TestLoadAgentPrompt:
    def test_success(self, mock_workspace: Path) -> None:
        orch = MangoMASOrchestrator(workspace_dir=mock_workspace)
        prompt = orch.load_agent_prompt("test-agent")
        assert "test-agent" in prompt

    def test_missing_agent_raises(self, mock_workspace: Path) -> None:
        orch = MangoMASOrchestrator(workspace_dir=mock_workspace)
        with pytest.raises(FileNotFoundError, match="Agent definition not found"):
            orch.load_agent_prompt("does-not-exist")


# ---------------------------------------------------------------------------
# _run_hook
# ---------------------------------------------------------------------------


class TestRunHook:
    def test_hook_missing_is_noop(self, mock_workspace: Path) -> None:
        orch = MangoMASOrchestrator(workspace_dir=mock_workspace)
        # No hook script present -> executes without raising and does nothing.
        orch._run_hook("pre-nemotron-run", task="t", agent="a")
        assert not (mock_workspace / ".mango" / "hooks" / "pre-nemotron-run.sh").exists()

    def test_hook_exists_and_runs(self, mock_workspace: Path) -> None:
        hooks = mock_workspace / ".mango" / "hooks"
        hooks.mkdir(parents=True, exist_ok=True)
        (hooks / "pre-nemotron-run.sh").write_text('echo ran > hook_marker.txt\n', encoding="utf-8")
        orch = MangoMASOrchestrator(workspace_dir=mock_workspace)
        orch._run_hook("pre-nemotron-run", task="t", agent="a")
        assert (mock_workspace / "hook_marker.txt").exists()

    def test_hook_raises_propagates(self, mock_workspace: Path) -> None:
        hooks = mock_workspace / ".mango" / "hooks"
        hooks.mkdir(parents=True, exist_ok=True)
        (hooks / "pre-nemotron-run.sh").write_text("exit 1\n", encoding="utf-8")
        orch = MangoMASOrchestrator(workspace_dir=mock_workspace, tool_timeout=5)
        with pytest.raises(subprocess.CalledProcessError):
            orch._run_hook("pre-nemotron-run", task="t", agent="a")


# ---------------------------------------------------------------------------
# _execute_write_file
# ---------------------------------------------------------------------------


class TestExecuteWriteFile:
    def test_success(self, mock_workspace: Path) -> None:
        orch = MangoMASOrchestrator(workspace_dir=mock_workspace)
        result = orch._execute_write_file("out/sub.txt", "hello")
        assert result.startswith("Success:")
        assert (mock_workspace / "out" / "sub.txt").read_text(encoding="utf-8") == "hello"

    def test_path_escapes_workspace(self, mock_workspace: Path) -> None:
        orch = MangoMASOrchestrator(workspace_dir=mock_workspace)
        result = orch._execute_write_file("../../etc/passwd", "pwned")
        assert "path escapes workspace" in result

    def test_write_failure_returns_error(self, mock_workspace: Path) -> None:
        orch = MangoMASOrchestrator(workspace_dir=mock_workspace)
        (mock_workspace / "a_dir").mkdir(parents=True, exist_ok=True)
        result = orch._execute_write_file("a_dir", "content")
        assert result.startswith("Error writing file")


# ---------------------------------------------------------------------------
# _execute_run_command (incl. pretooluse guard)
# ---------------------------------------------------------------------------


class TestExecuteRunCommand:
    def _guard_script(self, workspace: Path, body: str) -> Path:
        """Materialize a fake pretooluse_guard.py at the expected path."""
        guard = workspace / "harness" / "shared" / "pretooluse_guard.py"
        guard.parent.mkdir(parents=True, exist_ok=True)
        guard.write_text(body, encoding="utf-8")
        return guard

    def test_guard_blocks_command(self, mock_workspace: Path) -> None:
        self._guard_script(
            mock_workspace,
            "import sys; sys.stderr.write('BLOCKED by policy\\n'); sys.exit(2)\n",
        )
        orch = MangoMASOrchestrator(workspace_dir=mock_workspace, tool_timeout=5)
        result = orch._execute_run_command("echo hi")
        assert result.startswith("Error: Command blocked by policy guard")
        assert "BLOCKED by policy" in result

    def test_guard_passes_then_command_runs(self, mock_workspace: Path) -> None:
        self._guard_script(mock_workspace, "import sys; sys.exit(0)\n")
        orch = MangoMASOrchestrator(workspace_dir=mock_workspace, tool_timeout=5)
        result = orch._execute_run_command("echo 'guard ok'")
        assert "guard ok" in result

    def test_no_output(self, mock_workspace: Path) -> None:
        orch = MangoMASOrchestrator(workspace_dir=mock_workspace, tool_timeout=5)
        result = orch._execute_run_command("true")
        assert "generated no output" in result

    def test_stderr_captured(self, mock_workspace: Path) -> None:
        orch = MangoMASOrchestrator(workspace_dir=mock_workspace, tool_timeout=5)
        result = orch._execute_run_command("echo oops >&2")
        assert "[STDERR]" in result
        assert "oops" in result

    def test_timeout(self, mock_workspace: Path) -> None:
        orch = MangoMASOrchestrator(workspace_dir=mock_workspace, tool_timeout=1)
        result = orch._execute_run_command("sleep 5")
        assert "timed out" in result

    def test_generic_exception(self, mock_workspace: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        def _boom(*_a: Any, **_kw: Any) -> Any:
            raise OSError("kaboom")

        monkeypatch.setattr(orch_module.subprocess, "run", _boom)
        orch = MangoMASOrchestrator(workspace_dir=mock_workspace, tool_timeout=5)
        result = orch._execute_run_command("anything")
        assert result.startswith("Error executing command")
        assert "kaboom" in result


# ---------------------------------------------------------------------------
# execute_agent (network fully mocked)
# ---------------------------------------------------------------------------


class TestExecuteAgent:
    def test_plain_text_response(self, mock_workspace: Path, mock_complete_chat) -> None:
        mock_complete_chat.return_value = _resp("All done.")
        orch = MangoMASOrchestrator(workspace_dir=mock_workspace)
        assert orch.execute_agent("test-agent", "say hi") == "All done."

    def test_model_passed_in_kwargs(self, mock_workspace: Path, mock_complete_chat) -> None:
        mock_complete_chat.return_value = _resp("ok")
        orch = MangoMASOrchestrator(workspace_dir=mock_workspace, model="custom-model")
        orch.execute_agent("test-agent", "go")
        kwargs = mock_complete_chat.call_args.kwargs
        assert kwargs["model"] == "custom-model"

    def test_api_failure_raises_runtime_error(self, mock_workspace: Path, mock_complete_chat) -> None:
        mock_complete_chat.side_effect = ValueError("network down")
        orch = MangoMASOrchestrator(workspace_dir=mock_workspace)
        with pytest.raises(RuntimeError, match="API failed"):
            orch.execute_agent("test-agent", "go")

    def test_write_file_tool_call(self, mock_workspace: Path, mock_complete_chat) -> None:
        mock_complete_chat.side_effect = [
            _resp(None, tool_calls=[_tool_call("write_file", {"filepath": "out.txt", "content": "data"})]),
            _resp("Wrote the file."),
        ]
        orch = MangoMASOrchestrator(workspace_dir=mock_workspace)
        assert orch.execute_agent("test-agent", "write out.txt") == "Wrote the file."
        assert (mock_workspace / "out.txt").read_text(encoding="utf-8") == "data"

    def test_run_command_tool_call(self, mock_workspace: Path, mock_complete_chat) -> None:
        mock_complete_chat.side_effect = [
            _resp(None, tool_calls=[_tool_call("run_command", {"command": "echo hi"})]),
            _resp("Command done."),
        ]
        orch = MangoMASOrchestrator(workspace_dir=mock_workspace, tool_timeout=5)
        assert orch.execute_agent("test-agent", "run echo") == "Command done."

    def test_invalid_tool_args_json(self, mock_workspace: Path, mock_complete_chat) -> None:
        mock_complete_chat.side_effect = [
            _resp(None, tool_calls=[_tool_call("write_file", "not-valid-json{")]),
            _resp("Recovered."),
        ]
        orch = MangoMASOrchestrator(workspace_dir=mock_workspace)
        assert orch.execute_agent("test-agent", "go") == "Recovered."

    def test_unknown_tool(self, mock_workspace: Path, mock_complete_chat) -> None:
        mock_complete_chat.side_effect = [
            _resp(None, tool_calls=[_tool_call("frobnicate", {"x": 1})]),
            _resp("Done."),
        ]
        orch = MangoMASOrchestrator(workspace_dir=mock_workspace)
        assert orch.execute_agent("test-agent", "go") == "Done."

    def test_meta_tools_knowledge_gap_and_hypothesis(
        self, mock_workspace: Path, mock_complete_chat, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        calls: list[str] = []

        def _fake_gap(question: str, what_needed: str, proposed_approach: str) -> str:
            calls.append("gap")
            return "gap-logged"

        def _fake_hyp(claim: str, reasoning: str, confidence: float) -> str:
            calls.append("hyp")
            return "hyp-logged"

        monkeypatch.setattr(orch_module, "knowledge_gap_log", _fake_gap)
        monkeypatch.setattr(orch_module, "hypothesis_register", _fake_hyp)

        mock_complete_chat.side_effect = [
            _resp(None, tool_calls=[_tool_call("knowledge_gap_log", {"question": "q", "what_needed": "w", "proposed_approach": "p"})]),
            _resp(None, tool_calls=[_tool_call("hypothesis_register", {"claim": "c", "reasoning": "r", "confidence": 0.9})]),
            _resp("Done."),
        ]
        orch = MangoMASOrchestrator(workspace_dir=mock_workspace)
        assert orch.execute_agent("test-agent", "go") == "Done."
        assert calls == ["gap", "hyp"]

    def test_empty_content_fallback_uses_tool_result(self, mock_workspace: Path, mock_complete_chat) -> None:
        mock_complete_chat.side_effect = [
            _resp(None, tool_calls=[_tool_call("write_file", {"filepath": "f.txt", "content": "x"})]),
            _resp(""),
        ]
        orch = MangoMASOrchestrator(workspace_dir=mock_workspace)
        result = orch.execute_agent("test-agent", "go")
        assert result.startswith("Completed via tool execution.")
        assert "Success: Wrote" in result

    def test_debug_dump_redaction(
        self, mock_workspace: Path, mock_complete_chat, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        secret = "super-secret-key-value"
        mock_complete_chat.return_value = _resp(f"result with {secret}")
        import tempfile

        monkeypatch.setattr(tempfile, "gettempdir", lambda: str(tmp_path))
        monkeypatch.setenv("MANGO_DEBUG_DUMP", "1")
        orch = MangoMASOrchestrator(workspace_dir=mock_workspace, api_key=secret)
        result = orch.execute_agent("test-agent", "go")
        assert secret in result
        dump_dir = tmp_path / "mango_debug"
        dumps = list(dump_dir.glob("debug_test-agent_*.json"))
        assert dumps, "expected a debug dump file to be created"
        dumped = json.loads(dumps[0].read_text(encoding="utf-8"))
        joined = json.dumps(dumped)
        assert secret not in joined
        assert "<REDACTED_API_KEY>" in joined

    def test_max_iterations_timeout_path(self, mock_workspace: Path, mock_complete_chat) -> None:
        tc = _tool_call("write_file", {"filepath": "loop.txt", "content": "x"})
        mock_complete_chat.return_value = _resp(None, tool_calls=[tc])
        orch = MangoMASOrchestrator(workspace_dir=mock_workspace, max_iterations=2)
        with pytest.raises(RuntimeError, match="exceeded maximum tool iterations"):
            orch.execute_agent("test-agent", "loop")


# ---------------------------------------------------------------------------
# execute_sequential_thinking_loop (planner -> reasoner -> verifier, mocked)
# ---------------------------------------------------------------------------


class TestSequentialThinkingLoop:
    def test_full_loop_mocked(
        self, mock_workspace: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        responses = [
            _resp("PLAN: do the thing."),
            _resp("CODE: implemented it."),
            _resp("VERIFY: PASS"),
        ]

        def _fake_complete_chat(**_kw: Any) -> dict[str, Any]:
            return responses.pop(0)

        monkeypatch.setattr(orch_module, "complete_chat", _fake_complete_chat)

        orch = MangoMASOrchestrator(workspace_dir=mock_workspace, tool_timeout=5)
        result = orch.execute_sequential_thinking_loop("implement feature X")
        assert result == "VERIFY: PASS"

        system_msgs = [m for m in orch.conversation_history if m.get("role") == "system"]
        prompts = " ".join(m["content"] for m in system_msgs).lower()
        assert "planner" in prompts
        assert "reasoner" in prompts
        assert "verifier" in prompts


# ---------------------------------------------------------------------------
# Live tests (deselected by default) — would touch a real NVIDIA_API_KEY.
# ---------------------------------------------------------------------------


@pytest.mark.live
class TestLiveOrchestrator:
    """Real-API smoke tests. Skipped unless explicitly selected with ``-m live``."""

    def test_live_execute_agent(self, mock_workspace: Path) -> None:  # pragma: no cover
        orch = MangoMASOrchestrator(workspace_dir=mock_workspace, api_key=os.environ.get("NVIDIA_API_KEY"))
        assert orch.execute_agent("test-agent", "Reply with the word: OK")  # noqa: S101
