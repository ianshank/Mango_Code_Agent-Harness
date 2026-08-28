"""Is every coverage threshold the policy declares actually enforced somewhere?

`governance-policy.json` declares `lines`, `statements`, `functions`, `branches`
and `per_file`. Since the gate-hardening change, the Python gate
(coverage_gate.py) applies `lines` and `branches` in aggregate AND `lines` per
file when `per_file` is true, and `make test-node` runs vitest **with
`--coverage`**, so the Node thresholds (all five, sourced from this policy via
vitest.config.ts) evaluate on every root CI run.

A declared-but-unenforced threshold reads as governance in a CI report while
guaranteeing nothing. This module classifies every declared key as enforced
(and by which stack) or explicitly unenforced with a measured reason, so a gap
cannot stay accidental in either direction.
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

# Thresholds the *Python* gate applies (coverage_gate.py): lines and branches in
# aggregate, plus the lines floor per file when policy per_file is true.
PYTHON_ENFORCED = {"lines", "branches", "per_file"}

# Thresholds the *Node* gate applies: vitest.config.ts sources all of them from
# this policy, and `make test-node` runs vitest with --coverage, so they
# evaluate on every root CI run (per-file included, via perFile).
NODE_ENFORCED = {"lines", "statements", "branches", "functions", "per_file"}

# Keys with no Python-side equivalent, with the measured reason that is not a
# gap: enforcement exists on the Node side, and the Python side either measures
# the same thing under another name or has no such metric.
PYTHON_EQUIVALENT_NOTES = {
    "statements": (
        "coverage.py's statement and line counts are the same measure at this "
        "granularity (totals carry num_statements/covered_lines), so the Python "
        "lines floor already enforces it; the distinct statements number is "
        "enforced on the Node side by vitest --coverage."
    ),
    "functions": (
        "coverage.py does not produce a per-function metric in coverage.json, so "
        "there is nothing for the Python gate to read; function coverage is "
        "enforced on the Node side by vitest --coverage, where the metric exists."
    ),
}

# Declared thresholds with no enforcement anywhere in the root pipeline. Empty
# since the gate-hardening change; the classification machinery stays so any
# future declared-but-unwired key must land here with a measured reason.
UNENFORCED_IN_ROOT_CI: dict[str, str] = {}


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
        unaccounted = sorted(
            declared - PYTHON_ENFORCED - NODE_ENFORCED - set(UNENFORCED_IN_ROOT_CI)
        )
        assert not unaccounted, (
            f"coverage keys neither enforced nor declared unenforced: {unaccounted}. "
            "Enforce it, or add it to UNENFORCED_IN_ROOT_CI with a measured reason."
        )

    def test_node_only_keys_carry_a_python_equivalence_note(self, policy):
        """A key enforced only on the Node side needs the measured reason there is
        no Python half — otherwise the asymmetry reads as an oversight. Loops
        rather than parametrizes so an empty dict cannot become a skipped test."""
        node_only = sorted((NODE_ENFORCED - PYTHON_ENFORCED) & set(policy["coverage"]))
        assert node_only == sorted(PYTHON_EQUIVALENT_NOTES), (
            "PYTHON_EQUIVALENT_NOTES must name exactly the Node-only enforced keys"
        )
        for key, reason in PYTHON_EQUIVALENT_NOTES.items():
            assert len(reason.strip()) > 80, f"PYTHON_EQUIVALENT_NOTES[{key!r}] needs a real reason"

    def test_declared_gaps_still_exist_in_policy(self, policy):
        """A waiver must not outlive the threshold it excuses."""
        stale = sorted(set(UNENFORCED_IN_ROOT_CI) - set(policy["coverage"]))
        assert not stale, f"UNENFORCED_IN_ROOT_CI names thresholds the policy dropped: {stale}"

    def test_each_declared_gap_carries_a_substantive_reason(self):
        """Loops rather than parametrizes: the dict is empty today, and an empty
        parametrize would register as a skipped test."""
        for key in sorted(UNENFORCED_IN_ROOT_CI):
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
        match = re.search(r"thresholds:\s*\{(.*?)\}", config, re.S)
        assert match is not None, "vitest.config.ts has no thresholds block"
        thresholds = match.group(1)
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


class TestPerFileEnforcement:
    """coverage.per_file is now a live gate: one file below the lines floor must
    turn the run red even when the aggregate is comfortably green."""

    def _report(self, tmp_path, files):
        totals = {
            "covered_lines": sum(f[0] for f in files.values()),
            "num_statements": sum(f[1] for f in files.values()),
            "covered_branches": 90,
            "num_branches": 100,
        }
        payload = {
            "totals": totals,
            "files": {
                path: {"summary": {"covered_lines": cov, "num_statements": num}}
                for path, (cov, num) in files.items()
            },
        }
        report = tmp_path / "coverage.json"
        report.write_text(json.dumps(payload), encoding="utf-8")
        return report

    def _policy(self, tmp_path, per_file=True):
        policy = tmp_path / "policy.json"
        policy.write_text(
            json.dumps({"coverage": {"lines": 90, "branches": 80, "per_file": per_file}}),
            encoding="utf-8",
        )
        return policy

    def test_one_failing_file_fails_the_gate_despite_green_aggregate(self, tmp_path):
        from harness.shared import coverage_gate as cg

        report = self._report(tmp_path, {"big.py": (960, 1000), "thin.py": (10, 20)})
        assert cg.main(["--coverage-json", str(report), "--policy", str(self._policy(tmp_path))]) == 1

    def test_all_files_at_floor_pass(self, tmp_path):
        from harness.shared import coverage_gate as cg

        report = self._report(tmp_path, {"a.py": (95, 100), "b.py": (90, 100), "empty_init.py": (0, 0)})
        assert cg.main(["--coverage-json", str(report), "--policy", str(self._policy(tmp_path))]) == 0

    def test_missing_files_block_fails_closed_when_per_file_declared(self, tmp_path):
        from harness.shared import coverage_gate as cg

        report = tmp_path / "coverage.json"
        report.write_text(
            json.dumps({"totals": {
                "covered_lines": 95, "num_statements": 100,
                "covered_branches": 90, "num_branches": 100,
            }}),
            encoding="utf-8",
        )
        with pytest.raises(SystemExit) as exc:
            cg.main(["--coverage-json", str(report), "--policy", str(self._policy(tmp_path))])
        assert exc.value.code == 1

    def test_per_file_false_keeps_aggregate_only_behavior(self, tmp_path):
        from harness.shared import coverage_gate as cg

        report = self._report(tmp_path, {"big.py": (960, 1000), "thin.py": (10, 20)})
        assert cg.main(
            ["--coverage-json", str(report), "--policy", str(self._policy(tmp_path, per_file=False))]
        ) == 0


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
