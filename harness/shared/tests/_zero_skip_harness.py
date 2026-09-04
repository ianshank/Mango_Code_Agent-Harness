"""Shared harness for the INV-2 zero-skip gate suites.

`test_verify_zero_skips.py` reached 684 lines against a 700-line
`limits.test_size_budget_lines` — sixteen lines of headroom on the suite for the
invariant most likely to need new tests, since every new waiver shape lands
here. Splitting it required a second module, and a second module needed these
two pieces; copying them instead is how the two halves would come to disagree
about what "run the gate" means, which is the divergence `check_dedup.py` exists
to prevent one layer down.

The fixture is imported by name into each suite rather than living in a
`conftest.py`. That is deliberate: a fixture in the directory conftest is
visible to every test module in `harness/shared/tests/`, and `test_files` is a
generic enough name to shadow something later. DEC-030 records what
conftest-scoping errors cost here already.
"""

from __future__ import annotations

import contextlib
import json
import runpy
import subprocess
import sys
from io import StringIO
from pathlib import Path

import pytest


def run_script(project_root: Path, args: list[str]) -> subprocess.CompletedProcess:
    """Execute verify_zero_skips.py in-process via runpy for coverage tracking."""
    old_argv = sys.argv
    try:
        sys.argv = ["verify_zero_skips.py"] + (args or [])
        script = project_root / "harness" / "shared" / "verify_zero_skips.py"

        stdout = StringIO()
        stderr = StringIO()
        returncode = 0

        try:
            with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
                runpy.run_path(str(script), run_name="__main__")
        except SystemExit as e:
            if isinstance(e.code, int):
                returncode = e.code
            elif e.code is None:
                returncode = 0
            else:
                returncode = 1
                stderr.write(str(e.code))
        except Exception as e:  # noqa: BLE001 — intentional catch-all for arbitrary script failures
            returncode = 1
            stderr.write(str(e))

        return subprocess.CompletedProcess(
            args=sys.argv,
            returncode=returncode,
            stdout=stdout.getvalue(),
            stderr=stderr.getvalue(),
        )
    finally:
        sys.argv = old_argv


@pytest.fixture
def test_files(tmp_path: Path):
    d_log = tmp_path / "decision-log.md"
    d_log.write_text("Decision DEC-123\n")

    waivers = tmp_path / "waivers.json"
    waivers.write_text(
        json.dumps(
            {
                "waivers": [
                    {
                        "framework": "vitest",
                        "file": "some.test.ts",
                        "test": "My test",
                        "decision_id": "DEC-123",
                        "reason": "Wait for API",
                        "owner": "test",
                        "expires": "2099-12-31",
                    }
                ]
            }
        )
    )

    v_json = tmp_path / "vitest.json"
    v_json.write_text(json.dumps({"testResults": []}))

    j_events = tmp_path / "junit.events"
    j_events.write_text("")

    return {
        "log": str(d_log),
        "waivers": str(waivers),
        "v_json": str(v_json),
        "j_events": str(j_events),
    }
