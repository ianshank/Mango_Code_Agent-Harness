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
