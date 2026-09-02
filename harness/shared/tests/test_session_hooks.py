"""The session-wide hooks see every suite, not only harness/shared/tests.

Before R-TDH-26 the skip-evidence hooks lived in harness/shared/tests/conftest.py.
pytest scopes a conftest's per-item hooks to its own directory, so a skip under
harness/api_server/tests produced no row in the evidence file and the Python
zero-skip gate (INV-2, DEC-026) could not see it. The hooks now sit in the
repository-root conftest.py; the tests here pin that placement and reproduce
the original gap with a real pytest run over two sibling suites.
"""

from __future__ import annotations

import pytest

from harness.shared.tests import _session_hooks, _skip_events
from harness.shared.tests._helpers import REPO

pytestmark = pytest.mark.governance

ROOT_CONFTEST = REPO / "conftest.py"
SHARED_CONFTEST = REPO / "harness" / "shared" / "tests" / "conftest.py"
SESSION_HOOKS = (
    "pytest_collection_modifyitems",
    "pytest_report_header",
    "pytest_runtest_logreport",
    "pytest_sessionfinish",
)


class TestPlacement:
    def test_the_root_conftest_registers_every_session_hook(self) -> None:
        source = ROOT_CONFTEST.read_text(encoding="utf-8")
        for hook in SESSION_HOOKS:
            assert f"def {hook}(" in source, f"{hook} is not registered at the rootdir"
        assert "_session_hooks" in source, "the root conftest must delegate to _session_hooks, not fork the logic"

    def test_no_directory_conftest_registers_them_a_second_time(self) -> None:
        """A second registration would record every shared-suite skip twice."""
        for conftest in sorted(REPO.glob("harness/*/tests/conftest.py")):
            source = conftest.read_text(encoding="utf-8")
            for hook in SESSION_HOOKS:
                assert f"def {hook}(" not in source, f"{conftest.relative_to(REPO)} re-registers {hook}"

    def test_the_shared_conftest_still_exports_the_deselect_names(self) -> None:
        from harness.shared.tests import conftest

        assert conftest.LANGGRAPH_DESELECT_ENV == _session_hooks.LANGGRAPH_DESELECT_ENV
        assert conftest.LANGGRAPH_MARKER == _session_hooks.LANGGRAPH_MARKER


class TestSkipEvidenceCoversEverySuite:
    def test_a_skip_in_each_of_two_sibling_suites_is_recorded(
        self, pytester: pytest.Pytester, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The exact shape of the gap: two suites in different directories, one
        skip each. Both rows must land, with rootdir-relative ids."""
        pytester.makeconftest(ROOT_CONFTEST.read_text(encoding="utf-8"))
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
        result = pytester.runpytest_subprocess("-p", "no:cacheprovider", "suite_a", "suite_b")
        result.assert_outcomes(passed=2, skipped=2)
        rows = [line.split("\t") for line in events.read_text(encoding="utf-8").splitlines()]
        assert sorted(row[0] for row in rows) == [
            "suite_a/test_suite_a.py::test_suite_a",
            "suite_b/test_suite_b.py::test_suite_b",
        ]
        assert all("(DEC-026)" in row[2] for row in rows)
        result.stdout.fnmatch_lines(["*skip evidence: 2 skip(s) written to*"])

    def test_record_skip_ignores_passes_and_keeps_skips(self) -> None:
        """Unit view of the same hook: only skip reports become rows."""
        before = len(_session_hooks.SKIP_ROWS)

        class _Report:
            when = "setup"
            skipped = False
            passed = True
            nodeid = "x.py::test_ok"
            longrepr = None

        _session_hooks.record_skip(_Report())  # type: ignore[arg-type]
        assert len(_session_hooks.SKIP_ROWS) == before
