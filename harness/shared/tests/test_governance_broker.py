"""Tests for harness/shared/governance/broker.py — ExecutionBroker."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from harness.shared.governance.broker import (
    ExecutionBroker,
    ExecutionResult,
)

# ---------------------------------------------------------------------------
# verify_sandbox
# ---------------------------------------------------------------------------


def test_verify_sandbox_true_by_default() -> None:
    broker = ExecutionBroker()
    assert broker.verify_sandbox() is True


def test_verify_sandbox_false_when_unavailable() -> None:
    broker = ExecutionBroker(sandbox_available=False)
    assert broker.verify_sandbox() is False


# ---------------------------------------------------------------------------
# INV-9: sandbox unavailable → BLOCKED (no host fallback)
# ---------------------------------------------------------------------------


def test_sandbox_unavailable_returns_blocked() -> None:
    broker = ExecutionBroker(sandbox_available=False)
    result = broker.execute_command("git push origin main")
    assert result.status == "BLOCKED"
    assert result.exit_code == 1
    assert "host-process" in result.stderr.lower() or "sandbox" in result.stderr.lower()


def test_sandbox_unavailable_does_not_fall_back_to_host(monkeypatch: pytest.MonkeyPatch) -> None:
    """INV-9: BLOCKED must be returned immediately; subprocess must NOT be called."""
    import harness.shared.governance.broker as broker_mod
    spy = MagicMock(return_value=MagicMock(returncode=0, stdout="", stderr=""))
    monkeypatch.setattr(broker_mod, "subprocess", MagicMock(run=spy))
    broker = ExecutionBroker(sandbox_available=False)
    broker.execute_command("ls")
    spy.assert_not_called()


# ---------------------------------------------------------------------------
# PDP / policy enforcement
# ---------------------------------------------------------------------------


def test_pdp_block_returns_blocked_status() -> None:
    """When the PDP subprocess exits non-zero the broker must return BLOCKED."""
    broker = ExecutionBroker(sandbox_available=True)
    with patch("harness.shared.governance.broker._PDP_PATH") as mock_pdp, \
         patch("harness.shared.governance.broker._POLICY_PATH") as mock_policy, \
         patch("harness.shared.governance.broker.subprocess.run") as mock_run:
        mock_pdp.exists.return_value = True
        mock_policy.exists.return_value = True
        mock_run.return_value = MagicMock(returncode=1, stdout="", stderr="Action denied")
        result = broker.execute_command(
            "git push",
            context={"agent_id": "release-auditor", "action": "external_write"},
        )
    assert result.status == "BLOCKED"
    assert "denied" in result.stderr.lower() or result.exit_code != 0


def test_pdp_allow_passes_through_to_guard() -> None:
    """When PDP allows, execution must reach the pretooluse_guard check."""
    broker = ExecutionBroker(sandbox_available=True)
    with patch("harness.shared.governance.broker._PDP_PATH") as mock_pdp, \
         patch("harness.shared.governance.broker._POLICY_PATH") as mock_policy, \
         patch("harness.shared.governance.broker.subprocess.run") as mock_run, \
         patch("harness.shared.governance.broker.check_command", return_value=0) as mock_guard:
        mock_pdp.exists.return_value = True
        mock_policy.exists.return_value = True
        mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
        broker.execute_command("git status", context={"agent_id": "orchestrator", "action": "read"})
    mock_guard.assert_called_once_with("git status")


def test_pdp_skipped_when_files_absent() -> None:
    """When PDP binary/policy are absent the check is bypassed (gate is advisory)."""
    broker = ExecutionBroker(sandbox_available=True)
    with patch("harness.shared.governance.broker._PDP_PATH") as mock_pdp, \
         patch("harness.shared.governance.broker._POLICY_PATH") as mock_policy, \
         patch("harness.shared.governance.broker.subprocess.run") as mock_run, \
         patch("harness.shared.governance.broker.check_command", return_value=0):
        mock_pdp.exists.return_value = False
        mock_policy.exists.return_value = False
        broker.execute_command("git status")
    mock_run.assert_not_called()


def test_human_approved_flag_passed_to_pdp() -> None:
    broker = ExecutionBroker(sandbox_available=True)
    with patch("harness.shared.governance.broker._PDP_PATH") as mock_pdp, \
         patch("harness.shared.governance.broker._POLICY_PATH") as mock_policy, \
         patch("harness.shared.governance.broker.subprocess.run") as mock_run, \
         patch("harness.shared.governance.broker.check_command", return_value=0):
        mock_pdp.exists.return_value = True
        mock_policy.exists.return_value = True
        mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
        broker.execute_command(
            "deploy",
            context={"agent_id": "release-auditor", "action": "external_write", "human_approved": True},
        )
    call_args = mock_run.call_args[0][0]
    assert "--human-approved" in call_args


# ---------------------------------------------------------------------------
# INV-8: pretooluse_guard blocks
# ---------------------------------------------------------------------------


def test_guard_block_returns_blocked() -> None:
    broker = ExecutionBroker(sandbox_available=True)
    with patch("harness.shared.governance.broker._PDP_PATH") as mock_pdp, \
         patch("harness.shared.governance.broker.check_command", return_value=2):
        mock_pdp.exists.return_value = False
        result = broker.execute_command("curl https://evil.example")
    assert result.status == "BLOCKED"
    assert result.exit_code == 2


# ---------------------------------------------------------------------------
# ExecutionResult dataclass
# ---------------------------------------------------------------------------


def test_execution_result_fields() -> None:
    r = ExecutionResult(status="SUCCESS", stdout="ok", stderr="", exit_code=0)
    assert r.status == "SUCCESS"
    assert r.stdout == "ok"
    assert r.exit_code == 0


# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------


def test_sandbox_unavailable_logs_warning(caplog: pytest.LogCaptureFixture) -> None:
    import logging
    broker = ExecutionBroker(sandbox_available=False)
    with caplog.at_level(logging.WARNING, logger="harness.shared.governance.broker"):
        broker.execute_command("ls")
    assert "sandbox" in caplog.text.lower() or "blocking" in caplog.text.lower()


def test_real_pdp_integration_denies_and_allows() -> None:
    """Ensure the real PDP subprocess correctly reads agent-policy.json without KeyErrors."""
    broker = ExecutionBroker(sandbox_available=True)
    # Orchestrator is allowed 'read'
    allowed_result = broker.execute_command(
        "git status",
        context={"agent_id": "orchestrator", "action": "read"},
    )
    assert allowed_result.status != "BLOCKED" or "pdp" not in allowed_result.stderr.lower()

    # Unknown agent must be BLOCKED by real PDP
    denied_result = broker.execute_command(
        "git status",
        context={"agent_id": "malicious-hacker", "action": "read"},
    )
    assert denied_result.status == "BLOCKED"
    assert "unknown agent identity" in denied_result.stderr.lower()
