"""Skip-evidence hooks must see every suite, not only harness/shared/tests.

Defect reproduced here (present on ``main`` before the fix, DEC-030 / R-TDH-26):

Before the move, the skip-evidence hooks lived in
``harness/shared/tests/conftest.py``. pytest scopes a conftest's per-item hooks
to its own directory, so a skip under ``harness/api_server/tests`` produced no
row in the evidence file and the Python zero-skip gate (INV-2, DEC-026) could
not see it. The hooks now sit in the repository-root ``conftest.py``.

This module keeps the end-to-end reproduction: a real pytest run over two
sibling suites must write one evidence row per skip with rootdir-relative ids.
"""

from __future__ import annotations

import pytest

from harness.shared.tests import _skip_events
from harness.shared.tests._helpers import REPO

pytestmark = pytest.mark.governance

ROOT_CONFTEST = REPO / "conftest.py"


def test_a_skip_in_each_of_two_sibling_suites_is_recorded(
    pytester: pytest.Pytester, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The exact shape of the gap: two suites in different directories, one
    skip each. Both rows must land, with rootdir-relative ids."""
    pytester.makeconftest(ROOT_CONFTEST.read_text(encoding="utf-8"))
    # Anchor rootdir here so skip node ids stay suite-relative even when
    # an ancestor directory has a pyproject.toml.
    pytester.makepyprojecttoml("[tool.pytest.ini_options]\n")
    for suite in ("suite_a", "suite_b"):
        (pytester.path / suite).mkdir()
        pytester.makepyfile(
            **{
                f"{suite}/test_{suite}": (
                    "import pytest\n"
                    f"@pytest.mark.skip(reason='{suite} (DEC-026)')\n"
                    f"def test_{suite}(): ...\n"
                    f"def test_{suite}_runs(): assert True\n"
                )
            }
        )
    events = pytester.path / "skips.tsv"
    monkeypatch.setenv(_skip_events.SKIP_EVENTS_ENV, str(events))
    monkeypatch.setenv("PYTHONPATH", str(REPO))
    # The child needs no entry-point plugin: the hooks under test come from the
    # copied root conftest. Autoloading them would tie this test to whatever a
    # machine happens to have installed (pytester also moves HOME, which hides
    # user-site packages an autoloaded plugin may import).
    monkeypatch.setenv("PYTEST_DISABLE_PLUGIN_AUTOLOAD", "1")
    # Clear inherited addopts (socket plugins) so the child only needs the
    # hooks under test — the reproduction is about skip evidence, not egress.
    result = pytester.runpytest_subprocess(
        "-p",
        "no:cacheprovider",
        "-o",
        "addopts=",
        "suite_a",
        "suite_b",
    )
    result.assert_outcomes(passed=2, skipped=2)
    rows = [line.split("\t") for line in events.read_text(encoding="utf-8").splitlines()]
    assert sorted(row[0] for row in rows) == [
        "suite_a/test_suite_a.py::test_suite_a",
        "suite_b/test_suite_b.py::test_suite_b",
    ]
    assert all("(DEC-026)" in row[2] for row in rows)
    result.stdout.fnmatch_lines(["*skip evidence: 2 skip(s) written to*"])
