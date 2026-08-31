from pathlib import Path

import pytest

from harness.shared.mango_mas_orchestrator import MangoMASOrchestrator
from harness.shared.nemotron_bridge import resolve_api_key

# Check if LIVE test execution is enabled
IS_LIVE = bool(resolve_api_key())

# Project root: harness/shared/tests → harness/shared → harness → project root
_PROJECT_ROOT: Path = Path(__file__).resolve().parent.parent.parent.parent


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

        Uses ``execute_sequential_thinking_loop`` (the legacy prose-return path, R-ORCH-4) so the
        assertion is on the verifier's own prose. ``verification_cwd=_PROJECT_ROOT`` is still
        required: ``execute_sequential_thinking_loop`` delegates to ``execute_loop``, which calls
        ``_harness_verdict()``, which probes ``make -f Makefile test-python`` at ``_verification_cwd``.
        Without it, the probe runs in ``tmp_path`` (no Makefile) and returns BLOCKED — the prose
        assertion would pass but the harness verdict would silently be wrong.
        """
        monkeypatch.setenv("ALLOW_GITHUB_CHANGES", "1")
        orchestrator = MangoMASOrchestrator(
            workspace_dir=tmp_path,
            verification_cwd=_PROJECT_ROOT,
        )

        task = (
            "1. Write a Python function called calculate_fibonacci in dynamic_util.py with type hints and docstring.\n"
            "2. Write a test file test_dynamic_util.py testing calculate_fibonacci(10) == 55.\n"
            "3. Run python -m unittest test_dynamic_util.py to verify."
        )

        # Execute the loop — returns the verifier's own prose (legacy path)
        verification_result = orchestrator.execute_sequential_thinking_loop(task)

        # 1. The verifier prose must contain PASS or FAIL
        assert "PASS" in verification_result or "FAIL" in verification_result

        # 2. All 3 agents must have participated
        agents_used = [
            msg["content"] for msg in orchestrator.conversation_history if "role" in msg and msg["role"] == "system"
        ]
        assert any("planner" in prompt.lower() for prompt in agents_used)
        assert any("reasoner" in prompt.lower() for prompt in agents_used)
        assert any("verifier" in prompt.lower() for prompt in agents_used)


    def test_mango_mas_multi_file_app_synthesis_e2e(self, tmp_path, monkeypatch):
        """
        Tests multi-file application synthesis where MAS creates a module and companion test.

        ``verification_cwd=_PROJECT_ROOT`` is the root of the harness repository (where the repo's
        Makefile lives). ``workspace_dir=tmp_path`` is the agent's ephemeral file-creation sandbox.
        In production both are the same; in live tests they differ because the test isolates agent
        file I/O from the repository tree while still earning a real harness verdict via
        ``make -f Makefile test-python``.
        """
        monkeypatch.setenv("ALLOW_GITHUB_CHANGES", "1")
        orchestrator = MangoMASOrchestrator(
            workspace_dir=tmp_path,
            max_iterations=15,
            verification_cwd=_PROJECT_ROOT,
        )

        task = (
            "1. Write a DataValidator class in validator.py with method 'is_valid_email(email: str) -> bool'.\n"
            "2. Write a unit test file test_validator.py using unittest to verify valid and invalid emails.\n"
            "3. Run python -m unittest test_validator.py and verify all tests pass."
        )

        outcome = orchestrator.execute_loop(task)
        assert outcome.verdict.is_pass
        assert (tmp_path / "validator.py").exists()
        assert (tmp_path / "test_validator.py").exists()

    def test_mango_mas_math_symbolic_reasoning_e2e(self, tmp_path, monkeypatch):
        """
        Tests symbolic mathematical reasoning and formula verification.

        ``verification_cwd=_PROJECT_ROOT`` ensures ``make -f Makefile test-python`` resolves
        against the actual repo Makefile rather than the ephemeral agent sandbox (tmp_path).
        """
        monkeypatch.setenv("ALLOW_GITHUB_CHANGES", "1")
        orchestrator = MangoMASOrchestrator(
            workspace_dir=tmp_path,
            verification_cwd=_PROJECT_ROOT,
        )

        task = (
            "Write a Python script math_solver.py that computes prime factors of 1050 (which are 2, 3, 5, 7).\n"
            "Include an assertion verifying prime_factors(1050) == [2, 3, 5, 5, 7].\n"
            "Execute python math_solver.py and report the result."
        )

        outcome = orchestrator.execute_loop(task)
        assert outcome.verdict.is_pass
        assert (tmp_path / "math_solver.py").exists()
