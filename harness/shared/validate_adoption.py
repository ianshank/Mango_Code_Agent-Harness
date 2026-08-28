#!/usr/bin/env python3
"""Adoption readiness gate: the repository has the artifacts a governed
downstream consumer needs (pinned CI, an approved remote, a root of trust that
matches the local policy, and lockfiles for whichever stacks are present).

Structure note: every check lives inside ``main(root)``. This module used to be
45 lines of module-level code that read files, printed, and raised SystemExit
**at import**, which meant `import harness.shared.validate_adoption` ran the
gate and could take the interpreter down. Its two sibling control-plane CLIs
were made importable earlier in this program; this one survived because nothing
enforced the rule. ``test_import_purity.py`` is now that rule.

The per-stack shims ``runpy.run_path(..., run_name="__main__")`` this file, so
the ``__main__`` guard below preserves their behavior exactly: same CLI, same
CWD-relative path resolution, same exit codes, same stdout/stderr.
"""
from __future__ import annotations

import hashlib
import json
import re
import sys
from pathlib import Path

DIGEST_RE = re.compile(r"[0-9a-fA-F]{64}")


def check_adoption(root: Path) -> list[str]:
    """Return the list of adoption blockers; empty means ready.

    Pure with respect to the process: it reads the tree and returns findings
    rather than printing or exiting, so callers (and tests) can inspect the
    result instead of capturing stdout.
    """
    fail: list[str] = []

    ci = root / ".github/workflows/ci.yml"
    if not ci.is_file():
        fail.append("CI workflow missing")
    elif "PIN_FULL_COMMIT_SHA" in ci.read_text(encoding="utf-8"):
        fail.append("third-party action SHAs are not pinned yet")

    allowed = root / ".governance/allowed-remotes.txt"
    if not allowed.is_file() or not [
        x for x in allowed.read_text(encoding="utf-8").splitlines()
        if x.strip() and not x.lstrip().startswith("#")
    ]:
        fail.append("allowed-remotes.txt has no approved destination")

    policy = root / ".governance/policy.json"
    policy_digest = hashlib.sha256(policy.read_bytes()).hexdigest() if policy.is_file() else ""
    rot = root / ".governance/root-of-trust.json"
    if not rot.is_file():
        fail.append("root-of-trust.json missing (external policy reference/digest required)")
    else:
        try:
            data = json.loads(rot.read_text(encoding="utf-8"))
            declared = data.get("policy_sha256", "")
            if not data.get("external_policy_ref") or not DIGEST_RE.fullmatch(declared):
                fail.append("root-of-trust.json lacks external policy ref or SHA-256 digest")
            elif not policy_digest:
                fail.append(".governance/policy.json missing")
            elif declared.lower() != policy_digest.lower():
                fail.append("root-of-trust.json policy_sha256 does not match local policy.json")
        except Exception as e:  # noqa: BLE001 - any unreadable root of trust is a blocker
            fail.append(f"root-of-trust.json invalid: {e}")

    if (root / "package.json").exists() and not (root / "pnpm-lock.yaml").is_file():
        fail.append("pnpm-lock.yaml missing")
    if (root / "build.gradle.kts").exists():
        for name in ("gradlew", "gradle.lockfile", "gradle/verification-metadata.xml"):
            if not (root / name).exists():
                fail.append(f"{name} missing")
    return fail


def main(root: Path | None = None) -> None:
    """CLI entry point. Exits 1 with the blockers on stderr, or prints the
    pass verdict -- the stdout contract the per-stack Makefiles depend on."""
    fail = check_adoption(Path(".") if root is None else root)
    if fail:
        print("adoption: BLOCKED", file=sys.stderr)
        for item in fail:
            print("  - " + item, file=sys.stderr)
        raise SystemExit(1)
    print("adoption: passed")


if __name__ == "__main__":
    main()
