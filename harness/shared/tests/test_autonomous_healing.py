"""Tests for autonomous healing module."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from harness.shared.experimental.autonomous_healing import TestHealer
from harness.shared.governance.broker import ExecutionResult

# No socket exemption: nothing here opens one. The module-wide `enable_socket`
# that stood here had no justification and no need -- every test passes with
# the egress floor armed (code-quality-tech-debt-plan R-CQ-21, audit M12).


def test_run_test_suite_success(tmp_path) -> None:
    """Test _run_test_suite routes through a default broker and captures success."""
    from harness.shared.governance.broker import ExecutionBroker
    mock_broker = MagicMock(spec=ExecutionBroker)
    mock_broker.execute_command.return_value = ExecutionResult(
        status="SUCCESS", stdout="pass", stderr="", exit_code=0
    )
    healer = TestHealer(workspace=str(tmp_path), broker=mock_broker)
    success, output = healer._run_test_suite(["pytest"])
    assert success is True
    mock_broker.execute_command.assert_called_once()


def test_run_test_suite_exception(tmp_path) -> None:
    """Test _run_test_suite handles broker execution exceptions."""
    from harness.shared.governance.broker import ExecutionBroker
    mock_broker = MagicMock(spec=ExecutionBroker)
    mock_broker.execute_command.side_effect = OSError("cmd not found")
    healer = TestHealer(workspace=str(tmp_path), broker=mock_broker)
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
    # Initial run fails, second run passes after healing
    calls = iter([(False, "some failure"), (True, "recovered")])

    def fake_run(cmd: list[str]) -> tuple[bool, str]:
        return next(calls)

    with patch.object(healer, "_run_test_suite", side_effect=fake_run), \
         patch("harness.shared.experimental.autonomous_healing.LANGGRAPH_AVAILABLE", False), \
         patch("harness.shared.experimental.autonomous_healing.MangoMASOrchestrator") as mock_orch:
        mock_instance = MagicMock()
        mock_orch.return_value = mock_instance
        assert healer.heal_until_green(["pytest"]) is True
        assert mock_instance.execute_loop.called


def test_heal_until_green_langgraph_branch(tmp_path) -> None:
    """Test heal_until_green uses LangGraph when available and passes orchestrator config."""
    healer = TestHealer(workspace=str(tmp_path), max_retries=2)
    with patch.object(healer, "_run_test_suite", side_effect=[(False, "fail"), (True, "pass")]), \
         patch("harness.shared.experimental.autonomous_healing.LANGGRAPH_AVAILABLE", True), \
         patch("harness.shared.langgraph.graph.build_graph") as mock_build, \
         patch("harness.shared.experimental.autonomous_healing.MangoMASOrchestrator"):
        mock_graph = MagicMock()
        mock_build.return_value = mock_graph
        assert healer.heal_until_green(["pytest"]) is True
        assert mock_graph.invoke.called
        # verify orchestrator was passed in config
        call_kwargs = mock_graph.invoke.call_args
        config = call_kwargs[1].get("config") or (call_kwargs[0][1] if len(call_kwargs[0]) > 1 else {})
        assert config.get("configurable", {}).get("orchestrator") is not None


def test_heal_until_green_exhausted(tmp_path) -> None:
    """Test heal_until_green returns False when retries are exhausted."""
    healer = TestHealer(workspace=str(tmp_path), max_retries=2)
    with patch.object(healer, "_run_test_suite", return_value=(False, "fail")), \
         patch("harness.shared.experimental.autonomous_healing.LANGGRAPH_AVAILABLE", False), \
         patch("harness.shared.experimental.autonomous_healing.MangoMASOrchestrator"):
        assert healer.heal_until_green(["pytest"]) is False


def test_heal_until_green_orchestrator_exception(tmp_path) -> None:
    """Test heal_until_green catches orchestrator runtime errors."""
    healer = TestHealer(workspace=str(tmp_path), max_retries=2)
    orch_patch = patch(
        "harness.shared.experimental.autonomous_healing.MangoMASOrchestrator",
        side_effect=RuntimeError("orchestrator crash")
    )
    with patch.object(healer, "_run_test_suite", return_value=(False, "fail")), \
         patch("harness.shared.experimental.autonomous_healing.LANGGRAPH_AVAILABLE", False), \
         orch_patch:
        assert healer.heal_until_green(["pytest"]) is False


def test_healer_max_retries_clamped_to_policy(tmp_path) -> None:
    """max_retries above the policy limit must be rejected."""
    from harness.shared.policy_loader import orchestrator_defaults
    policy_limit = orchestrator_defaults().get("max_healing_retries", 3)
    with pytest.raises(ValueError, match="exceeds governance policy limit"):
        TestHealer(workspace=str(tmp_path), max_retries=policy_limit + 100)


def test_healer_max_retries_invalid_type(tmp_path) -> None:
    """max_retries must be a non-negative integer."""
    with pytest.raises(ValueError, match="non-negative integer"):
        TestHealer(workspace=str(tmp_path), max_retries=-1)
    with pytest.raises(ValueError, match="non-negative integer"):
        TestHealer(workspace=str(tmp_path), max_retries=True)


def test_healer_max_retries_zero_exhausted_immediately(tmp_path) -> None:
    """Test heal_until_green returns False on first failure if max_retries=0 (no healing loops)."""
    healer = TestHealer(workspace=str(tmp_path), max_retries=0)
    with patch.object(healer, "_run_test_suite", return_value=(False, "fail")), \
         patch("harness.shared.experimental.autonomous_healing.MangoMASOrchestrator") as mock_orch:
        assert healer.heal_until_green(["pytest"]) is False
        assert not mock_orch.called


def test_healer_broker_routes_test_execution(tmp_path) -> None:
    """When a broker is injected, _run_test_suite routes through it (INV-8)."""
    from harness.shared.governance.broker import ExecutionBroker
    mock_broker = MagicMock(spec=ExecutionBroker)
    mock_broker.execute_command.return_value = ExecutionResult(
        status="SUCCESS", stdout="test output", stderr="", exit_code=0, reason="", action=""
    )
    healer = TestHealer(workspace=str(tmp_path), max_retries=1, broker=mock_broker)
    success, output = healer._run_test_suite(["pytest"])
    assert success is True
    assert output == "test output"
    assert mock_broker.execute_command.call_args.kwargs["cwd"] == tmp_path


def test_healer_broker_preserves_failed_execution_status(tmp_path) -> None:
    """A failed broker result starts the healing loop instead of reporting success."""
    from harness.shared.governance.broker import ExecutionBroker
    mock_broker = MagicMock(spec=ExecutionBroker)
    mock_broker.execute_command.return_value = ExecutionResult(
        status="FAILED", stdout="", stderr="failure", exit_code=1, reason="", action=""
    )
    healer = TestHealer(workspace=str(tmp_path), max_retries=0, broker=mock_broker)
    success, _ = healer._run_test_suite(["pytest"])
    assert success is False
