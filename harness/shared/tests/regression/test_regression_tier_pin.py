"""Pin that named defect reproductions stay in the regression tier.

CONTRACT.md defines ``harness/shared/tests/regression/`` as one reproduction per
defect that reached ``main``. NS-11 moved the coverage-gate shadowing probe and
the sibling-suite session-hook pytester run out of the unit tier; this module
lists them so ``make test-regression`` fails if either file is deleted, renamed
away from this directory, or the reproduction function is defined anywhere
under the unit suite.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from harness.shared.tests._helpers import REPO

pytestmark = pytest.mark.governance

REGRESSION_DIR = Path(__file__).resolve().parent
UNIT_TESTS_DIR = REPO / "harness" / "shared" / "tests"

#: Basename -> reproduction function name that must be *defined* in that
#: regression module (not merely mentioned in a comment/string) and must not
#: be defined anywhere under the unit suite.
REQUIRED_REGRESSION_MODULES = {
    "test_coverage_gate_shadowing_regression.py": "test_the_gates_own_directory_cannot_shadow_the_extra",
    "test_session_hooks_skip_evidence_regression.py": "test_a_skip_in_each_of_two_sibling_suites_is_recorded",
}


def _defines_function(source: str, name: str) -> bool:
    """True when ``source`` contains a ``def`` / ``async def`` named ``name``."""
    tree = ast.parse(source)
    return any(
        isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name for node in ast.walk(tree)
    )


@pytest.mark.parametrize("basename", sorted(REQUIRED_REGRESSION_MODULES))
def test_required_reproduction_lives_in_the_regression_tier(basename: str) -> None:
    path = REGRESSION_DIR / basename
    assert path.is_file(), (
        f"{basename} is missing from harness/shared/tests/regression/; "
        "CONTRACT.md requires one standalone reproduction per defect that reached main"
    )
    name = REQUIRED_REGRESSION_MODULES[basename]
    source = path.read_text(encoding="utf-8")
    assert _defines_function(source, name), (
        f"{basename} no longer defines function {name} (comment/string mentions do not count)"
    )


@pytest.mark.parametrize("basename", sorted(REQUIRED_REGRESSION_MODULES))
def test_required_reproduction_is_not_defined_under_the_unit_tier(basename: str) -> None:
    """A definition under the unit suite must fail even if regression/ still has a copy."""
    name = REQUIRED_REGRESSION_MODULES[basename]
    unit_hits = sorted(
        path for path in UNIT_TESTS_DIR.glob("test_*.py") if _defines_function(path.read_text(encoding="utf-8"), name)
    )
    regression_path = REGRESSION_DIR / basename
    assert regression_path.is_file(), f"{basename} is absent from regression/; cannot judge unit-suite drift"
    assert not unit_hits, (
        f"{name} is defined under the unit suite at "
        f"{[p.relative_to(REPO).as_posix() for p in unit_hits]}; keep the "
        "reproduction in harness/shared/tests/regression/"
    )
