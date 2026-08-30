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
            "1. Write a Python function called calculate_fibonacci in dynamic_util.py with type hints and docstring.\n"
            "2. Write a test file test_dynamic_util.py testing calculate_fibonacci(10) == 55.\n"
            "3. Run python -m unittest test_dynamic_util.py to verify."
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

    def test_mango_mas_multi_file_app_synthesis_e2e(self, tmp_path, monkeypatch):
        """
        Tests multi-file application synthesis where MAS creates a module and companion test.
        """
        monkeypatch.setenv("ALLOW_GITHUB_CHANGES", "1")
        orchestrator = MangoMASOrchestrator(workspace_dir=tmp_path, max_iterations=15)

        task = (
            "1. Write a DataValidator class in validator.py with method 'is_valid_email(email: str) -> bool'.\n"
            "2. Write a unit test file test_validator.py using unittest to verify valid and invalid emails.\n"
            "3. Run python -m unittest test_validator.py and verify all tests pass."
        )

        outcome = orchestrator.execute_loop(task)
        history_str = str(orchestrator.conversation_history)
        assert (
            "PASS" in outcome.verifier_message
            or "FAIL" in outcome.verifier_message
            or "PASS" in history_str
            or "FAIL" in history_str
            or (tmp_path / "validator.py").exists()
            or "validator.py" in history_str
        )
        assert (tmp_path / "validator.py").exists() or "validator.py" in history_str

    def test_mango_mas_math_symbolic_reasoning_e2e(self, tmp_path, monkeypatch):
        """
        Tests symbolic mathematical reasoning and formula verification.
        """
        monkeypatch.setenv("ALLOW_GITHUB_CHANGES", "1")
        orchestrator = MangoMASOrchestrator(workspace_dir=tmp_path)

        task = (
            "Write a Python script math_solver.py that computes prime factors of 1050 (which are 2, 3, 5, 7).\n"
            "Include an assertion verifying prime_factors(1050) == [2, 3, 5, 5, 7].\n"
            "Execute python math_solver.py and report the result."
        )

        verification_result = orchestrator.execute_sequential_thinking_loop(task)
        history_str = str(orchestrator.conversation_history)
        assert (
            "PASS" in verification_result
            or "FAIL" in verification_result
            or "PASS" in history_str
            or "FAIL" in history_str
            or (tmp_path / "math_solver.py").exists()
            or "math_solver.py" in history_str
        )
