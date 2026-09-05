#!/usr/bin/env python3
"""
Validation script: enforce structural correctness of ``.governance/agent-policy.json``.

Checks: required roles, default_deny, high_risk_actions, delegation depth,
allowed_actions, human_approval_required_for, and mandatory rule assertions.
Exits non-zero with a descriptive message on any violation.
"""

import json
from pathlib import Path


def main(policy_path: Path = Path(".governance/agent-policy.json")) -> None:
    p = policy_path
    d = json.loads(p.read_text())
    required = {
        "orchestrator",
        "spec-analyst",
        "implementer",
        "test-eval",
        "security-reviewer",
        "peer-reviewer",
        "release-auditor",
    }
    roles = {x["id"]: x for x in d.get("agents", [])}
    missing = required - set(roles)
    if missing:
        raise SystemExit("agent-policy: missing roles: " + ", ".join(sorted(missing)))
    if d.get("default_deny") is not True:
        raise SystemExit("agent-policy: default_deny must be true")
    limits = d.get("limits", {})
    high = set(d.get("high_risk_actions", []))
    if not high:
        raise SystemExit("agent-policy: high_risk_actions must be declared")
    for rid, r in roles.items():
        if r.get("delegation_depth", 99) > limits.get("max_delegation_depth", -1):
            raise SystemExit(f"agent-policy: {rid} exceeds delegation depth")
        allowed = r.get("allowed_actions")
        approvals = r.get("human_approval_required_for")
        if not isinstance(allowed, list):
            raise SystemExit(f"agent-policy: {rid} has no allowed_actions")
        if not isinstance(approvals, list):
            raise SystemExit(f"agent-policy: {rid} has no human_approval_required_for list")
        if not set(approvals).issubset(set(allowed)):
            raise SystemExit(f"agent-policy: {rid} approval action is not allowed to the role")
        unapproved = high.intersection(allowed) - set(approvals)
        if unapproved:
            msg = f"agent-policy: {rid} high-risk actions lack human approval: {', '.join(sorted(unapproved))}"
            raise SystemExit(msg)
    rules = d.get("rules", {})
    for key in (
        "self_modify_policy",
        "secrets_may_not_be_propagated_to_subagents",
        "delegation_does_not_transfer_authority",
        "every_side_effect_requires_trace_id",
    ):
        if key not in rules:
            raise SystemExit(f"agent-policy: missing rule {key}")
    if rules["self_modify_policy"] is not False:
        raise SystemExit("agent-policy: agents may not self-modify policy")
    if rules["secrets_may_not_be_propagated_to_subagents"] is not True:
        raise SystemExit("agent-policy: secret propagation must be prohibited")
    if rules["delegation_does_not_transfer_authority"] is not True:
        raise SystemExit("agent-policy: delegation must not transfer authority")
    if rules["every_side_effect_requires_trace_id"] is not True:
        raise SystemExit("agent-policy: side effects require trace IDs")
    print("agent-policy: passed")


if __name__ == "__main__":
    main()
