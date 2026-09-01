"""Tests for autonomous healing module."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from harness.shared.autonomous_healing import TestHealer

pytestmark = pytest.mark.enable_socket


def test_run_test_suite_success(tmp_path) -> None:
    """Test _run_test_suite captures success."""
    healer = TestHealer(workspace=str(tmp_path))
    with patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0, stdout="pass", stderr="")
        success, output = healer._run_test_suite(["pytest"])
        assert success is True
        assert "pass" in output


def test_run_test_suite_exception(tmp_path) -> None:
    """Test _run_test_suite handles execution exceptions."""
    healer = TestHealer(workspace=str(tmp_path))
    with patch("subprocess.run", side_effect=OSError("cmd not found")):
        success, output = healer._run_test_suite(["pytest"])
        assert success is False
        assert "Failed to run test suite" in output


def test_heal_until_green_success_first_try(tmp_path) -> None:
    """Test heal_until_green succeeds without healing if tests pass immediately."""
    healer = TestHealer(workspace=str(tmp_path), max_retries=2)
    with patch.object(healer, "_run_test_suite", return_value=(True, "ok")):
        assert healer.heal_until_green(["pytest"]) is True


def test_heal_until_green_recovers_after_remediation(tmp_path) -> None:
    """Test heal_until_green invokes orchestrator and recovers."""
    healer = TestHealer(workspace=str(tmp_path), max_retries=3)
    attempts = [False, True]

    def fake_run(cmd: list[str]) -> tuple[bool, str]:
        return attempts.pop(0), "some failure" if not attempts else "recovered"

    with patch.object(healer, "_run_test_suite", side_effect=fake_run), \
         patch("harness.shared.autonomous_healing.LANGGRAPH_AVAILABLE", False), \
         patch("harness.shared.autonomous_healing.MangoMASOrchestrator") as mock_orch:
        mock_instance = MagicMock()
        mock_orch.return_value = mock_instance
        assert healer.heal_until_green(["pytest"]) is True
        assert mock_instance.execute_loop.called


def test_heal_until_green_langgraph_branch(tmp_path) -> None:
    """Test heal_until_green uses LangGraph when available."""
    healer = TestHealer(workspace=str(tmp_path), max_retries=2)
    with patch.object(healer, "_run_test_suite", side_effect=[(False, "fail"), (True, "pass")]), \
         patch("harness.shared.autonomous_healing.LANGGRAPH_AVAILABLE", True), \
         patch("harness.shared.langgraph.graph.build_graph") as mock_build:
        mock_graph = MagicMock()
        mock_build.return_value = mock_graph
        assert healer.heal_until_green(["pytest"]) is True
        assert mock_graph.invoke.called


def test_heal_until_green_exhausted(tmp_path) -> None:
    """Test heal_until_green returns False when retries are exhausted."""
    healer = TestHealer(workspace=str(tmp_path), max_retries=2)
    with patch.object(healer, "_run_test_suite", return_value=(False, "fail")), \
         patch("harness.shared.autonomous_healing.LANGGRAPH_AVAILABLE", False), \
         patch("harness.shared.autonomous_healing.MangoMASOrchestrator"):
        assert healer.heal_until_green(["pytest"]) is False


def test_heal_until_green_orchestrator_exception(tmp_path) -> None:
    """Test heal_until_green catches orchestrator runtime errors."""
    healer = TestHealer(workspace=str(tmp_path), max_retries=2)
    orch_patch = patch(
        "harness.shared.autonomous_healing.MangoMASOrchestrator",
        side_effect=RuntimeError("orchestrator crash")
    )
    with patch.object(healer, "_run_test_suite", return_value=(False, "fail")), \
         patch("harness.shared.autonomous_healing.LANGGRAPH_AVAILABLE", False), \
         orch_patch:
        assert healer.heal_until_green(["pytest"]) is False
