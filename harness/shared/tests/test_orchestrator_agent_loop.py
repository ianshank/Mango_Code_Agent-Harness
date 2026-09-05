"""Tests for MangoMASOrchestrator ReAct execution loop, sequential thinking, and budget limits."""

from __future__ import annotations

import json
import logging
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

        from harness.shared.orchestrator import dispatcher

        monkeypatch.setattr(dispatcher, "knowledge_gap_log", _fake_gap)
        monkeypatch.setattr(dispatcher, "hypothesis_register", _fake_hyp)

        mock_complete_chat.side_effect = [
            _resp(
                None,
                tool_calls=[
                    _tool_call(
                        "knowledge_gap_log",
                        {"question": "q", "what_needed": "w", "proposed_approach": "p"},
                    )
                ],
            ),
            _resp(
                None,
                tool_calls=[
                    _tool_call(
                        "hypothesis_register",
                        {"claim": "c", "reasoning": "r", "confidence": 0.9},
                    )
                ],
            ),
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
    def test_full_loop_mocked(self, mock_workspace: Path, monkeypatch: pytest.MonkeyPatch) -> None:
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
        assert orch.execution_loop.max_iterations == limits["max_iterations"]
        assert orch.execution_loop.api_timeout == limits["api_timeout_sec"]
        assert orch.execution_loop.hook_runner.tool_timeout == limits["tool_timeout_sec"]
        assert orch.execution_loop.max_tool_calls_per_task == max_tool_calls_per_task()
        assert orch.verification_timeout == limits["verification_timeout_sec"]
        assert orch._verification._timeout == limits["verification_timeout_sec"]

    def test_the_verification_timeout_does_not_follow_api_timeout(self, mock_workspace: Path) -> None:
        """H16, at the facade: an explicit `api_timeout` used to be handed to
        the `VerificationRunner` as well, so a caller tuning model latency
        was also -- silently -- retuning how long the test suite may run."""
        from harness.shared.policy_loader import orchestrator_defaults

        orch = MangoMASOrchestrator(workspace_dir=mock_workspace, api_timeout=42)
        assert orch.execution_loop.api_timeout == 42
        assert orch._verification._timeout == orchestrator_defaults()["verification_timeout_sec"]
        assert orch._verification._timeout != 42

    def test_explicit_arguments_still_override_policy(self, mock_workspace: Path) -> None:
        orch = MangoMASOrchestrator(workspace_dir=mock_workspace, max_iterations=3, api_timeout=42, tool_timeout=7)
        actual = (
            orch.execution_loop.max_iterations,
            orch.execution_loop.api_timeout,
            orch.execution_loop.hook_runner.tool_timeout,
        )
        assert actual == (3, 42, 7)

    def test_tool_call_budget_is_enforced(self, mock_workspace: Path, mock_complete_chat) -> None:
        tc = _tool_call("write_file", {"filepath": "loop.txt", "content": "x"})
        mock_complete_chat.return_value = _resp(None, tool_calls=[tc, tc])
        orch = MangoMASOrchestrator(workspace_dir=mock_workspace, max_iterations=50)
        orch.execution_loop.max_tool_calls_per_task = 3
        with pytest.raises(RuntimeError, match="tool-call budget"):
            orch.execute_agent("nemotron-reasoner", "budget")

    def test_budget_not_hit_when_under_limit(self, mock_workspace: Path, mock_complete_chat) -> None:
        tc = _tool_call("write_file", {"filepath": "ok.txt", "content": "x"})
        mock_complete_chat.side_effect = [_resp(None, tool_calls=[tc]), _resp("done")]
        orch = MangoMASOrchestrator(workspace_dir=mock_workspace)
        assert orch.execute_agent("nemotron-reasoner", "small task") == "done"


class TestTheBudgetIsPerTaskNotPerRole:
    """`agent_defaults.max_tool_calls_per_task` says per task; `execute_loop`
    handed each of the three roles a fresh `ToolBudget`, so a task could spend
    three times the declared value (2026 standards audit M1). One budget is
    now minted per loop and threaded through every role."""

    def _reasoner_then_verifier(self, mock_complete_chat, reasoner_calls: int, verifier_calls: int) -> None:
        reasoner_tc = _tool_call("write_file", {"filepath": "r.txt", "content": "x"})
        verifier_tc = _tool_call("read_file", {"filepath": "r.txt"})
        mock_complete_chat.side_effect = [
            _resp("Plan: do work"),
            _resp(None, tool_calls=[reasoner_tc] * reasoner_calls),
            _resp("Code: done"),
            _resp(None, tool_calls=[verifier_tc] * verifier_calls),
            _resp("Verifier: done"),
        ]

    def test_the_sum_across_roles_cannot_exceed_the_task_budget(self, mock_workspace: Path, mock_complete_chat) -> None:
        """2 + 2 > 3. With a per-role budget the verifier would have had its own
        3 and finished; with a per-task budget the fourth call is refused."""
        self._reasoner_then_verifier(mock_complete_chat, reasoner_calls=2, verifier_calls=2)
        orch = MangoMASOrchestrator(workspace_dir=mock_workspace, tool_timeout=5)
        orch.execution_loop.max_tool_calls_per_task = 3
        with pytest.raises(RuntimeError, match="verifier exceeded the tool-call budget"):
            orch.execute_loop("Do a task")

    def test_a_task_within_the_budget_completes(self, mock_workspace: Path, mock_complete_chat) -> None:
        """Control: 2 + 1 <= 3, so the same shape passes when the sum fits."""
        self._reasoner_then_verifier(mock_complete_chat, reasoner_calls=2, verifier_calls=1)
        orch = MangoMASOrchestrator(workspace_dir=mock_workspace, tool_timeout=5)
        orch.execution_loop.max_tool_calls_per_task = 3
        assert orch.execute_loop("Do a task").verifier_message == "Verifier: done"

    def test_each_loop_starts_from_a_full_budget(self, mock_workspace: Path, mock_complete_chat) -> None:
        """The budget is per task, not per orchestrator: a second loop on the
        same facade is a new task and gets a new allowance."""
        orch = MangoMASOrchestrator(workspace_dir=mock_workspace, tool_timeout=5)
        orch.execution_loop.max_tool_calls_per_task = 3
        for _ in range(2):
            self._reasoner_then_verifier(mock_complete_chat, reasoner_calls=2, verifier_calls=1)
            assert orch.execute_loop("Do a task").verifier_message == "Verifier: done"


class TestStructuredRunEvents:
    """One `run_id` per loop, on every model event and every tool event, with
    the fields the observability contract names and none of the payload
    (2026 standards audit H6)."""

    LOGGERS = ("harness.shared.orchestrator.loop", "harness.shared.orchestrator.dispatcher")

    def _events(self, caplog: pytest.LogCaptureFixture, name: str) -> list[logging.LogRecord]:
        return [r for r in caplog.records if getattr(r, "event", None) == name]

    def test_model_and_tool_events_carry_the_same_run_id(
        self, mock_workspace: Path, mock_complete_chat, caplog: pytest.LogCaptureFixture
    ) -> None:
        tc = _tool_call("write_file", {"filepath": "r.txt", "content": "x"})
        planner = _resp("Plan: do work")
        planner["usage"] = {"prompt_tokens": 12, "completion_tokens": 7}
        mock_complete_chat.side_effect = [
            planner,
            _resp(None, tool_calls=[tc]),
            _resp("Code: done"),
            _resp("Verifier: done"),
        ]
        orch = MangoMASOrchestrator(workspace_dir=mock_workspace, tool_timeout=5)
        assert orch.run_id is None
        with caplog.at_level(logging.DEBUG, logger="harness.shared.orchestrator"):
            orch.execute_loop("Do a task")

        assert orch.run_id is not None and len(orch.run_id) == 32
        model_events = self._events(caplog, "model_call")
        tool_events = self._events(caplog, "tool_call")
        assert len(model_events) == 4, "one event per completion call"
        assert len(tool_events) == 1
        assert {getattr(r, "run_id", None) for r in model_events + tool_events} == {orch.run_id}

        first = vars(model_events[0])
        assert (first["agent"], first["iteration"]) == ("planner", 0)
        assert (first["prompt_tokens"], first["completion_tokens"]) == (12, 7)
        assert isinstance(first["latency_ms"], int) and first["latency_ms"] >= 0
        assert vars(model_events[1])["prompt_tokens"] is None, "no usage block, no invented count"

        tool = vars(tool_events[0])
        assert (tool["tool"], tool["permitted"], tool["outcome"]) == ("write_file", True, "executed")
        assert isinstance(tool["duration_ms"], int) and tool["duration_ms"] >= 0
        assert tool_events[0].levelno == logging.DEBUG

    def test_a_new_loop_mints_a_new_run_id(self, mock_workspace: Path, mock_complete_chat) -> None:
        mock_complete_chat.side_effect = [_resp("p"), _resp("c"), _resp("v")] * 2
        orch = MangoMASOrchestrator(workspace_dir=mock_workspace, tool_timeout=5)
        orch.execute_loop("one")
        first = orch.run_id
        orch.execute_loop("two")
        assert first is not None and orch.run_id != first

    def test_a_denied_tool_is_a_warning_event_that_names_no_arguments(
        self, mock_workspace: Path, mock_complete_chat, caplog: pytest.LogCaptureFixture
    ) -> None:
        secret_path = "very-secret-path.txt"
        mock_complete_chat.side_effect = [
            _resp(None, tool_calls=[_tool_call("write_file", {"filepath": secret_path, "content": "x"})]),
            _resp("done"),
        ]
        orch = MangoMASOrchestrator(workspace_dir=mock_workspace, tool_timeout=5)
        with caplog.at_level(logging.DEBUG, logger="harness.shared.orchestrator"):
            # The verifier holds no `write_file`, so the authority model refuses it.
            orch.execute_agent("verifier", "go")
        (event,) = self._events(caplog, "tool_call")
        fields = (event.levelno, getattr(event, "permitted", None), getattr(event, "outcome", None))
        assert fields == (logging.WARNING, False, "denied_role")
        assert secret_path not in event.getMessage()
        assert all(secret_path not in str(v) for v in vars(event).values())

    def test_a_policy_denial_inside_the_handler_is_logged_as_a_denial(
        self, mock_workspace: Path, mock_complete_chat, caplog: pytest.LogCaptureFixture
    ) -> None:
        """The role check passes (the reasoner holds `write_file`); the write
        policy refuses the credential file inside the handler. The event used
        to say `permitted=True, outcome=executed` because the handler returned
        normally -- the refusal is text for the model. The result now carries
        its outcome (Copilot review on PR #86)."""
        mock_complete_chat.side_effect = [
            _resp(None, tool_calls=[_tool_call("write_file", {"filepath": ".env", "content": "K=v"})]),
            _resp("done"),
        ]
        orch = MangoMASOrchestrator(workspace_dir=mock_workspace, tool_timeout=5)
        with caplog.at_level(logging.DEBUG, logger="harness.shared.orchestrator"):
            orch.execute_agent("nemotron-reasoner", "go")
        (event,) = self._events(caplog, "tool_call")
        fields = (event.levelno, getattr(event, "permitted", None), getattr(event, "outcome", None))
        assert fields == (logging.WARNING, False, "denied_policy")
        assert not (mock_workspace / ".env").exists()

    def test_a_permitted_call_that_fails_is_not_a_denial(
        self, mock_workspace: Path, mock_complete_chat, caplog: pytest.LogCaptureFixture
    ) -> None:
        mock_complete_chat.side_effect = [
            _resp(None, tool_calls=[_tool_call("read_file", {"filepath": "absent.txt"})]),
            _resp("done"),
        ]
        orch = MangoMASOrchestrator(workspace_dir=mock_workspace, tool_timeout=5)
        with caplog.at_level(logging.DEBUG, logger="harness.shared.orchestrator"):
            orch.execute_agent("nemotron-reasoner", "go")
        (event,) = self._events(caplog, "tool_call")
        fields = (event.levelno, getattr(event, "permitted", None), getattr(event, "outcome", None))
        assert fields == (logging.DEBUG, True, "failed")


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

        from harness.shared.orchestrator import loop

        monkeypatch.setattr(loop, "shadow_planner_enabled", lambda: True)

        def mock_shadow_raise(ctx):
            raise RuntimeError("shadow planner failed unexpectedly")

        monkeypatch.setattr(loop, "run_shadow_comparison", mock_shadow_raise)

        res = orch.execute_loop("Do a task")
        assert res.plan == "Plan: do work"
        assert res.code_output == "Code: done"
        assert res.verifier_message == "Verifier: done"
        assert res.verdict is not None


class TestAFailedModelCallIsStillAnEvent:
    def test_the_failure_path_emits_a_model_call_event(
        self, mock_workspace: Path, mock_complete_chat, caplog: pytest.LogCaptureFixture
    ) -> None:
        """A request that raises used to log a bare error with no run_id or
        latency; the structured event now covers both outcomes (Copilot review
        on PR #86)."""
        mock_complete_chat.side_effect = RuntimeError("upstream 503")
        orch = MangoMASOrchestrator(workspace_dir=mock_workspace, tool_timeout=5)
        with caplog.at_level(logging.DEBUG, logger="harness.shared.orchestrator"), pytest.raises(RuntimeError):
            orch.execute_loop("Do a task")

        events = [r for r in caplog.records if getattr(r, "event", None) == "model_call"]
        assert len(events) == 1
        event = events[0]
        assert getattr(event, "outcome", None) == "error"
        assert getattr(event, "error_type", None) == "RuntimeError"
        assert getattr(event, "run_id", None) == orch.run_id
        assert event.levelno == logging.WARNING
