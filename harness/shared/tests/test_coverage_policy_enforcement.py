"""Is every coverage threshold the policy declares actually enforced somewhere?

`governance-policy.json` declares `lines`, `statements`, `functions`, `branches`
and `per_file`. The Python gate applies only `lines`, and only in aggregate. The
Node config applies all five — but `make test-node` runs `vitest run` **without
`--coverage`**, so those thresholds never evaluate in root CI.

A declared-but-unenforced threshold reads as governance in a CI report while
guaranteeing nothing. This module makes each one either enforced or explicitly
declared unenforced with a measured reason, so the gap cannot stay accidental.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[3]
POLICY = REPO / "harness" / "shared" / "governance-policy.json"
ROOT_MAKEFILE = REPO / "Makefile"
PYPROJECT = REPO / "pyproject.toml"
VITEST_CONFIG = REPO / "harness" / "node" / "vitest.config.ts"

pytestmark = pytest.mark.governance

# Thresholds the *Python* gate applies (coverage_gate.py, one floor per metric).
PYTHON_ENFORCED = {"lines", "branches"}

# Declared thresholds with no enforcement in the root pipeline. Each needs a
# measured reason: these are the numbers that turn CI red if enabled today, so a
# future change can weigh the cost instead of rediscovering it.
UNENFORCED_IN_ROOT_CI = {
    "per_file": (
        "The Python gate is aggregate-only (coverage_gate.py reads only the "
        "totals block). Measured at the policy's lines=90, six measured files "
        "fail per-file today: "
        "pretooluse_guard.py (75%), remotes.py (75%), publish_policy_artifact.py "
        "(77.85%), validate_adoption.py (85.71%), verify_zero_skips.py (87.5%), "
        "governance/pretooluse_guard.py (87.58%). Aggregate headroom is ~60 "
        "statements, so a new untested module can ship green. Tracked in "
        "harness/CONTRACT.md as a documented follow-up."
    ),
    "statements": (
        "Python: coverage.py's statement and line counts are the same measure at "
        "this granularity (totals carry num_statements/covered_lines), so the "
        "lines floor already covers it. Node: enforced by vitest.config.ts, "
        "which `make test-node` never activates because it runs without "
        "--coverage."
    ),
    "functions": (
        "No Python equivalent is applied. Node enforces it only under --coverage, "
        "which root CI does not pass; measured, circuit-breaker.ts (85.71%) and "
        "web/app.ts (58.33%) would fail."
    ),
}

# Node-side note for the enforced keys: `lines` and `branches` are enforced for
# Python by coverage_gate.py; on the Node side vitest.config.ts declares both but
# `make test-node` runs without --coverage, the declared follow-up. Recorded here
# so moving a key to PYTHON_ENFORCED does not read as "enforced everywhere".


@pytest.fixture(scope="module")
def policy() -> dict:
    loaded: dict = json.loads(POLICY.read_text(encoding="utf-8"))
    return loaded


@pytest.fixture(scope="module")
def makefile() -> str:
    return ROOT_MAKEFILE.read_text(encoding="utf-8")


class TestEveryDeclaredThresholdIsAccountedFor:
    def test_no_threshold_is_silently_unaccounted_for(self, policy):
        declared = set(policy["coverage"])
        unaccounted = sorted(declared - PYTHON_ENFORCED - set(UNENFORCED_IN_ROOT_CI))
        assert not unaccounted, (
            f"coverage keys neither enforced nor declared unenforced: {unaccounted}. "
            "Enforce it, or add it to UNENFORCED_IN_ROOT_CI with a measured reason."
        )

    def test_declared_gaps_still_exist_in_policy(self, policy):
        """A waiver must not outlive the threshold it excuses."""
        stale = sorted(set(UNENFORCED_IN_ROOT_CI) - set(policy["coverage"]))
        assert not stale, f"UNENFORCED_IN_ROOT_CI names thresholds the policy dropped: {stale}"

    @pytest.mark.parametrize("key", sorted(UNENFORCED_IN_ROOT_CI))
    def test_each_declared_gap_carries_a_substantive_reason(self, key):
        assert len(UNENFORCED_IN_ROOT_CI[key].strip()) > 80, (
            f"UNENFORCED_IN_ROOT_CI['{key}'] needs a measured reason, not a placeholder"
        )

    def test_enforced_and_unenforced_sets_are_disjoint(self):
        overlap = sorted(PYTHON_ENFORCED & set(UNENFORCED_IN_ROOT_CI))
        assert not overlap, f"thresholds recorded as both enforced and not: {overlap}"


class TestThresholdSourcing:
    def test_vitest_config_reads_the_policy_rather_than_literals(self):
        """CLAUDE.md forbids hard-coded values; this block used to restate all five."""
        config = VITEST_CONFIG.read_text(encoding="utf-8")
        assert "governance-policy.json" in config, (
            "vitest.config.ts no longer sources thresholds from the governance policy"
        )
        thresholds = re.search(r"thresholds:\s*\{(.*?)\}", config, re.S)
        assert thresholds, "vitest.config.ts declares no coverage thresholds"
        literals = re.findall(r":\s*(\d+)\s*,", thresholds.group(1))
        assert not literals, (
            f"vitest thresholds contain hard-coded numbers {literals}; they must come "
            "from governance-policy.json so the two cannot drift"
        )

    def test_vitest_thresholds_cover_every_policy_key(self, policy):
        config = VITEST_CONFIG.read_text(encoding="utf-8")
        thresholds = re.search(r"thresholds:\s*\{(.*?)\}", config, re.S).group(1)
        for key in ("lines", "statements", "branches", "functions"):
            assert f"policy.{key}" in thresholds, (
                f"vitest threshold '{key}' is not sourced from the policy"
            )
        assert "per_file" in thresholds, "vitest perFile is not sourced from the policy"

    def test_pyproject_does_not_declare_a_competing_threshold(self):
        """A `fail_under` here hard-coded 80 while the policy said 90, so any bare
        `pytest --cov` silently enforced the weaker number."""
        table = re.search(
            r"^\[tool\.coverage\.report\]\s*$(.*?)(?=^\[|\Z)",
            PYPROJECT.read_text(encoding="utf-8"),
            re.M | re.S,
        )
        assert table, "pyproject declares no [tool.coverage.report] table"
        assert not re.search(r"^\s*fail_under\s*=", table.group(1), re.M), (
            "pyproject re-declares fail_under; the threshold has one source, "
            "governance-policy.json -> coverage.lines, applied via $(COV_MIN)"
        )


class TestCoverageGateFailsClosed:
    """The old COV_MIN mechanism lowered itself to 80 on an unreadable policy.

    Its replacement, coverage_gate.py, must keep both fail-closed properties:
    no silent numeric fallback, and no way to pass without a real report.
    These are behavioural probes against the actual script, not string checks
    on the Makefile -- the Makefile wiring is pinned in test_ci_gate_coverage.
    """

    def test_branch_measurement_is_enabled(self):
        """coverage.branches is enforceable only while branch arcs are recorded.

        Deleting `branch = true` would make num_branches vanish from
        coverage.json, and the gate script would then fail closed rather than
        silently pass -- but the honest state is measuring, so this pins it.
        """
        pyproject = (REPO / "pyproject.toml").read_text(encoding="utf-8")
        run_block = re.search(r"^\[tool\.coverage\.run\]\s*$(.*?)(?=^\[)", pyproject, re.M | re.S)
        assert run_block, "pyproject.toml has no [tool.coverage.run] table"
        assert re.search(r"^branch\s*=\s*true\s*$", run_block.group(1), re.M), (
            "[tool.coverage.run] no longer sets branch = true; branch coverage "
            "would be unmeasured and coverage.branches unenforceable"
        )

    def test_gate_fails_closed_when_the_report_is_missing(self, tmp_path):
        from harness.shared import coverage_gate as cg

        with pytest.raises(SystemExit) as exc:
            cg.main(["--coverage-json", str(tmp_path / "absent.json")])
        assert exc.value.code == 1

    def test_gate_fails_closed_on_a_malformed_policy(self, tmp_path):
        from harness.shared import coverage_gate as cg

        report = tmp_path / "coverage.json"
        report.write_text('{"totals": {"covered_lines": 9, "num_statements": 10, '
                          '"covered_branches": 9, "num_branches": 10}}', encoding="utf-8")
        policy = tmp_path / "policy.json"
        policy.write_text("{not json", encoding="utf-8")
        with pytest.raises(SystemExit) as exc:
            cg.main(["--coverage-json", str(report), "--policy", str(policy)])
        assert exc.value.code == 1

    def test_gate_applies_lines_and_branches_as_separate_floors(self, tmp_path):
        """The defect this script replaces: a blended total can satisfy the lines
        floor while branch coverage is far below its own. Lines 91% / branches
        40% must FAIL; the blend (~65%) is never consulted."""
        from harness.shared import coverage_gate as cg

        policy = tmp_path / "policy.json"
        policy.write_text(json.dumps({"coverage": {"lines": 90, "branches": 80}}), encoding="utf-8")
        report = tmp_path / "coverage.json"
        report.write_text(json.dumps({"totals": {
            "covered_lines": 91, "num_statements": 100,
            "covered_branches": 40, "num_branches": 100,
        }}), encoding="utf-8")
        assert cg.main(["--coverage-json", str(report), "--policy", str(policy)]) == 1
        report.write_text(json.dumps({"totals": {
            "covered_lines": 91, "num_statements": 100,
            "covered_branches": 81, "num_branches": 100,
        }}), encoding="utf-8")
        assert cg.main(["--coverage-json", str(report), "--policy", str(policy)]) == 0


class TestDedupBypassIsNotSilentlyOpen:
    def test_dedup_exempt_entries_are_justified(self, policy):
        """`dedup.exempt` disables the drift gate per file with nothing objecting;
        an entry is a deliberate act, so it must be reviewed rather than assumed."""
        exempt = policy.get("dedup", {}).get("exempt", [])
        assert exempt == [], (
            f"dedup.exempt is non-empty ({exempt}); each entry silently disables the "
            "shim-vs-copy drift gate for that file. Record the decision in the "
            "decision log and update this test to name the approved entries."
        )
