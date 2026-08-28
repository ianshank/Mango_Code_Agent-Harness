#!/usr/bin/env python3
"""Coverage gate: apply the governance policy's line and branch thresholds separately.

Why this exists: with ``[tool.coverage.run] branch = true``, the single "total"
percentage that ``--cov-fail-under`` gates is a *blend* of statements and
branches. Gating that blend against ``coverage.lines`` mislabels the number --
line coverage could regress well below the declared floor while the blend stays
green, and ``coverage.branches`` would still be applied nowhere. This gate reads
the machine-readable ``coverage.json`` and enforces each declared threshold
against its own metric:

* ``coverage.lines``    vs ``covered_lines / num_statements``
* ``coverage.branches`` vs ``covered_branches / num_branches``

Fail-closed contract (matches its sibling gates): a missing, unreadable, or
malformed coverage report or policy exits 1 with a reason -- absence of
evidence is never a pass. Thresholds have exactly one source,
``governance-policy.json``; nothing here carries a numeric default.

Exit codes: 0 = all enforced thresholds met, 1 = violation or unreadable input.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

try:
    from harness.shared.json_logging import resolve_log_level
except ImportError:  # direct `python harness/shared/coverage_gate.py`
    from json_logging import resolve_log_level  # type: ignore[no-redef]

logger = logging.getLogger(__name__)

DEFAULT_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
POLICY_RELPATH = Path("harness") / "shared" / "governance-policy.json"
COVERAGE_JSON = Path("coverage.json")

# Metric name in policy -> (numerator key, denominator key) in coverage.json totals.
ENFORCED_METRICS = {
    "lines": ("covered_lines", "num_statements"),
    "branches": ("covered_branches", "num_branches"),
}


def _load_json_object(path: Path, what: str) -> dict:
    """Fail-closed read: any unreadable or non-object input exits 1 with a reason."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            raise TypeError(f"root must be a JSON object, got {type(data).__name__}")
        return data
    except (OSError, ValueError, TypeError) as e:
        logger.error("[FAIL] Could not read %s from %s: %s", what, path, e)
        raise SystemExit(1) from e


def load_thresholds(policy_path: Path) -> dict[str, float]:
    """Return the enforced thresholds from policy. Absent keys fail closed.

    Unlike the size/dedup gates, there is no adopter default here: a repository
    that wires this gate has declared coverage governance, and running with a
    silently-invented floor is the COV_MIN inversion this gate replaced.
    """
    policy = _load_json_object(policy_path, "governance policy")
    coverage = policy.get("coverage")
    if not isinstance(coverage, dict):
        logger.error("[FAIL] Governance policy %s has no coverage block", policy_path)
        raise SystemExit(1)
    thresholds: dict[str, float] = {}
    for metric in ENFORCED_METRICS:
        value = coverage.get(metric)
        if not isinstance(value, (int, float)) or isinstance(value, bool):
            logger.error(
                "[FAIL] Governance policy %s: coverage.%s is missing or non-numeric", policy_path, metric
            )
            raise SystemExit(1)
        thresholds[metric] = float(value)
    return thresholds


def measure(coverage_json: Path) -> dict[str, float]:
    """Extract per-metric percentages from coverage.json's totals block."""
    totals = _load_json_object(coverage_json, "coverage report").get("totals")
    if not isinstance(totals, dict):
        logger.error("[FAIL] Coverage report %s has no totals block", coverage_json)
        raise SystemExit(1)
    measured: dict[str, float] = {}
    for metric, (num_key, den_key) in ENFORCED_METRICS.items():
        numerator, denominator = totals.get(num_key), totals.get(den_key)
        if not isinstance(numerator, int) or not isinstance(denominator, int):
            logger.error(
                "[FAIL] Coverage report %s lacks %s/%s -- was pytest run with "
                "--cov-report=json and branch coverage enabled?",
                coverage_json, num_key, den_key,
            )
            raise SystemExit(1)
        if denominator == 0:
            logger.error("[FAIL] Coverage report %s measured zero %s", coverage_json, den_key)
            raise SystemExit(1)
        measured[metric] = 100.0 * numerator / denominator
    return measured


def check(thresholds: dict[str, float], measured: dict[str, float]) -> bool:
    """Return True when every enforced metric meets its own threshold."""
    ok = True
    for metric, floor in sorted(thresholds.items()):
        actual = measured[metric]
        if actual < floor:
            logger.error("[FAIL] Coverage %s: %.2f%% is below the policy floor of %.2f%%", metric, actual, floor)
            ok = False
        else:
            logger.info("[PASS] Coverage %s: %.2f%% >= %.2f%%", metric, actual, floor)
    return ok


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--coverage-json", type=Path, default=COVERAGE_JSON)
    parser.add_argument("--policy", type=Path, default=DEFAULT_REPO_ROOT / POLICY_RELPATH)
    args = parser.parse_args(argv)
    thresholds = load_thresholds(args.policy)
    measured = measure(args.coverage_json)
    return 0 if check(thresholds, measured) else 1


if __name__ == "__main__":
    logging.basicConfig(level=resolve_log_level(), format="%(levelname)s: %(message)s")
    sys.exit(main())
