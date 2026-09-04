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
import logging
import sys
from pathlib import Path

try:
    from harness.shared.coverage_scope import (
        OPTIONAL_EXTRAS_KEY,
        check_measured_set,
        check_per_file,
        declared_source_roots,
        first_party_sources,
        optional_extra_waivers,
    )
    from harness.shared.coverage_scope import (
        _importable as _importable,
    )
    from harness.shared.coverage_scope import (
        _load_json_object as _load_json_object,
    )
    from harness.shared.coverage_scope import (
        _waiving_extra as _waiving_extra,
    )
    from harness.shared.json_logging import configure_gate_process_logging
except ImportError:  # direct `python harness/shared/coverage_gate.py`
    from coverage_scope import (  # type: ignore[no-redef]
        OPTIONAL_EXTRAS_KEY,
        check_measured_set,
        check_per_file,
        declared_source_roots,
        first_party_sources,
        optional_extra_waivers,
    )
    from coverage_scope import _importable as _importable  # type: ignore[no-redef]
    from coverage_scope import _load_json_object as _load_json_object  # type: ignore[no-redef]
    from coverage_scope import _waiving_extra as _waiving_extra  # type: ignore[no-redef]
    from json_logging import configure_gate_process_logging  # type: ignore[no-redef]

#: Re-exported so `coverage_gate.<name>` keeps working for every existing caller
#: and test after the scope concern moved to `coverage_scope.py`. The split is an
#: internal reorganisation; the module's public surface is unchanged.
__all__ = [
    "OPTIONAL_EXTRAS_KEY",
    "check",
    "check_measured_set",
    "check_per_file",
    "declared_source_roots",
    "first_party_sources",
    "load_thresholds",
    "main",
    "measure",
    "optional_extra_waivers",
    "per_file_enabled",
]

logger = logging.getLogger(__name__)

DEFAULT_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
POLICY_RELPATH = Path("harness") / "shared" / "governance-policy.json"
COVERAGE_JSON = Path("coverage.json")

# Metric name in policy -> (numerator key, denominator key) in coverage.json totals.
ENFORCED_METRICS = {
    "lines": ("covered_lines", "num_statements"),
    "branches": ("covered_branches", "num_branches"),
}


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


def per_file_enabled(policy_path: Path) -> bool:
    """True when the policy declares per-file enforcement (coverage.per_file).

    Absent means off -- per-file enforcement is opt-in. But *present and not a
    boolean* fails closed rather than being coerced: this value decides whether
    a gate runs at all, so `bool(...)` would read ``0``, ``[]``, ``null`` or the
    string ``"no"`` as a decision instead of as the malformed policy it is, and
    silently disable enforcement while the gate reported success. Every other
    reader in this module does the same strict check.
    """
    policy = _load_json_object(policy_path, "governance policy")
    coverage = policy.get("coverage")
    if not isinstance(coverage, dict):
        logger.error("[FAIL] Governance policy %s has no coverage block", policy_path)
        raise SystemExit(1)
    if "per_file" not in coverage:
        return False
    per_file = coverage["per_file"]
    if not isinstance(per_file, bool):
        logger.error(
            "[FAIL] Governance policy %s declares coverage.per_file as %r (%s); "
            "it must be true or false",
            policy_path, per_file, type(per_file).__name__,
        )
        raise SystemExit(1)
    return per_file


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
    parser.add_argument("--repo-root", type=Path, default=DEFAULT_REPO_ROOT)
    args = parser.parse_args(argv)
    thresholds = load_thresholds(args.policy)
    measured = measure(args.coverage_json)
    ok = check(thresholds, measured)
    if per_file_enabled(args.policy):
        # Bound the measured set before judging it. The two are one control: the
        # per-file floor is a promise about every first-party file, and it can
        # only keep that promise if the report contains every first-party file.
        # A policy that has not opted into per-file enforcement is making no
        # such promise, so there is nothing here to bound.
        ok = check_measured_set(args.coverage_json, args.repo_root, args.repo_root / "pyproject.toml") and ok
        waived = optional_extra_waivers(args.policy)
        ok = check_per_file(args.coverage_json, thresholds["lines"], waived) and ok
    return 0 if ok else 1


if __name__ == "__main__":
    configure_gate_process_logging()
    sys.exit(main())
