"""Dynamic Coverage Gate Enforcer.

Reads the coverage threshold from governance-policy.json (single source of truth)
and dynamically injects --cov-fail-under into pytest invocations, failing closed
if policy is missing or malformed.
"""

from __future__ import annotations

import json
import logging
import subprocess
import sys
from pathlib import Path

logger = logging.getLogger(__name__)


def resolve_policy_path(custom_path: Path | None = None) -> Path:
    """Resolve the governance policy path reliably relative to repo structure."""
    if custom_path is not None:
        return custom_path
    repo_root = Path(__file__).resolve().parent.parent.parent
    return repo_root / "harness" / "shared" / "governance-policy.json"


def load_coverage_threshold(policy_path: Path) -> int:
    """Load the minimum lines coverage threshold from the governance policy."""
    if not policy_path.exists():
        raise FileNotFoundError(f"[FAIL] {policy_path} does not exist. Failing closed.")

    try:
        policy = json.loads(policy_path.read_text(encoding="utf-8"))
        coverage_sec = policy.get("coverage", {})
        if "lines" not in coverage_sec:
            raise KeyError("Missing 'coverage.lines' threshold in policy")
        return int(coverage_sec["lines"])
    except Exception as e:
        raise ValueError(f"[FAIL] Failed to parse coverage policy from {policy_path}: {e}") from e


def main(argv: list[str] | None = None, policy_path: Path | None = None) -> int:
    """Execute pytest with dynamically injected --cov-fail-under threshold."""
    target_policy = resolve_policy_path(policy_path)
    try:
        lines_cov = load_coverage_threshold(target_policy)
    except Exception as e:
        logger.error(str(e))
        print(str(e), file=sys.stderr)
        return 1

    args = list(argv) if argv is not None else sys.argv[1:]
    if not args:
        args = ["python", "-m", "pytest"]

    cmd = args + [f"--cov-fail-under={lines_cov}"]
    logger.info("Running coverage gate: %s", " ".join(cmd))
    print(f"Running coverage gate: {' '.join(cmd)}")
    try:
        return subprocess.call(cmd)
    except KeyboardInterrupt:
        return 1
    except Exception as e:
        logger.error("Failed to execute command %s: %s", cmd, e)
        print(f"[FAIL] Failed to execute coverage command: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    sys.exit(main())
