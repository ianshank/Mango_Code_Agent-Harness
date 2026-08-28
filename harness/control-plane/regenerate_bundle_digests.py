#!/usr/bin/env python3
"""Regenerate policy-bundle.example.json protected_files digests from actual files.

The node/jvm governance scripts are thin delegating shims (single source of truth
in harness/shared/). This recomputes the sha256 of every protected file so the
external-root-of-trust verifier matches the current repository state.

Paths are parameters with repo-relative defaults rather than module constants, so
the regeneration logic can be exercised against a fixture instead of only against
this repository — that is why it previously had no test coverage at all.

Entries whose file no longer exists are dropped so the manifest stays resolvable,
but never silently: each drop is logged at WARNING and summarised on stderr. The
`digest-regen` Make target pairs this with `git diff --exit-code`, so any drop
still turns CI red; the logging is what makes the *reason* visible. Run with
`LOG_LEVEL=DEBUG` to see every file digested.
"""
from __future__ import annotations

import hashlib
import json
import logging
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent.parent
BUNDLE = REPO / "harness" / "control-plane" / "policy-bundle.example.json"
STACK_ROOTS = {"node": REPO / "harness" / "node", "jvm": REPO / "harness" / "jvm"}


def _gate_logger() -> logging.Logger:
    """Return the shared gate logger, degrading to a bare one if unimportable.

    This runs as `python harness/control-plane/...`, where the repo root is not on
    sys.path. Diagnostics must never be able to fail the gate, so an import problem
    degrades rather than raising.
    """
    try:
        if str(REPO) not in sys.path:
            sys.path.insert(0, str(REPO))
        from harness.shared.json_logging import configure_gate_logging

        return configure_gate_logging(__name__)
    except Exception:  # noqa: BLE001 - logging setup must never break a gate
        # Non-propagating: the root logger may be configured to write to stdout
        # (setup_json_logging does exactly that), which would put diagnostics into
        # the stdout summary this script's callers parse.
        fallback = logging.getLogger(__name__)
        fallback.propagate = False
        if not fallback.handlers:
            fallback.addHandler(logging.StreamHandler(sys.stderr))
        return fallback


logger = _gate_logger()


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def regenerate(
    bundle_path: Path | None = None,
    stack_roots: dict[str, Path] | None = None,
) -> tuple[dict, dict[str, list[str]]]:
    """Recompute digests in place and return (bundle, dropped-entries-by-stack).

    Pure with respect to the filesystem apart from reading the protected files:
    the caller decides whether to persist the result, which is what makes the
    drift behaviour testable without writing to the real bundle.
    """
    bundle_path = bundle_path if bundle_path is not None else BUNDLE
    stack_roots = stack_roots if stack_roots is not None else STACK_ROOTS
    bundle = json.loads(bundle_path.read_text(encoding="utf-8"))
    dropped: dict[str, list[str]] = {}
    for stack, root in stack_roots.items():
        profile = bundle.get("profiles", {}).get(stack, {})
        protected = profile.get("protected_files", {})
        for rel in list(protected):
            actual = root / rel
            if actual.is_file():
                protected[rel] = digest(actual)
                logger.debug("%s: digested %s", stack, rel)
            else:
                # The file moved or was deleted. Dropping keeps the manifest
                # resolvable; the WARNING is what stops it from being invisible.
                protected.pop(rel, None)
                dropped.setdefault(stack, []).append(rel)
                logger.warning("%s: dropped stale protected-file entry %s", stack, rel)
        if not protected:
            logger.warning("%s profile has no resolvable protected files", stack)
            print(f"[WARN] {stack} profile has no resolvable protected files")
    return bundle, dropped


def main(
    bundle_path: Path | None = None,
    stack_roots: dict[str, Path] | None = None,
) -> int:
    bundle_path = bundle_path if bundle_path is not None else BUNDLE
    stack_roots = stack_roots if stack_roots is not None else STACK_ROOTS
    bundle, dropped = regenerate(bundle_path, stack_roots)
    bundle_path.write_text(json.dumps(bundle, indent=2) + "\n", encoding="utf-8")
    print(f"[PASS] Regenerated digests for {bundle_path}")
    for stack in stack_roots:
        # `.get()` chain mirrors regenerate(): a stack_roots override naming a stack
        # the bundle does not declare must report zero, not raise KeyError.
        profile = bundle.get("profiles", {}).get(stack, {})
        count = len(profile.get("protected_files", {}))
        print(f"  {stack}: {count} protected file digests")
    for stack, entries in dropped.items():
        # stderr, so the stdout summary above stays a stable, parseable shape.
        print(f"[WARN] {stack}: dropped {len(entries)} stale entry(ies): {entries}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
