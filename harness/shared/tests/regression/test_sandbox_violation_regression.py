"""Regression tests for SandboxViolation critique normalization.

Requirement Citations:
- R-CE-3: Sandbox execution boundary and violation trapping
- AC-CE-1: Capability profile restriction enforcement
- AC-NS-3: Critique normalization from sandbox violations
"""

from __future__ import annotations

import json
from dataclasses import dataclass

from harness.shared.tool_result_format import format_execution_result


@dataclass
class DummyExecutionResult:
    status: str
    stdout: str
    stderr: str
    exit_code: int
    reason: str = ""


class TestSandboxViolationCritiqueNormalizationRegression:
    """Verifies that SandboxViolation payloads in stderr are normalized to structured critiques."""

    def test_sandbox_violation_json_in_stderr_becomes_structured_critique(self) -> None:
        violation_payload = {
            "schema_version": "1.0",
            "violation_type": "network_access_denied",
            "evidence_id": "evd-9988",
            "capability_profile": "network-isolated",
            "message": "Outbound connection refused by network-isolated profile.",
        }
        res = DummyExecutionResult(
            status="BLOCKED",
            stdout="",
            stderr=json.dumps(violation_payload),
            exit_code=1,
            reason="BLOCKED: Sandbox violation",
        )
        rendered = format_execution_result(res)

        assert rendered.startswith("Error: Critique received.\n")
        critique_json = rendered.split("Error: Critique received.\n", 1)[1]
        critique = json.loads(critique_json)

        assert critique["schema_version"] == "1.0"
        assert critique["failure_type"] == "network_access_denied"
        assert critique["evidence_id"] == "evd-9988"
        assert critique["location"] == "execution_broker"
        assert "network-isolated" in critique["normalized_message"]

    def test_standard_policy_denial_without_json_preserves_legacy_format(self) -> None:
        res = DummyExecutionResult(
            status="BLOCKED",
            stdout="",
            stderr="git push is not permitted",
            exit_code=1,
            reason="action 'external_write' is not granted",
        )
        rendered = format_execution_result(res)

        assert rendered.startswith("Error: Command blocked by policy guard.")
        assert "action 'external_write' is not granted" in rendered

    def test_normal_successful_command_output(self) -> None:
        res = DummyExecutionResult(
            status="SUCCESS",
            stdout="pytest passed: 10 passed",
            stderr="",
            exit_code=0,
        )
        rendered = format_execution_result(res)
        assert rendered == "pytest passed: 10 passed"
