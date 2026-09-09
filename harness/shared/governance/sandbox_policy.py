"""In-memory isolation policy compiler (R-AEI-14, C-AEI-2).

Compiled from ``governance-policy.json`` and ``agent-policy.json`` at backend
start. Nothing here is written to disk: a committed derived copy would be the
same stale-governance bug ``authority_graph.py`` already refuses. Does not
import ``broker``.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from harness.shared.agent_authority import DEFAULT_AGENT_POLICY_PATH
from harness.shared.policy_loader import POLICY_PATH, PolicyError, execution_routing

_FILESYSTEM = "workspace"
_NETWORK_DENY = "deny"


class SandboxPolicyError(Exception):
    """Compilation failed; the isolation backend must return BLOCKED."""


@dataclass(frozen=True)
class CompiledSandboxPolicy:
    """Allow/deny view derived from the two JSON sources. Never persisted."""

    routing: str
    default_deny: bool
    network_outbound: str
    filesystem: str
    high_risk_actions: tuple[str, ...]
    governance_digest: str
    agent_digest: str
    compiled_digest: str


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _read_object(path: Path, label: str) -> tuple[bytes, dict[str, Any]]:
    try:
        raw = path.read_bytes()
    except OSError as exc:
        raise SandboxPolicyError(f"{label} unreadable: {path}: {exc}") from exc
    try:
        loaded = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise SandboxPolicyError(f"{label} is not JSON: {path}: {exc}") from exc
    if not isinstance(loaded, dict):
        raise SandboxPolicyError(f"{label} is not a JSON object: {path}")
    return raw, loaded


def _require_agent_fields(agent: dict[str, Any]) -> tuple[bool, tuple[str, ...]]:
    if agent.get("default_deny") is not True:
        raise SandboxPolicyError("agent-policy default_deny must be true")
    high_risk = agent.get("high_risk_actions")
    if not isinstance(high_risk, list) or not all(isinstance(item, str) for item in high_risk):
        raise SandboxPolicyError("agent-policy high_risk_actions must be a list of strings")
    rules = agent.get("rules")
    if not isinstance(rules, dict):
        raise SandboxPolicyError("agent-policy rules must be an object")
    if rules.get("external_network_default") != _NETWORK_DENY:
        raise SandboxPolicyError("agent-policy rules.external_network_default must be deny")
    return True, tuple(high_risk)


def compile_sandbox_policy(
    governance_path: Path | None = None,
    agent_path: Path | None = None,
) -> CompiledSandboxPolicy:
    """Rebuild the allow/deny view from the two sources (R-AEI-14).

    ``governance_path`` defaults to ``policy_loader.POLICY_PATH``.
    ``agent_path`` defaults to ``agent_authority.DEFAULT_AGENT_POLICY_PATH``.
    Parse, I/O, semantic mismatch, or a routing-reader ``PolicyError`` raises
    ``SandboxPolicyError`` (the ``PolicyError`` is wrapped, never leaked),
    never a silent default.
    """
    gov_path = POLICY_PATH if governance_path is None else governance_path
    ag_path = DEFAULT_AGENT_POLICY_PATH if agent_path is None else agent_path
    gov_raw, _gov = _read_object(gov_path, "governance-policy")
    agent_raw, agent = _read_object(ag_path, "agent-policy")
    try:
        routing = execution_routing(gov_path)
    except PolicyError as exc:
        raise SandboxPolicyError(f"execution.routing: {exc}") from exc
    default_deny, high_risk = _require_agent_fields(agent)
    gov_digest = _sha256(gov_raw)
    agent_digest = _sha256(agent_raw)
    view = {
        "routing": routing,
        "default_deny": default_deny,
        "network_outbound": _NETWORK_DENY,
        "filesystem": _FILESYSTEM,
        "high_risk_actions": list(high_risk),
        "governance_digest": gov_digest,
        "agent_digest": agent_digest,
    }
    compiled_digest = _sha256(
        json.dumps(view, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")
    )
    return CompiledSandboxPolicy(
        routing=routing,
        default_deny=default_deny,
        network_outbound=_NETWORK_DENY,
        filesystem=_FILESYSTEM,
        high_risk_actions=high_risk,
        governance_digest=gov_digest,
        agent_digest=agent_digest,
        compiled_digest=compiled_digest,
    )


__all__ = [
    "CompiledSandboxPolicy",
    "SandboxPolicyError",
    "compile_sandbox_policy",
]
