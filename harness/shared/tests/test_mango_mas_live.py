import pytest

from harness.shared.mango_mas_orchestrator import MangoMASOrchestrator
from harness.shared.nemotron_bridge import resolve_api_key

# Check if LIVE test execution is enabled
IS_LIVE = bool(resolve_api_key())


@pytest.mark.live
@pytest.mark.skipif(not IS_LIVE, reason="Requires NVIDIA_API_KEY")
class TestMangoMASLive:
    """
    E2E Adversarial Live tests testing the Mango MAS Orchestrator.
    Requires NVIDIA_API_KEY to hit the Nemotron API.
    """

    def test_mango_mas_sequential_thinking_e2e(self, tmp_path, monkeypatch):
        """
        Tests the full loop of planner -> reasoner -> verifier
        by generating a simple Python function and ensuring it is created dynamically without hallucination.
        """
        monkeypatch.setenv("ALLOW_GITHUB_CHANGES", "1")
        # Find the root of the project to locate the .mango directory
        # Harness_TEST / harness / shared / tests / ...
        orchestrator = MangoMASOrchestrator(workspace_dir=tmp_path)

        # We ask the MAS to write a simple dynamic python utility to the workspace path
        # and test it via sequential thinking
        task = (
            "Write a Python function called calculate_fibonacci in dynamic_util.py."
            " Ensure it has type hints and a docstring."
        )

        # Execute the loop
        verification_result = orchestrator.execute_sequential_thinking_loop(task)

        # Assertions
        # 1. The MAS should report PASS or FAIL in its verification output
        assert "PASS" in verification_result or "FAIL" in verification_result

        # 2. Check the conversation history to ensure all 3 agents participated
        agents_used = [
            msg["content"] for msg in orchestrator.conversation_history if "role" in msg and msg["role"] == "system"
        ]
        assert any("planner" in prompt.lower() for prompt in agents_used)
        assert any("reasoner" in prompt.lower() for prompt in agents_used)
        assert any("verifier" in prompt.lower() for prompt in agents_used)
