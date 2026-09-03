"""`unique_id_glob` waivers for the JUnit half of the INV-2 gate (DEC-026, R-TDH-19).

Split out of `test_verify_zero_skips.py` at the section banner that module had
already drawn around this block. The trigger was mechanical — 684 lines against
a 700-line budget — but the seam is not: a glob waiver widens *which node ids a
waiver addresses* while leaving *what it approves* untouched, and that
distinction is what DEC-026 and the waiver narrowing both turned on. Every case
here is about the address.

The gate runner and its fixture come from `_zero_skip_harness` so both halves
exercise the same invocation; a copied runner is how they would drift.
"""

from __future__ import annotations

import json
from pathlib import Path

from harness.shared.tests._zero_skip_harness import run_script, test_files

# `test_files` is imported for pytest to resolve as a fixture in this module, not
# called directly; ruff cannot see that use, hence the explicit re-export.
__all__ = ["run_script", "test_files"]


def _glob_registry(test_files, glob: str = "harness/shared/tests/test_langgraph_*.py::*", test: str = "*") -> None:
    Path(test_files["waivers"]).write_text(
        json.dumps(
            {
                "waivers": [
                    {
                        "framework": "junit",
                        "unique_id_glob": glob,
                        "test": test,
                        "decision_id": "DEC-123",
                        "reason": "langgraph not installable below 3.10",
                        "owner": "a",
                        "expires": "2099-12-31",
                    }
                ],
            }
        )
    )


def _run_junit(test_files):
    args = ["--decision-log", test_files["log"], "--waivers", test_files["waivers"]]
    return run_script(Path("."), [*args, "--junit-events", test_files["j_events"]])


def test_junit_glob_waiver_covers_every_matching_nodeid(test_files):
    _glob_registry(test_files)
    reason = "langgraph not installed (DEC-123)"
    Path(test_files["j_events"]).write_text(
        f"harness/shared/tests/test_langgraph_graph.py::TestLive::test_a[x]\ttest_a[x]\t{reason}\n"
        f"harness/shared/tests/test_langgraph_state.py::test_b\ttest_b\t{reason}\n"
    )
    assert _run_junit(test_files).returncode == 0


def test_junit_glob_waiver_still_requires_the_decision_id_in_the_reason(test_files):
    _glob_registry(test_files)
    Path(test_files["j_events"]).write_text(
        "harness/shared/tests/test_langgraph_graph.py::test_a\ttest_a\tlanggraph not installed\n"
    )
    res = _run_junit(test_files)
    assert res.returncode != 0 and "unapproved JUnit skip" in res.stderr


def test_junit_glob_waiver_does_not_reach_other_paths(test_files):
    _glob_registry(test_files)
    Path(test_files["j_events"]).write_text("harness/shared/tests/test_other.py::test_c\ttest_c\tskip (DEC-123)\n")
    res = _run_junit(test_files)
    assert res.returncode != 0 and "test_other.py" in res.stderr


def test_junit_glob_waiver_can_pin_the_test_name(test_files):
    _glob_registry(test_files, glob="harness/shared/tests/test_mcp_server.py::*", test="test_real_*")
    Path(test_files["j_events"]).write_text(
        "harness/shared/tests/test_mcp_server.py::test_real_tool\ttest_real_tool\tmcp absent (DEC-123)\n"
        "harness/shared/tests/test_mcp_server.py::test_other\ttest_other\tmcp absent (DEC-123)\n"
    )
    res = _run_junit(test_files)
    assert res.returncode != 0 and "test_other" in res.stderr


def test_junit_waiver_with_both_exact_and_glob_is_malformed(test_files):
    Path(test_files["waivers"]).write_text(
        json.dumps(
            {
                "waivers": [
                    {
                        "framework": "junit",
                        "unique_id": "id1",
                        "unique_id_glob": "id*",
                        "test": "t",
                        "decision_id": "DEC-123",
                        "reason": "a",
                        "owner": "a",
                        "expires": "2099-12-31",
                    }
                ],
            }
        )
    )
    Path(test_files["j_events"]).write_text("")
    res = _run_junit(test_files)
    assert res.returncode != 0 and "exactly one of unique_id / unique_id_glob" in res.stderr
