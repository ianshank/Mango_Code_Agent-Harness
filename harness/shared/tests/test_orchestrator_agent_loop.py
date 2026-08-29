"""Tests for MangoMASOrchestrator ReAct execution loop, sequential thinking, and budget limits."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from harness.shared import mango_mas_orchestrator as orch_module
from harness.shared.mango_mas_orchestrator import MangoMASOrchestrator
from harness.shared.nemotron_bridge import resolve_api_key
from harness.shared.tests._orchestrator_helpers import (
    _resp,
    _tool_call,
)


class TestExecuteAgent:
    def test_plain_text_response(self, mock_workspace: Path, mock_complete_chat) -> None:
        mock_complete_chat.return_value = _resp("All done.")
        orch = MangoMASOrchestrator(workspace_dir=mock_workspace)
        assert orch.execute_agent("nemotron-reasoner", "say hi") == "All done."

    def test_model_passed_in_kwargs(self, mock_workspace: Path, mock_complete_chat) -> None:
        mock_complete_chat.return_value = _resp("ok")
        orch = MangoMASOrchestrator(workspace_dir=mock_workspace, model="custom-model")
        orch.execute_agent("nemotron-reasoner", "go")
        kwargs = mock_complete_chat.call_args.kwargs
        assert kwargs["model"] == "custom-model"

    def test_api_failure_raises_runtime_error(self, mock_workspace: Path, mock_complete_chat) -> None:
        mock_complete_chat.side_effect = ValueError("network down")
        orch = MangoMASOrchestrator(workspace_dir=mock_workspace)
        with pytest.raises(RuntimeError, match="API failed"):
            orch.execute_agent("nemotron-reasoner", "go")

    def test_write_file_tool_call(self, mock_workspace: Path, mock_complete_chat) -> None:
        mock_complete_chat.side_effect = [
            _resp(None, tool_calls=[_tool_call("write_file", {"filepath": "out.txt", "content": "data"})]),
            _resp("Wrote the file."),
        ]
        orch = MangoMASOrchestrator(workspace_dir=mock_workspace)
        assert orch.execute_agent("nemotron-reasoner", "write out.txt") == "Wrote the file."
        assert (mock_workspace / "out.txt").read_text(encoding="utf-8") == "data"

    def test_run_command_tool_call(self, mock_workspace: Path, mock_complete_chat) -> None:
        mock_complete_chat.side_effect = [
            _resp(None, tool_calls=[_tool_call("run_command", {"command": "echo hi"})]),
            _resp("Command done."),
        ]
        orch = MangoMASOrchestrator(workspace_dir=mock_workspace, tool_timeout=5)
        assert orch.execute_agent("nemotron-reasoner", "run echo") == "Command done."

    def test_invalid_tool_args_json(self, mock_workspace: Path, mock_complete_chat) -> None:
        mock_complete_chat.side_effect = [
            _resp(None, tool_calls=[_tool_call("write_file", "not-valid-json{")]),
            _resp("Recovered."),
        ]
        orch = MangoMASOrchestrator(workspace_dir=mock_workspace)
        assert orch.execute_agent("nemotron-reasoner", "go") == "Recovered."

    def test_unknown_tool(self, mock_workspace: Path, mock_complete_chat) -> None:
        mock_complete_chat.side_effect = [
            _resp(None, tool_calls=[_tool_call("frobnicate", {"x": 1})]),
            _resp("Done."),
        ]
        orch = MangoMASOrchestrator(workspace_dir=mock_workspace)
        assert orch.execute_agent("nemotron-reasoner", "go") == "Done."

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
            _resp(None, tool_calls=[_tool_call(
                "knowledge_gap_log",
                {"question": "q", "what_needed": "w", "proposed_approach": "p"},
            )]),
            _resp(None, tool_calls=[_tool_call(
                "hypothesis_register",
                {"claim": "c", "reasoning": "r", "confidence": 0.9},
            )]),
            _resp("Done."),
        ]
        orch = MangoMASOrchestrator(workspace_dir=mock_workspace)
        assert orch.execute_agent("nemotron-reasoner", "go") == "Done."
        assert calls == ["gap", "hyp"]

    def test_empty_content_fallback_uses_tool_result(self, mock_workspace: Path, mock_complete_chat) -> None:
        mock_complete_chat.side_effect = [
            _resp(None, tool_calls=[_tool_call("write_file", {"filepath": "f.txt", "content": "x"})]),
            _resp(""),
        ]
        orch = MangoMASOrchestrator(workspace_dir=mock_workspace)
        result = orch.execute_agent("nemotron-reasoner", "go")
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
        result = orch.execute_agent("nemotron-reasoner", "go")
        assert secret in result
        dump_dir = tmp_path / "mango_debug"
        dumps = list(dump_dir.glob("debug_nemotron-reasoner_*.json"))
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
            orch.execute_agent("nemotron-reasoner", "loop")


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


IS_LIVE = bool(resolve_api_key())


@pytest.mark.live
@pytest.mark.skipif(not IS_LIVE, reason="Requires NVIDIA_API_KEY")
class TestLiveOrchestrator:
    """Real-API smoke tests. Skipped unless explicitly selected with ``-m live``."""

    def test_live_execute_agent(self, mock_workspace: Path) -> None:  # pragma: no cover
        orch = MangoMASOrchestrator(workspace_dir=mock_workspace, api_key=resolve_api_key())
        assert orch.execute_agent("nemotron-reasoner", "Reply with the word: OK")


class TestPolicySourcedLimits:
    def test_defaults_come_from_the_policy_block(self, mock_workspace: Path) -> None:
        """Constructor defaults now resolve through governance-policy.json."""
        from harness.shared.policy_loader import max_tool_calls_per_task, orchestrator_defaults

        limits = orchestrator_defaults()
        orch = MangoMASOrchestrator(workspace_dir=mock_workspace)
        assert orch.max_iterations == limits["max_iterations"]
        assert orch.api_timeout == limits["api_timeout_sec"]
        assert orch.tool_timeout == limits["tool_timeout_sec"]
        assert orch.max_tool_calls_per_task == max_tool_calls_per_task()

    def test_explicit_arguments_still_override_policy(self, mock_workspace: Path) -> None:
        orch = MangoMASOrchestrator(workspace_dir=mock_workspace, max_iterations=3, api_timeout=42, tool_timeout=7)
        assert (orch.max_iterations, orch.api_timeout, orch.tool_timeout) == (3, 42, 7)

    def test_tool_call_budget_is_enforced(self, mock_workspace: Path, mock_complete_chat) -> None:
        tc = _tool_call("write_file", {"filepath": "loop.txt", "content": "x"})
        mock_complete_chat.return_value = _resp(None, tool_calls=[tc, tc])
        orch = MangoMASOrchestrator(workspace_dir=mock_workspace, max_iterations=50)
        orch.max_tool_calls_per_task = 3
        with pytest.raises(RuntimeError, match="tool-call budget"):
            orch.execute_agent("nemotron-reasoner", "budget")

    def test_budget_not_hit_when_under_limit(self, mock_workspace: Path, mock_complete_chat) -> None:
        tc = _tool_call("write_file", {"filepath": "ok.txt", "content": "x"})
        mock_complete_chat.side_effect = [_resp(None, tool_calls=[tc]), _resp("done")]
        orch = MangoMASOrchestrator(workspace_dir=mock_workspace)
        assert orch.execute_agent("nemotron-reasoner", "small task") == "done"


class TestOrchestrateWorkflow:
    def test_orchestrate_with_shadow_planner_exception(
        self, mock_workspace: Path, mock_complete_chat, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # Mock responses for: planner, reasoner, verifier
        mock_complete_chat.side_effect = [
            _resp("Plan: do work"),
            _resp("Code: done"),
            _resp("Verifier: done"),
        ]
        orch = MangoMASOrchestrator(workspace_dir=mock_workspace)

        monkeypatch.setattr(orch_module, "shadow_planner_enabled", lambda: True)

        def mock_shadow_raise(ctx):
            raise RuntimeError("shadow planner failed unexpectedly")

        monkeypatch.setattr(orch_module, "run_shadow_comparison", mock_shadow_raise)

        res = orch.execute_loop("Do a task")
        assert res.plan == "Plan: do work"
        assert res.code_output == "Code: done"
        assert res.verifier_message == "Verifier: done"
        assert res.verdict is not None

