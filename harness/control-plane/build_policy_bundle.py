#!/usr/bin/env python3
"""Build a candidate protected bundle. Output must be independently reviewed/published.

Wired into `make digest-regen` behind `git diff --exit-code`: it is the only
regenerator of the bundle's top-level governance/agent policy digests, which
verify_repository.py (exercised in CI by test_harness.py) checks against the
per-stack .governance files. Without this wiring, a per-stack policy edit left
the committed bundle stale with nothing noticing."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


COMMON = [
    "Makefile",
    ".github/workflows/ci.yml",
    "scripts/remotes.py",
    "scripts/pretooluse_guard.py",
    "scripts/pretooluse_guard.sh",
    "scripts/pre_push_scan.sh",
    "scripts/install_hooks.sh",
    "scripts/verify_zero_skips.py",
    "scripts/validate_specs.sh",
    "scripts/validate_policy.py",
    "scripts/validate_agent_policy.py",
    "scripts/validate_governance_docs.py",
    "scripts/validate_adoption.py",
    "scripts/check_traceability.py",
    "scripts/check_projections.py",
]
PROFILE = {
    "node": ["package.json", "tsconfig.json", "vitest.config.ts", "tests/governance/meta.test.ts"],
    "jvm": [
        "build.gradle.kts",
        "settings.gradle.kts",
        "gradle.properties",
        "src/test/kotlin/governance/GovernanceMetaTest.kt",
        "src/test/kotlin/governance/ZeroSkipListener.kt",
        "src/test/resources/META-INF/services/org.junit.platform.launcher.TestExecutionListener",
    ],
}
MARKER = {"node": "package.json", "jvm": "build.gradle.kts"}


def build(roots: dict[str, Path]) -> dict:
    """Assemble the candidate bundle. Fails closed: a missing protected file aborts."""
    profiles = {}
    for name, root in roots.items():
        files = COMMON + PROFILE[name]
        missing = [f for f in files if not (root / f).is_file()]
        if missing:
            raise SystemExit(f"{name}: missing protected files: {missing}")
        profiles[name] = {"marker": MARKER[name], "protected_files": {f: sha(root / f) for f in files}}
    node = roots["node"]
    return {
        "policy_id": "agentic-ssd-governance",
        "version": "2.0.0",
        # The ONLY regenerator of these two top-level digests; regenerate_bundle_digests.py
        # refreshes profiles[*].protected_files and never touches them.
        "governance_policy_sha256": sha(node / ".governance/policy.json"),
        "agent_policy_sha256": sha(node / ".governance/agent-policy.json"),
        "deny_if_digest_mismatch": True,
        "human_approval_categories": [
            "external_write",
            "destructive",
            "secret_access",
            "permission_change",
            "production_change",
        ],
        "profiles": profiles,
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--node", required=True)
    ap.add_argument("--jvm", required=True)
    ap.add_argument("--output", required=True)
    ns = ap.parse_args(argv)
    bundle = build({"node": Path(ns.node).resolve(), "jvm": Path(ns.jvm).resolve()})
    Path(ns.output).write_text(json.dumps(bundle, indent=2) + "\n")
    print(f"candidate bundle written: {ns.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
