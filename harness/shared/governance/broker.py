"""Execution broker enforcing governance constraints.

This module provides the `ExecutionBroker` which enforces fail-closed execution logic.
It integrates with `pretooluse_guard` to block unauthorized network or filesystem access,
and explicitly prevents host-process fallback if the sandbox is unavailable (INV-9).
"""

from __future__ import annotations

import logging
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .pretooluse_guard import check_command

logger = logging.getLogger(__name__)

# Paths to the policy-enforcement point (PEP) and reference policy bundle.
# Resolved relative to this file so the broker works from any working directory.
_CONTROL_PLANE = Path(__file__).resolve().parent.parent.parent / "control-plane"
_PDP_PATH = _CONTROL_PLANE / "tool_broker_reference.py"
_POLICY_PATH = _CONTROL_PLANE / "policy-bundle.example.json"


@dataclass
class ExecutionResult:
    """The outcome of an execution attempt."""
    status: str  # "SUCCESS", "FAILED", "BLOCKED"
    stdout: str
    stderr: str
    exit_code: int


class ExecutionBroker:
    """The central execution broker for governed execution."""

    def __init__(self, sandbox_available: bool = True):
        self._sandbox_available = sandbox_available

    def verify_sandbox(self) -> bool:
        """Verify the sandbox backend is available and healthy."""
        return self._sandbox_available

    def execute_command(self, command: str, context: dict[str, Any] | None = None) -> ExecutionResult:
        """Execute a command securely within the sandbox.

        Enforces INV-8 (pre-tool guard integration) and INV-9 (no host fallback).
        """
        # INV-9: The execution broker MUST return BLOCKED if the sandbox is unavailable;
        # host-process fallback is strictly prohibited.
        if not self.verify_sandbox():
            logger.warning("Sandbox unavailable; blocking execution of: %s", command)
            return ExecutionResult(
                status="BLOCKED",
                stdout="",
                stderr="BLOCKED: Sandbox unavailable; host-process execution fallback is strictly prohibited.",
                exit_code=1
            )

        context = context or {}
        agent_id = context.get("agent_id", "unknown")
        action = context.get("action", "unknown")
        human_approved = context.get("human_approved", False)

        logger.debug("Broker evaluating command for agent=%s action=%s", agent_id, action)

        if _PDP_PATH.exists() and _POLICY_PATH.exists():
            cmd_args = [
                sys.executable,
                str(_PDP_PATH),
                "--policy", str(_POLICY_PATH),
                "--agent", agent_id,
                "--action", action
            ]
            if human_approved:
                cmd_args.append("--human-approved")

            p = subprocess.run(cmd_args, text=True, capture_output=True)
            if p.returncode != 0:
                logger.warning("PDP denied execution: agent=%s action=%s", agent_id, action)
                return ExecutionResult(
                    status="BLOCKED",
                    stdout="",
                    stderr=f"BLOCKED: {p.stderr.strip() or p.stdout.strip()}",
                    exit_code=p.returncode
                )

        # INV-8: All execution requests MUST pass through harness.shared.governance.pretooluse_guard
        guard_result = check_command(command)
        if guard_result != 0:
            logger.warning("PreToolUse guard blocked command: %s", command)
            return ExecutionResult(
                status="BLOCKED",
                stdout="",
                stderr="BLOCKED: Command failed pretooluse_guard policy evaluation.",
                exit_code=guard_result
            )

        logger.debug("Execution engine not yet implemented; returning FAILED for: %s", command)
        return ExecutionResult(
            status="FAILED",
            stdout="",
            stderr="FAILED: Execution engine not fully implemented.",
            exit_code=1
        )
