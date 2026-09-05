"""The session-wide hooks see every suite, not only harness/shared/tests.

Before R-TDH-26 the skip-evidence hooks lived in harness/shared/tests/conftest.py.
pytest scopes a conftest's per-item hooks to its own directory, so a skip under
harness/api_server/tests produced no row in the evidence file and the Python
zero-skip gate (INV-2, DEC-026) could not see it. The hooks now sit in the
repository-root conftest.py; the tests here pin that placement. The end-to-end
sibling-suite reproduction lives in
``harness/shared/tests/regression/test_session_hooks_skip_evidence_regression.py`` (NS-11).
"""

from __future__ import annotations

import logging
from pathlib import Path

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
    # A module-level importorskip skips at collection and produces only a
    # CollectReport, so the evidence gate needs this hook too.
    "pytest_collectreport",
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


class TestCollectionTimeSkipsAreRecorded:
    """A module-level ``importorskip`` skips during *collection*.

    pytest reports that as a ``CollectReport``, never as the ``TestReport`` the
    evidence hook originally read, so the module — sometimes a whole directory,
    when it is a conftest that skips — disappeared with no row and the gate that
    exists to notice skips printed ``passed``. Same failure shape as DEC-030 one
    layer up: there the hooks saw one of three suites, here one of two report
    types. Four live sites skip at collection, including ``test_egress_floor.py``,
    whose silent disappearance would remove the proof that the egress floor is armed.
    """

    def test_a_module_level_importorskip_writes_an_evidence_row(
        self, pytester: pytest.Pytester, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        pytester.makeconftest(ROOT_CONFTEST.read_text(encoding="utf-8"))
        pytester.makepyfile(
            test_collect_skip=(
                "import pytest\n"
                "pytest.importorskip('a_module_that_does_not_exist_xyz')\n"
                "def test_never_runs(): assert True\n"
            )
        )
        events = pytester.path / "skips.tsv"
        monkeypatch.setenv(_skip_events.SKIP_EVENTS_ENV, str(events))
        monkeypatch.setenv("PYTHONPATH", str(REPO))
        monkeypatch.setenv("PYTEST_DISABLE_PLUGIN_AUTOLOAD", "1")
        result = pytester.runpytest_subprocess("-p", "no:cacheprovider", ".")
        result.assert_outcomes(skipped=1)
        rows = [line.split("\t") for line in events.read_text(encoding="utf-8").splitlines()]
        assert [row[0] for row in rows] == ["test_collect_skip.py"], (
            "a collection-time skip left no evidence row; verify-zero-skips-python would pass vacuously"
        )
        assert "a_module_that_does_not_exist_xyz" in rows[0][2]

    def test_a_successful_collection_writes_nothing(self) -> None:
        """The control: only a *skipped* collect report becomes a row."""

        class _Report:
            when = "collect"
            skipped = False
            nodeid = "test_ok.py"
            longrepr = None

        assert _skip_events.collect_skip_event(_Report()) is None  # type: ignore[arg-type]

    def test_a_runtest_report_is_not_taken_as_a_collect_skip(self) -> None:
        """`when` discriminates the two report types; a setup skip belongs to the other hook."""

        class _Report:
            when = "setup"
            skipped = True
            nodeid = "test_x.py::test_y"
            longrepr = ("test_x.py", 1, "Skipped: because")

        assert _skip_events.collect_skip_event(_Report()) is None  # type: ignore[arg-type]


class TestLanggraphDeselection:
    """R-TDH-4's mechanism had no test at all, and is invisible to the coverage
    gate because ``harness/shared/tests/*`` is omitted from measurement (the
    function measured 73% with its whole body uncovered). If it silently stopped
    deselecting, the 3.9 leg would return to ~36 unaccounted skips and the only
    thing left to notice would be the evidence gate written in the same module.

    Driven directly rather than through ``pytester``: the deselection is
    conditional on langgraph genuinely being absent, so a subprocess test asserts
    something different depending on what the runner happens to have installed.
    """

    class _Item:
        def __init__(self, nodeid: str, marked: bool) -> None:
            self.nodeid, self._marked = nodeid, marked

        def get_closest_marker(self, name: str) -> object | None:
            return object() if (self._marked and name == _session_hooks.LANGGRAPH_MARKER) else None

    class _Hook:
        def __init__(self) -> None:
            self.deselected: list[TestLanggraphDeselection._Item] = []

        def pytest_deselected(self, items: list[TestLanggraphDeselection._Item]) -> None:
            self.deselected.extend(items)

    class _Config:
        def __init__(self) -> None:
            self.hook = TestLanggraphDeselection._Hook()
            self.stash: dict[object, object] = {}

    def _items(self) -> list[TestLanggraphDeselection._Item]:
        return [self._Item("test_marked.py::test_a", True), self._Item("test_plain.py::test_b", False)]

    def test_marked_items_are_deselected_when_the_extra_is_absent(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(_session_hooks, "LANGGRAPH_AVAILABLE", False)
        monkeypatch.setenv(_session_hooks.LANGGRAPH_DESELECT_ENV, "1")
        config, items = self._Config(), self._items()
        _session_hooks.deselect_langgraph(config, items)  # type: ignore[arg-type]
        assert [i.nodeid for i in items] == ["test_plain.py::test_b"], "the marked item was not removed"
        assert [i.nodeid for i in config.hook.deselected] == ["test_marked.py::test_a"], (
            "pytest was not told about the deselection, so it would not appear in the summary"
        )

    def test_nothing_is_deselected_when_the_extra_is_installed(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """A leg that HAS langgraph must keep running the suites, env or no env."""
        monkeypatch.setattr(_session_hooks, "LANGGRAPH_AVAILABLE", True)
        monkeypatch.setenv(_session_hooks.LANGGRAPH_DESELECT_ENV, "1")
        config, items = self._Config(), self._items()
        _session_hooks.deselect_langgraph(config, items)  # type: ignore[arg-type]
        assert len(items) == 2 and config.hook.deselected == []

    def test_nothing_is_deselected_when_the_env_is_unset(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(_session_hooks, "LANGGRAPH_AVAILABLE", False)
        monkeypatch.delenv(_session_hooks.LANGGRAPH_DESELECT_ENV, raising=False)
        config, items = self._Config(), self._items()
        _session_hooks.deselect_langgraph(config, items)  # type: ignore[arg-type]
        assert len(items) == 2 and config.hook.deselected == []

    def test_the_run_header_announces_the_deselection(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Silent deselection reads as "those tests do not exist"; the header is
        the only place a reader learns the leg ran a reduced suite."""
        monkeypatch.setattr(_session_hooks, "LANGGRAPH_AVAILABLE", False)
        monkeypatch.setenv(_session_hooks.LANGGRAPH_DESELECT_ENV, "1")
        header = _session_hooks.report_header()
        assert header and _session_hooks.LANGGRAPH_MARKER in header[0]
        monkeypatch.setattr(_session_hooks, "LANGGRAPH_AVAILABLE", True)
        assert _session_hooks.report_header() == []


class TestDeselectEnvResolution:
    """The env name comes from the policy, but a trimmed policy must not kill collection."""

    def test_the_shipped_policy_supplies_the_name(self) -> None:
        assert _session_hooks.LANGGRAPH_DESELECT_ENV == "MANGO_CI_DESELECT_LANGGRAPH"

    def test_a_policy_without_the_extra_falls_back_instead_of_raising(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Indexing the extras dict unguarded raised ``KeyError`` out of a
        module-level statement reached from the root conftest, so an adopter fork
        that trimmed the block could not collect any suite at all — and got no
        reason, because the failure happened before pytest could report one."""
        monkeypatch.setattr(_session_hooks, "coverage_optional_extras", dict)
        assert _session_hooks._resolve_deselect_env() == _session_hooks._FALLBACK_DESELECT_ENV


class TestMainLoggerIsolation:
    """A gate run in-process under ``runpy`` must not leak its logging config.

    ``json_logging.configure_gate_logging(__name__)`` sets ``propagate = False``
    and attaches a handler. Under ``runpy.run_path(..., run_name="__main__")``
    that lands on the *process-global* ``__main__`` logger and outlived the test,
    so a later test asserting its own ``__main__`` error reached a patched stdout
    failed — purely from collection order. Fourteen modules across the three
    suites run scripts this way; the full suite was green only because
    alphabetical order happened to be favourable, and reverse file order was red.
    """

    def test_a_gate_run_under_runpy_leaves_the_main_logger_as_it_found_it(self) -> None:
        main = logging.getLogger("__main__")
        assert main.propagate is True, (
            "the __main__ logger arrived at this test already reconfigured; the autouse "
            "fixture in the repository-root conftest.py is not restoring it"
        )
        assert not any(getattr(h, "_mango_gate_handler", False) for h in main.handlers)

    def test_the_fixture_restores_a_mutation_this_test_makes(self) -> None:
        """Directly exercise the restore, so the guarantee is not merely observed."""
        main = logging.getLogger("__main__")
        main.propagate = False
        main.addHandler(logging.NullHandler())
        # The autouse fixture unwinds both on teardown; the sibling test above is
        # what observes it, and pytest runs them in the order written.
        assert main.propagate is False


class TestEvidenceIsCompleteAndWrittenOnceUnderXdist:
    """`make coverage-python` runs under `-n auto` (audit H8), and that run is
    also the one INV-2 reads. Measured before enabling it: xdist forwards both
    runtime and collection-time skip reports to the controller. The subprocess
    test below is that measurement, kept as a gate; the unit test pins that only
    the controller writes, so the file's contents never depend on which process
    happened to finish last.
    """

    def test_both_kinds_of_skip_reach_the_evidence_file_under_two_workers(
        self, pytester: pytest.Pytester, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        pytester.makeconftest(ROOT_CONFTEST.read_text(encoding="utf-8"))
        pytester.makepyfile(
            test_collect_skip=(
                "import pytest\n"
                "pytest.importorskip('a_module_that_does_not_exist_xyz')\n"
                "def test_never_runs(): assert True\n"
            ),
            test_runtime=(
                "import pytest\n"
                "@pytest.mark.skip(reason='runtime (DEC-026)')\n"
                "def test_runtime_skip(): ...\n"
                "def test_ok(): assert True\n"
                "def test_ok2(): assert True\n"
            ),
        )
        events = pytester.path / "skips.tsv"
        monkeypatch.setenv(_skip_events.SKIP_EVENTS_ENV, str(events))
        monkeypatch.setenv("PYTHONPATH", str(REPO))
        monkeypatch.setenv("PYTEST_DISABLE_PLUGIN_AUTOLOAD", "1")
        result = pytester.runpytest_subprocess("-p", "no:cacheprovider", "-p", "xdist", "-n", "2", ".")
        result.assert_outcomes(passed=2, skipped=2)
        rows = [line.split("\t") for line in events.read_text(encoding="utf-8").splitlines()]
        assert sorted(row[0] for row in rows) == ["test_collect_skip.py", "test_runtime.py::test_runtime_skip"], (
            "a skip produced on an xdist worker left no evidence row on the controller"
        )

    def test_a_worker_session_writes_nothing(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        events = tmp_path / "skips.tsv"
        monkeypatch.setenv(_skip_events.SKIP_EVENTS_ENV, str(events))

        class _Config:
            workerinput = {"workerid": "gw0"}

        class _Session:
            config = _Config()

        _session_hooks.write_skip_evidence(_Session())  # type: ignore[arg-type]
        assert not events.exists(), "an xdist worker wrote a partial evidence file"

    def test_the_controller_is_not_mistaken_for_a_worker(self) -> None:
        """The control: a config without `workerinput` is the process that writes."""

        class _Config:
            pass

        assert _session_hooks.is_xdist_worker(_Config()) is False  # type: ignore[arg-type]
