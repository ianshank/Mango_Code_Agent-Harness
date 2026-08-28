#!/usr/bin/env python3
"""Projection drift gate: mapped source/projection file pairs must be identical.

Standalone stdlib script by design (like validate_invariants.py): per-stack
shims runpy this file as __main__ from arbitrary CWDs, so it imports nothing
from the harness package.
"""
import argparse
import json
import re
from pathlib import Path

# Fallback decision-ID grammar for the adopter path (no policy file). The
# authoritative copy is governance-policy.json `decision_id_pattern`; the
# lockstep test in test_policy_consistency.py pins this literal to it.
FALLBACK_ID_PATTERN = r"\b(DEC-[0-9]+|RB-[0-9]+[a-z]?|G-[A-Z]+|S[0-9]+\.[0-9]+)\b"
POLICY_PATH = Path(__file__).resolve().parent / "governance-policy.json"


def decision_id_regex() -> "re.Pattern[str]":
    """Decision-ID grammar from the policy, converted from the anchored
    ``^(...)$`` form to the ``\\b(...)\\b`` search form. No policy file is the
    adopter path (fallback literal); a present-but-malformed policy fails
    closed."""
    if not POLICY_PATH.is_file():
        # Absent is the adopter path; present-but-not-a-regular-file is a broken
        # deployment and must stop the run. is_file() answers False for both, so
        # branching on it alone would silently use the fallback grammar when the
        # governing policy is a directory or a dangling symlink. exists() is
        # checked alongside is_symlink() because exists() follows symlinks and
        # answers False for a dangling one.
        if POLICY_PATH.exists() or POLICY_PATH.is_symlink():
            raise SystemExit(
                f"projections: policy path {POLICY_PATH} exists but is not a regular file; "
                "refusing to fall back to the built-in decision-ID grammar"
            )
        return re.compile(FALLBACK_ID_PATTERN)
    try:
        pattern = json.loads(POLICY_PATH.read_text(encoding="utf-8"))["decision_id_pattern"]
        body = re.fullmatch(r"\^\((.*)\)\$", pattern).group(1)  # type: ignore[union-attr]
    except (OSError, ValueError, KeyError, AttributeError, TypeError) as exc:
        raise SystemExit(f"projections: unusable decision_id_pattern in {POLICY_PATH}: {exc}") from exc
    return re.compile(r"\b(" + body + r")\b")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default=".governance/projections.json")
    ap.add_argument("--decision-log", default=".governance/decision-log.md")
    ns = ap.parse_args()
    cfg = json.loads(Path(ns.config).read_text())
    known = set(decision_id_regex().findall(Path(ns.decision_log).read_text()))
    if not cfg.get("enabled", False):
        d = cfg.get("decision_id", "")
        if d not in known:
            raise SystemExit("projections: disabled without a decision-log entry")
        print(f"projections: explicitly not applicable under {d}")
        raise SystemExit(0)
    fail = []
    for m in cfg.get("mappings", []):
        a, b = Path(m["source"]), Path(m["projection"])
        if not a.is_file() or not b.is_file():
            fail.append(f"missing mapping endpoint: {a} -> {b}")
            continue
        if a.read_bytes() != b.read_bytes():
            fail.append(f"drift: {a} != {b}")
    if not cfg.get("mappings"):
        fail.append("enabled but no mappings configured")
    if fail:
        raise SystemExit("projections: FAILED\n  - " + "\n  - ".join(fail))
    print("projections: passed")


if __name__ == "__main__":
    main()
