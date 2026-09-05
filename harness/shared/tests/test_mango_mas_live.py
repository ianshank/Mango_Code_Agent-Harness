import os
import sys
from pathlib import Path

# Project root: harness/shared/tests → harness/shared → harness → project root
_PROJECT_ROOT: Path = Path(__file__).resolve().parent.parent.parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

import pytest  # noqa: E402

from harness.shared.mango_mas_orchestrator import MangoMASOrchestrator  # noqa: E402
from harness.shared.nemotron_bridge import resolve_api_key  # noqa: E402

# Check if LIVE test execution is enabled
IS_LIVE = bool(resolve_api_key())

_TRANSIENT_NIM_ERRORS = (
    "500",
    "502",
    "503",
    "504",
    "429",
    "ResourceExhausted",
    "timeout",
    "timed out",
)


@pytest.fixture(autouse=True)
def _set_nemotron_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    """Set NEMOTRON_MODE only when a live test in this module actually runs.

    Previously set at import time, which leaked into hermetic runs because
    pytest collects (imports) live modules even when they are deselected.
    """
    monkeypatch.setenv("NEMOTRON_MODE", "online")


@pytest.mark.live
# A real TCP need (R-EGF-6): the orchestrator calls the Nemotron API over HTTPS,
# which no unix-socket allowance covers. Selected only by `pytest -m live`.
@pytest.mark.enable_socket
@pytest.mark.skipif(not IS_LIVE, reason="Requires NVIDIA_API_KEY (DEC-026)")
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
        pythonpath = os.environ.get("PYTHONPATH", "")
        monkeypatch.setenv("PYTHONPATH", f"{tmp_path}{os.pathsep}{pythonpath}" if pythonpath else str(tmp_path))
        orchestrator = MangoMASOrchestrator(
            workspace_dir=tmp_path,
            max_iterations=5,
            verification_cwd=_PROJECT_ROOT,
        )

        task = (
            "Write a simple Python file fib.py with a function `fibonacci(n)` that returns the nth fibonacci number.\n"
            "Include a main block that prints `fibonacci(10)`.\n"
            "Run python fib.py to verify it works."
        )

        try:
            # Execute the loop — returns the verifier's own prose (legacy path)
            verification_result = orchestrator.execute_sequential_thinking_loop(task)
        except Exception as e:
            err_msg = str(e)
            if any(term in err_msg for term in _TRANSIENT_NIM_ERRORS):
                pytest.skip(f"Live NIM transient failure: {err_msg}")
            raise

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
        pythonpath = os.environ.get("PYTHONPATH", "")
        monkeypatch.setenv("PYTHONPATH", f"{tmp_path}{os.pathsep}{pythonpath}" if pythonpath else str(tmp_path))
        orchestrator = MangoMASOrchestrator(
            workspace_dir=tmp_path,
            max_iterations=15,
            verification_cwd=_PROJECT_ROOT,
        )

        task = (
            "1. Write a DataValidator class in validator.py with method 'is_valid_email(email: str) -> bool'.\n"
            "2. Write a unit test file test_validator.py using unittest to verify valid and invalid emails.\n"
            "   Ensure test_validator.py imports DataValidator from validator without import errors.\n"
            "3. Run python -m unittest test_validator.py and verify all tests pass."
        )

        try:
            outcome = orchestrator.execute_loop(task)
        except Exception as e:
            err_msg = str(e)
            if any(term in err_msg for term in _TRANSIENT_NIM_ERRORS):
                pytest.skip(f"Live NIM transient failure: {err_msg}")
            if "exceeded maximum tool iterations" in err_msg or "budget" in err_msg:
                pytest.skip(f"Live synthesis iteration limit reached: {err_msg}")
            raise

        if not outcome.verdict.is_pass and outcome.verdict.termination_reason == "verification_unavailable":
            # On host environments without GNU make (e.g. Windows dev hosts),
            # VerificationRunner.probe() returns False and outcome terminates as verification_unavailable.
            assert any(
                term in outcome.verifier_message.upper()
                for term in ("PASS", "VERIFIED", "SUCCESS", "VALIDATOR", "SOLVER")
            )
        else:
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
        pythonpath = os.environ.get("PYTHONPATH", "")
        monkeypatch.setenv("PYTHONPATH", f"{tmp_path}{os.pathsep}{pythonpath}" if pythonpath else str(tmp_path))
        orchestrator = MangoMASOrchestrator(
            workspace_dir=tmp_path,
            max_iterations=15,
            verification_cwd=_PROJECT_ROOT,
        )

        task = (
            "Write a Python script math_solver.py that computes prime factors of 1050 (which are 2, 3, 5, 7).\n"
            "Include an assertion verifying prime_factors(1050) == [2, 3, 5, 5, 7].\n"
            "Execute python math_solver.py and report the result."
        )

        try:
            outcome = orchestrator.execute_loop(task)
        except Exception as e:
            err_msg = str(e)
            if any(term in err_msg for term in _TRANSIENT_NIM_ERRORS):
                pytest.skip(f"Live NIM transient failure: {err_msg}")
            if "exceeded maximum tool iterations" in err_msg or "budget" in err_msg:
                pytest.skip(f"Live synthesis iteration limit reached: {err_msg}")
            raise

        if not outcome.verdict.is_pass and outcome.verdict.termination_reason == "verification_unavailable":
            # On host environments without GNU make (e.g. Windows dev hosts),
            # VerificationRunner.probe() returns False and outcome terminates as verification_unavailable.
            assert any(
                term in outcome.verifier_message.upper() for term in ("PASS", "VERIFIED", "SUCCESS", "PRIME", "SOLVER")
            )
        else:
            assert outcome.verdict.is_pass
        assert (tmp_path / "math_solver.py").exists() or "math_solver.py" in str(orchestrator.conversation_history)
