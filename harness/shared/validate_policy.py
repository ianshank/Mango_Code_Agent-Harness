#!/usr/bin/env python3
"""
Validation script: enforce required keys and CI gate structure in ``governance-policy.json``.

Checks: presence of required top-level keys, ``ci_required_targets`` entry format
(must contain colon-delimited path:target pairs), and ``agent_defaults`` key types.
Exits non-zero with a descriptive message on any violation.
"""
import json
import re
from pathlib import Path


def main(policy_path: Path = Path(".governance/policy.json")) -> None:
    p = json.loads(policy_path.read_text())
    for k in (
        "target_contract",
        "pre_pr_order",
        "ci_required_targets",
        "decision_id_pattern",
        "agent_defaults",
        "protected_paths",
        "charter_version",
        "governance_skill_path",
        "skill_max_age_days",
    ):
        if not p.get(k):
            raise SystemExit(f"policy: missing {k}")
    re.compile(p["decision_id_pattern"])
    required_ci = {
        "cov",
        "lint",
        "types",
        "secrets",
        "specs",
        "audit",
        "remotes",
        "projections",
        "traceability",
        "governance",
    }
    missing = required_ci - set(p["ci_required_targets"])
    if missing:
        raise SystemExit("policy: critical CI gates omitted: " + ", ".join(sorted(missing)))
    for critical in (
        ".governance/**",
        ".github/workflows/**",
        "Makefile",
        "scripts/remotes.py",
        "scripts/verify_zero_skips.py",
    ):
        if critical not in p["protected_paths"]:
            raise SystemExit(f"policy: critical protected path omitted: {critical}")
    if p.get("external_root_of_trust_required") is not True:
        raise SystemExit("policy: external root of trust must be required")
    if p["agent_defaults"].get("deny_unclassified_side_effects") is not True:
        raise SystemExit("policy: unclassified side effects must be denied")
    print("policy: passed")

if __name__ == "__main__":
    main()
