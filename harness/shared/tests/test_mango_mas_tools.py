import json
from unittest.mock import patch

import pytest

from harness.shared.mango_mas_orchestrator import MangoMASOrchestrator


@pytest.fixture
def mock_workspace(tmp_path):
    # Setup mock workspace with a fake agent definition
    agents_dir = tmp_path / ".mango" / "agents"
    agents_dir.mkdir(parents=True)
    # The active roles, not a fictional one: execution is now evaluated against
    # the authority model, and a role that model does not declare is denied.
    for role in ("planner", "nemotron-reasoner", "verifier"):
        (agents_dir / f"{role}.md").write_text(f"{role} system prompt")
    return tmp_path


def test_tool_write_file_success(mock_workspace):
    """Test that the orchestrator can write a file via tools."""
    # Simulate Nemotron asking to call 'write_file'
    mock_tool_call = {
        "id": "call_123",
        "function": {
            "name": "write_file",
            "arguments": json.dumps({"filepath": "output.txt", "content": "hello world"}),
        },
    }

    mock_response_1 = {"choices": [{"message": {"role": "assistant", "content": None, "tool_calls": [mock_tool_call]}}]}

    mock_response_2 = {
        "choices": [{"message": {"role": "assistant", "content": "I have successfully written the file."}}]
    }

    with patch("harness.shared.mango_mas_orchestrator.complete_chat") as mock_complete:
        mock_complete.side_effect = [mock_response_1, mock_response_2]
        orchestrator = MangoMASOrchestrator(workspace_dir=mock_workspace)

        result = orchestrator.execute_agent("nemotron-reasoner", "Write output.txt")

        # Verify result
        assert result == "I have successfully written the file."

        # Verify file was actually written to the mock workspace
        output_file = mock_workspace / "output.txt"
        assert output_file.exists()
        assert output_file.read_text() == "hello world"


def test_tool_run_command_success(mock_workspace):
    """Test that the orchestrator can run a bash command.

    Driven as `nemotron-reasoner` rather than the previous fictional `test-agent`:
    execution is evaluated against the authority model, and a role that model
    does not declare is denied as an unknown identity (spec R-AC-11).
    """
    mock_tool_call = {
        "id": "call_abc",
        "function": {"name": "run_command", "arguments": json.dumps({"command": "echo 'test command'"})},
    }

    mock_response_1 = {"choices": [{"message": {"role": "assistant", "content": None, "tool_calls": [mock_tool_call]}}]}

    mock_response_2 = {"choices": [{"message": {"role": "assistant", "content": "Command executed successfully."}}]}

    with patch("harness.shared.mango_mas_orchestrator.complete_chat") as mock_complete:
        mock_complete.side_effect = [mock_response_1, mock_response_2]
        orchestrator = MangoMASOrchestrator(workspace_dir=mock_workspace, tool_timeout=5)

        result = orchestrator.execute_agent("nemotron-reasoner", "Run tests")

        assert result == "Command executed successfully."

        # The conversation history should contain the tool result
        # In the orchestrator, we only append to messages loop, then to self.conversation_history at the end.
        # Actually, self.conversation_history is updated at the very end with the final assistant content.
        # To verify the tool executed, we can check the calls to complete_chat

        assert mock_complete.call_count == 2
        second_call_kwargs = mock_complete.call_args_list[1].kwargs
        messages = second_call_kwargs["messages"]

        # The messages array sent on the second call should have:
        # system, user, assistant (with tool_calls), tool (with result)
        # However, since messages is a mutable list and the loop continues, the orchestrator
        # appends the final assistant message at the end. So the tool message is at -2.
        assert messages[-2]["role"] == "tool"
        assert messages[-2]["name"] == "run_command"
        assert "test command" in messages[-2]["content"]


def test_tool_max_iterations(mock_workspace):
    """Test that the orchestrator breaks out of infinite tool loops."""
    mock_tool_call = {
        "id": "call_inf",
        "function": {"name": "run_command", "arguments": json.dumps({"command": "echo 'loop'"})},
    }

    mock_response_tool = {
        "choices": [{"message": {"role": "assistant", "content": None, "tool_calls": [mock_tool_call]}}]
    }

    with patch("harness.shared.mango_mas_orchestrator.complete_chat") as mock_complete:
        mock_complete.return_value = mock_response_tool
        orchestrator = MangoMASOrchestrator(workspace_dir=mock_workspace)

        with pytest.raises(RuntimeError, match="exceeded maximum tool iterations"):
            orchestrator.execute_agent("nemotron-reasoner", "Loop forever")
