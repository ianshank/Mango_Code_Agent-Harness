"""Pin that named defect reproductions stay in the regression tier.

CONTRACT.md defines ``harness/shared/tests/regression/`` as one reproduction per
defect that reached ``main``. NS-11 moved the coverage-gate shadowing probe and
the sibling-suite session-hook pytester run out of the unit tier; this module
lists them so ``make test-regression`` fails if either file is deleted, renamed
away from this directory, or the reproduction is only restored under a unit
path.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from harness.shared.tests._helpers import REPO

pytestmark = pytest.mark.governance

REGRESSION_DIR = Path(__file__).resolve().parent
UNIT_TESTS_DIR = REPO / "harness" / "shared" / "tests"

#: Basename -> a unique token that must appear in that regression module and
#: must not appear as a live unit-tier reproduction of the same defect.
REQUIRED_REGRESSION_MODULES = {
    "test_coverage_gate_shadowing_regression.py": (
        "test_the_gates_own_directory_cannot_shadow_the_extra"
    ),
    "test_session_hooks_skip_evidence_regression.py": (
        "test_a_skip_in_each_of_two_sibling_suites_is_recorded"
    ),
}


@pytest.mark.parametrize("basename", sorted(REQUIRED_REGRESSION_MODULES))
def test_required_reproduction_lives_in_the_regression_tier(basename: str) -> None:
    path = REGRESSION_DIR / basename
    assert path.is_file(), (
        f"{basename} is missing from harness/shared/tests/regression/; "
        "CONTRACT.md requires one standalone reproduction per defect that reached main"
    )
    token = REQUIRED_REGRESSION_MODULES[basename]
    source = path.read_text(encoding="utf-8")
    assert token in source, f"{basename} no longer defines {token}"


@pytest.mark.parametrize("basename", sorted(REQUIRED_REGRESSION_MODULES))
def test_required_reproduction_is_not_only_under_the_unit_tier(basename: str) -> None:
    """A move back into unit/ alone must fail: the tier's guarantee is the path."""
    token = REQUIRED_REGRESSION_MODULES[basename]
    unit_hits = sorted(
        path
        for path in UNIT_TESTS_DIR.glob("test_*.py")
        if token in path.read_text(encoding="utf-8")
    )
    regression_path = REGRESSION_DIR / basename
    assert regression_path.is_file(), (
        f"{basename} is absent from regression/; cannot judge unit-only drift"
    )
    assert not unit_hits, (
        f"{token} reappeared only under the unit tier at "
        f"{[p.relative_to(REPO).as_posix() for p in unit_hits]}; keep the "
        "reproduction in harness/shared/tests/regression/"
    )
