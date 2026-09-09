"""In-memory sandbox policy compiler (R-AEI-14 / AC-14)."""

from __future__ import annotations

import hashlib
import json
from dataclasses import replace
from pathlib import Path

import pytest

from harness.shared.agent_authority import DEFAULT_AGENT_POLICY_PATH
from harness.shared.governance.landlock_backend import LandlockBackend
from harness.shared.governance.process_backend import DEFAULT_MAX_OUTPUT_BYTES, DEFAULT_TIMEOUT_SEC
from harness.shared.governance.sandbox_policy import (
    SandboxPolicyError,
    compile_sandbox_policy,
)
from harness.shared.governance.verdict import BROKER_BLOCKED
from harness.shared.policy_loader import POLICY_PATH
from harness.shared.tests._helpers import REPO
from harness.shared.tests._isolation_request import TEST_EXECUTE_ACTION, isolation_request

pytestmark = pytest.mark.governance


def test_sandbox_policy_compiled_in_memory() -> None:
    """AC-14: rebuild equals compile; both source digests; no derived artifact."""
    compiled = compile_sandbox_policy()
    rebuilt = compile_sandbox_policy()
    assert compiled == rebuilt
    agent_raw = DEFAULT_AGENT_POLICY_PATH.read_bytes()
    gov_raw = POLICY_PATH.read_bytes()
    assert compiled.agent_digest == hashlib.sha256(agent_raw).hexdigest()
    assert compiled.governance_digest == hashlib.sha256(gov_raw).hexdigest()
    assert compiled.default_deny is True
    assert compiled.network_outbound == "deny"
    assert compiled.filesystem == "workspace"
    assert compiled.routing in {"brokered", "refuse"}
    derived = [
        path
        for path in (REPO / "harness").rglob("*")
        if path.is_file() and "sandbox" in path.name.lower() and path.suffix == ".json"
    ]
    assert derived == [], f"committed derived sandbox artifact: {derived}"


def test_isolation_request_uses_policy_sourced_bounds() -> None:
    """C-AEI-2: isolation tests must not restate orchestrator literals."""
    request = isolation_request(None, "true")
    assert request.timeout == DEFAULT_TIMEOUT_SEC
    assert request.max_output_bytes == DEFAULT_MAX_OUTPUT_BYTES
    assert request.action == TEST_EXECUTE_ACTION == "test_execute"


def test_sandbox_policy_mismatch_blocks(tmp_path: Path) -> None:
    """A compiled view that does not match a live rebuild is BLOCKED at start."""
    live = compile_sandbox_policy()
    stale = replace(live, compiled_digest="0" * 64)
    backend = LandlockBackend(policy=stale)
    workspace = tmp_path / "ws"
    workspace.mkdir()
    result = backend.execute(isolation_request(workspace, "true"))
    assert result.status == BROKER_BLOCKED
    assert "mismatch" in (result.reason or "")


def test_sandbox_policy_parse_failure_is_compile_error(tmp_path: Path) -> None:
    gov = tmp_path / "governance-policy.json"
    agent = tmp_path / "agent-policy.json"
    gov.write_text("{", encoding="utf-8")
    agent.write_text("{}", encoding="utf-8")
    with pytest.raises(SandboxPolicyError, match="not JSON"):
        compile_sandbox_policy(governance_path=gov, agent_path=agent)


def test_sandbox_policy_missing_agent_fields(tmp_path: Path) -> None:
    gov = tmp_path / "governance-policy.json"
    agent = tmp_path / "agent-policy.json"
    gov.write_text(json.dumps({"execution": {"routing": "brokered"}}), encoding="utf-8")
    agent.write_text(json.dumps({"default_deny": False}), encoding="utf-8")
    with pytest.raises(SandboxPolicyError, match="default_deny"):
        compile_sandbox_policy(governance_path=gov, agent_path=agent)


def test_sandbox_policy_not_an_object(tmp_path: Path) -> None:
    gov = tmp_path / "governance-policy.json"
    agent = tmp_path / "agent-policy.json"
    gov.write_text("[]", encoding="utf-8")
    agent.write_text("{}", encoding="utf-8")
    with pytest.raises(SandboxPolicyError, match="not a JSON object"):
        compile_sandbox_policy(governance_path=gov, agent_path=agent)


def test_sandbox_policy_unreadable(tmp_path: Path) -> None:
    missing = tmp_path / "nope.json"
    agent = tmp_path / "agent-policy.json"
    agent.write_text("{}", encoding="utf-8")
    with pytest.raises(SandboxPolicyError, match="unreadable"):
        compile_sandbox_policy(governance_path=missing, agent_path=agent)


def test_sandbox_policy_network_must_be_deny(tmp_path: Path) -> None:
    gov = tmp_path / "governance-policy.json"
    agent = tmp_path / "agent-policy.json"
    gov.write_text(json.dumps({"execution": {"routing": "brokered"}}), encoding="utf-8")
    agent.write_text(
        json.dumps(
            {
                "default_deny": True,
                "high_risk_actions": ["destructive"],
                "rules": {"external_network_default": "allow"},
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(SandboxPolicyError, match="external_network_default"):
        compile_sandbox_policy(governance_path=gov, agent_path=agent)


def test_sandbox_policy_high_risk_and_rules_shape(tmp_path: Path) -> None:
    gov = tmp_path / "governance-policy.json"
    agent = tmp_path / "agent-policy.json"
    gov.write_text(json.dumps({"execution": {"routing": "brokered"}}), encoding="utf-8")
    agent.write_text(json.dumps({"default_deny": True, "high_risk_actions": [1]}), encoding="utf-8")
    with pytest.raises(SandboxPolicyError, match="high_risk_actions"):
        compile_sandbox_policy(governance_path=gov, agent_path=agent)
    agent.write_text(
        json.dumps({"default_deny": True, "high_risk_actions": ["destructive"], "rules": []}),
        encoding="utf-8",
    )
    with pytest.raises(SandboxPolicyError, match="rules must be an object"):
        compile_sandbox_policy(governance_path=gov, agent_path=agent)


def test_sandbox_policy_invalid_utf8(tmp_path: Path) -> None:
    gov = tmp_path / "governance-policy.json"
    agent = tmp_path / "agent-policy.json"
    gov.write_bytes(b"\xff\xfe not utf-8")
    agent.write_text("{}", encoding="utf-8")
    with pytest.raises(SandboxPolicyError, match="not JSON"):
        compile_sandbox_policy(governance_path=gov, agent_path=agent)


def test_sandbox_policy_wraps_routing_error(tmp_path: Path) -> None:
    gov = tmp_path / "governance-policy.json"
    agent = tmp_path / "agent-policy.json"
    gov.write_text(json.dumps({"execution": {"rationale": "no routing key"}}), encoding="utf-8")
    agent.write_text(
        json.dumps(
            {
                "default_deny": True,
                "high_risk_actions": ["destructive"],
                "rules": {"external_network_default": "deny"},
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(SandboxPolicyError, match="execution.routing"):
        compile_sandbox_policy(governance_path=gov, agent_path=agent)
