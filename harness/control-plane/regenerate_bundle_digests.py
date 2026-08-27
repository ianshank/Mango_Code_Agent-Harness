#!/usr/bin/env python3
"""Regenerate policy-bundle.example.json protected_files digests from actual files.

The node/jvm governance scripts are now thin delegating shims (single source of
truth in harness/shared/). This recomputes the sha256 of every protected file so
the external-root-of-trust verifier matches the current repository state.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent.parent
BUNDLE = REPO / "harness" / "control-plane" / "policy-bundle.example.json"
STACK_ROOTS = {"node": REPO / "harness" / "node", "jvm": REPO / "harness" / "jvm"}


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    bundle = json.loads(BUNDLE.read_text())
    for stack, root in STACK_ROOTS.items():
        profile = bundle.get("profiles", {}).get(stack, {})
        protected = profile.get("protected_files", {})
        for rel in list(protected):
            actual = root / rel
            if actual.is_file():
                protected[rel] = digest(actual)
            else:
                # File no longer exists at this path; drop the stale entry.
                protected.pop(rel, None)
        if not protected:
            print(f"[WARN] {stack} profile has no resolvable protected files")
    BUNDLE.write_text(json.dumps(bundle, indent=2) + "\n")
    print(f"[PASS] Regenerated digests for {BUNDLE}")
    for stack in STACK_ROOTS:
        n = len(bundle["profiles"][stack]["protected_files"])
        print(f"  {stack}: {n} protected file digests")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
