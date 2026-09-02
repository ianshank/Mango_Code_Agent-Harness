"""Tests for MangoMASOrchestrator initialization and prompt loading."""

from __future__ import annotations

from pathlib import Path

import pytest

from harness.shared.mango_mas_orchestrator import MangoMASOrchestrator


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


class TestLoadAgentPrompt:
    def test_success(self, mock_workspace: Path) -> None:
        orch = MangoMASOrchestrator(workspace_dir=mock_workspace)
        prompt = orch.load_agent_prompt("nemotron-reasoner")
        assert "nemotron-reasoner" in prompt

    def test_missing_agent_raises(self, mock_workspace: Path) -> None:
        orch = MangoMASOrchestrator(workspace_dir=mock_workspace)
        with pytest.raises(FileNotFoundError, match="Agent definition not found"):
            orch.load_agent_prompt("does-not-exist")


class TestFacadePassThroughs:
    """The facade's private pass-throughs (mango_mas_orchestrator.py lines 145-173)
    exist for external tooling that still calls them. Each must hand the caller's
    arguments to the composed dispatcher / execution loop unchanged and return
    what that component returns -- a pass-through that reorders or drops an
    argument would be an API break no other test could see (R-TDH-25)."""

    def test_read_file_forwards_the_line_bounds(self, mock_workspace: Path, mocker) -> None:
        orch = MangoMASOrchestrator(workspace_dir=mock_workspace)
        spy = mocker.patch.object(orch.dispatcher, "_execute_read_file", return_value="lines 2-5")
        assert orch._execute_read_file("a.py", 2, 5) == "lines 2-5"
        spy.assert_called_once_with("a.py", 2, 5)

    def test_read_file_defaults_the_bounds_to_none(self, mock_workspace: Path, mocker) -> None:
        orch = MangoMASOrchestrator(workspace_dir=mock_workspace)
        spy = mocker.patch.object(orch.dispatcher, "_execute_read_file", return_value="whole file")
        assert orch._execute_read_file("a.py") == "whole file"
        spy.assert_called_once_with("a.py", None, None)

    def test_apply_patch_forwards_old_and_new_text_in_order(self, mock_workspace: Path, mocker) -> None:
        orch = MangoMASOrchestrator(workspace_dir=mock_workspace)
        spy = mocker.patch.object(orch.dispatcher, "_execute_apply_patch", return_value="patched")
        assert orch._execute_apply_patch("a.py", "old", "new") == "patched"
        spy.assert_called_once_with("a.py", "old", "new")

    def test_run_command_forwards_the_command(self, mock_workspace: Path, mocker) -> None:
        orch = MangoMASOrchestrator(workspace_dir=mock_workspace)
        spy = mocker.patch.object(orch.dispatcher, "_execute_run_command", return_value="ran")
        assert orch._execute_run_command("echo hi") == "ran"
        spy.assert_called_once_with("echo hi")

    def test_finalize_response_forwards_the_same_message_list(self, mock_workspace: Path, mocker) -> None:
        """The loop mutates the final assistant message in place, so the facade must
        pass the caller's list object itself, not a copy."""
        orch = MangoMASOrchestrator(workspace_dir=mock_workspace)
        spy = mocker.patch.object(orch.execution_loop, "_finalize_response", return_value="final")
        messages = [{"role": "assistant", "content": None}]
        assert orch._finalize_response(messages, "done") == "final"
        spy.assert_called_once_with(messages, "done")
        assert spy.call_args.args[0] is messages

    def test_dump_debug_history_forwards_the_agent_name(self, mock_workspace: Path, mocker) -> None:
        orch = MangoMASOrchestrator(workspace_dir=mock_workspace)
        spy = mocker.patch.object(orch.execution_loop, "_dump_debug_history", return_value=None)
        orch._dump_debug_history("verifier")
        spy.assert_called_once_with("verifier")

    def test_harness_verdict_returns_the_loops_verdict(self, mock_workspace: Path, mocker) -> None:
        orch = MangoMASOrchestrator(workspace_dir=mock_workspace)
        sentinel = object()
        spy = mocker.patch.object(orch.execution_loop, "_harness_verdict", return_value=sentinel)
        assert orch._harness_verdict() is sentinel
        spy.assert_called_once_with()
