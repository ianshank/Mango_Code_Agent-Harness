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

# Thresholds the *Python* aggregate gate applies.
PYTHON_ENFORCED = {"lines"}

# Declared thresholds with no enforcement in the root pipeline. Each needs a
# measured reason: these are the numbers that turn CI red if enabled today, so a
# future change can weigh the cost instead of rediscovering it.
UNENFORCED_IN_ROOT_CI = {
    "per_file": (
        "The Python gate is aggregate-only (--cov-fail-under). Measured at the "
        "policy's lines=90, six measured files fail per-file today: "
        "pretooluse_guard.py (75%), remotes.py (75%), publish_policy_artifact.py "
        "(77.85%), validate_adoption.py (85.71%), verify_zero_skips.py (87.5%), "
        "governance/pretooluse_guard.py (87.58%). Aggregate headroom is ~60 "
        "statements, so a new untested module can ship green. Tracked in "
        "harness/CONTRACT.md as a documented follow-up."
    ),
    "statements": (
        "Python: coverage.py reports statements but the gate applies only lines. "
        "Node: enforced by vitest.config.ts, which `make test-node` never "
        "activates because it runs without --coverage."
    ),
    "functions": (
        "No Python equivalent is applied. Node enforces it only under --coverage, "
        "which root CI does not pass; measured, circuit-breaker.ts (85.71%) and "
        "web/app.ts (58.33%) would fail."
    ),
    "branches": (
        "pyproject declares no `branch = true`, so branch coverage is not even "
        "measured on the Python side. Node would fail nemotron-client.ts (70.42%), "
        "web/app.ts (31.57%) and terminal-renderer.ts (61.11%) at the policy's 80."
    ),
}


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
    def test_cov_min_has_no_permissive_fallback(self, makefile):
        """Governance fails closed everywhere else; this gate used to *lower itself*
        to 80 when it could not read the policy that says 90."""
        line = re.search(r"^COV_MIN\s*\?=\s*(.+)$", makefile, re.M)
        assert line, "root Makefile does not define COV_MIN"
        assert not re.search(r"\|\|\s*echo\s*\d+", line.group(1)), (
            "COV_MIN falls back to a literal when the policy is unreadable; an "
            "unreadable policy must fail the gate, not weaken it"
        )

    def test_coverage_target_aborts_when_the_threshold_is_unresolved(self, makefile):
        recipe = re.search(r"^coverage-python:.*?\n((?:\t[^\n]*\n)+)", makefile, re.M)
        assert recipe, "root Makefile has no coverage-python recipe"
        assert re.search(r'test\s+-n\s+"?\$\(COV_MIN\)"?', recipe.group(1)), (
            "coverage-python does not guard against an empty COV_MIN, so an "
            "unreadable policy would run pytest with no threshold at all"
        )


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
