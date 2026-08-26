"""Execution broker enforcing governance constraints.

This module provides the `ExecutionBroker` which enforces fail-closed execution logic.
It integrates with `pretooluse_guard` to block unauthorized network or filesystem access,
and explicitly prevents host-process fallback if the sandbox is unavailable (INV-9).
"""

from __future__ import annotations

import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .pretooluse_guard import check_command


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

        pdp_path = Path(__file__).resolve().parent.parent.parent / "control-plane" / "tool_broker_reference.py"
        policy_path = Path(__file__).resolve().parent.parent.parent / "control-plane" / "policy-bundle.example.json"

        if pdp_path.exists() and policy_path.exists():
            cmd_args = [
                sys.executable,
                str(pdp_path),
                "--policy", str(policy_path),
                "--agent", agent_id,
                "--action", action
            ]
            if human_approved:
                cmd_args.append("--human-approved")

            p = subprocess.run(cmd_args, text=True, capture_output=True)
            if p.returncode != 0:
                return ExecutionResult(
                    status="BLOCKED",
                    stdout="",
                    stderr=f"BLOCKED: {p.stderr.strip() or p.stdout.strip()}",
                    exit_code=p.returncode
                )

        # INV-8: All execution requests MUST pass through harness.shared.governance.pretooluse_guard
        guard_result = check_command(command)
        if guard_result != 0:
            return ExecutionResult(
                status="BLOCKED",
                stdout="",
                stderr="BLOCKED: Command failed pretooluse_guard policy evaluation.",
                exit_code=guard_result
            )

        return ExecutionResult(
            status="FAILED",
            stdout="",
            stderr="FAILED: Execution engine not fully implemented.",
            exit_code=1
        )
