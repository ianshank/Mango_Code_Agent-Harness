"""Contracts the root Makefile must keep, beyond "the targets exist".

`test_ci_gate_coverage.py` already proves every policy-declared gate is
reachable from `make ci` and that its recipe still does something. This file
covers the contracts added alongside the regression/AQA tier, and the class of
drift where two composite targets are supposed to stay in step and quietly
stop being.

Kept separate from `test_ci_gate_coverage.py` (which is a protected path) so
these checks can evolve without a label round-trip.
"""

from __future__ import annotations

import re

import pytest

from harness.shared.tests._helpers import REPO

MAKEFILE = REPO / "Makefile"
REGRESSION_DIR = REPO / "harness" / "shared" / "tests" / "regression"

pytestmark = pytest.mark.governance


def _text() -> str:
    return MAKEFILE.read_text(encoding="utf-8")


def _targets() -> dict[str, str]:
    """Map target name -> its recipe body (the indented lines beneath it)."""
    targets: dict[str, str] = {}
    current: str | None = None
    lines: list[str] = []
    for line in _text().splitlines():
        match = re.match(r"^([A-Za-z][A-Za-z0-9_-]*):", line)
        if match:
            if current:
                targets[current] = "\n".join(lines)
            current, lines = match.group(1), []
        elif current and (line.startswith(("\t", "    "))):
            lines.append(line)
        elif current and not line.strip():
            continue
        elif current:
            targets[current] = "\n".join(lines)
            current, lines = None, []
    if current:
        targets[current] = "\n".join(lines)
    return targets


def _prerequisites(target: str) -> list[str]:
    match = re.search(rf"^{re.escape(target)}:\s*([^\n#]*)", _text(), re.M)
    return match.group(1).split() if match else []


class TestRegressionTierIsWired:
    def test_the_tier_exists_and_is_populated(self) -> None:
        """Guards every check below: an empty tier would satisfy them all."""
        modules = sorted(REGRESSION_DIR.glob("test_*.py"))
        assert modules, "the regression tier has no test modules"

    def test_make_test_regression_targets_the_tier(self) -> None:
        recipe = _targets().get("test-regression", "")
        assert "regression" in recipe, "make test-regression does not run the regression directory"
        assert 'not live' in recipe, "make test-regression would run the live suites"

    def test_the_tier_is_reachable_from_make_ci(self) -> None:
        """The dedicated target is a convenience. What must not drift is that
        `make ci` still executes these tests -- it does so through
        `test-python`, whose path argument has to keep containing the tier."""
        recipe = _targets().get("test-python", "")
        assert "$(SHARED_TESTS)" in recipe, (
            "test-python no longer runs the shared tests directory, so the regression "
            "tier is not covered by `make ci`"
        )
        relative = REGRESSION_DIR.relative_to(REPO / "harness" / "shared" / "tests")
        assert relative.parts, "the tier moved outside the directory test-python runs"

    def test_coverage_run_also_covers_the_tier(self) -> None:
        assert "$(SHARED_TESTS)" in _targets().get("coverage-python", "")


class TestCompositeTargetsStayInStep:
    def test_pre_pr_still_runs_ci_review_and_the_cold_typecheck(self) -> None:
        assert _prerequisites("pre-pr") == ["ci", "review", "lint-cold", "audit", "secrets"]

    def test_ci_and_ci_python_differ_only_by_the_node_gates(self) -> None:
        """A gate added to `ci` and forgotten in `ci-python` silently stops
        enforcing on the secondary matrix legs, with no signal anywhere.

        `ci-python` arrives with the open gate-hardening PR; until it exists
        there is nothing to compare, so this asserts the invariant the moment
        the target appears rather than failing before it does.
        """
        ci_python = _prerequisites("ci-python")
        if not ci_python:
            pytest.skip("ci-python does not exist on this branch yet")
        difference = set(_prerequisites("ci")) - set(ci_python)
        assert difference == {"test-node", "verify-zero-skips"}, (
            f"ci and ci-python differ by {sorted(difference)}; the only legitimate difference "
            "is the Node-dependent gates, which run once on the primary leg"
        )

    def test_node_deps_is_a_shared_target_using_the_lockfile(self) -> None:
        """One install recipe, so CI, the session hook and a local run cannot
        drift into installing different things."""
        recipe = _targets().get("node-deps", "")
        assert recipe, "make node-deps does not exist"
        assert "--frozen-lockfile" in recipe, (
            "node-deps must install from the lockfile; a resolving install makes CI "
            "non-reproducible"
        )


class TestMakefileSelfConsistency:
    def test_every_phony_declaration_names_a_real_target(self) -> None:
        declared = set(re.findall(r"^\.PHONY:\s*(.+)$", _text(), re.M))
        names = {name for line in declared for name in line.split()}
        defined = set(_targets())
        assert not names - defined, f".PHONY names targets that do not exist: {sorted(names - defined)}"

    def test_test_governance_selects_by_marker_not_by_filename(self) -> None:
        """A hardcoded file list goes stale the moment a governance module is added,
        and reports "governance is green" while skipping most of the suite. It named
        three modules while 23 carried the marker."""
        recipe = _targets().get("test-governance", "")
        assert "-m" in recipe and "governance" in recipe, recipe
        assert ".py" not in recipe, (
            "test-governance names individual files; select by marker so a new governance "
            "module is picked up without editing the Makefile"
        )

    def test_every_target_is_documented(self) -> None:
        """`make help` parses `## ` comments; an undocumented target is
        invisible to anyone who did not write it."""
        undocumented = [
            name for name in _targets()
            if not re.search(rf"^{re.escape(name)}:[^\n]*##", _text(), re.M)
        ]
        assert not undocumented, f"targets missing a `## ` description: {undocumented}"

    def test_review_names_every_skill_claude_md_mandates(self) -> None:
        """CLAUDE.md calls three review skills non-negotiable; `make review`
        printed only two of them, so following the printed checklist skipped
        one of the mandated steps."""
        recipe = _targets().get("review", "")
        for skill in ("openspec-peer-review", "repo-invariant-review", "validation-runner"):
            assert skill in recipe, f"make review does not name the mandated '{skill}' skill"
