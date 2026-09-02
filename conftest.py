"""Repository-root pytest hooks: the ones that must see every suite.

pytest scopes a conftest's per-item hooks (``pytest_runtest_logreport`` among
them) to the directory the conftest sits in. The skip evidence that
``make verify-zero-skips-python`` reads (INV-2, DEC-026) and the langgraph
deselection for the 3.9 leg (R-TDH-4) therefore have to be registered here,
at the rootdir, or a skip under ``harness/api_server/tests`` or
``harness/control-plane/tests`` goes unrecorded -- which is exactly what
happened while they lived in ``harness/shared/tests/conftest.py``
(tech-debt-hardening-plan R-TDH-26). The logic is in
``harness/shared/tests/_session_hooks.py``; this file only wires it, and
``harness/shared/tests/test_session_hooks.py`` runs it through ``pytester``
to prove a skip in any directory lands in the evidence file.
"""

from __future__ import annotations

import logging
from collections.abc import Iterator

import pytest

from harness.shared.tests import _session_hooks as hooks

# `pytester` is the fixture test_session_hooks.py uses to run a real pytest
# session against a copy of this file. Only a rootdir conftest may declare it.
pytest_plugins = ["pytester"]


@pytest.fixture(autouse=True)
def _isolate_main_logger() -> Iterator[None]:
    """Restore the process-global ``__main__`` logger around every test.

    Gate scripts call ``json_logging.configure_gate_logging(__name__)``, which
    sets ``propagate = False`` and attaches a stderr handler. Under a real
    ``python harness/shared/<gate>.py`` run that name is ``__main__`` and the
    configuration is correct. A test that executes the same gate in-process via
    ``runpy.run_path(..., run_name="__main__")`` gets the identical mutation --
    on the *process-global* ``__main__`` logger, where it outlives the test.

    A later test asserting that its own ``__main__``-logged error reaches a
    patched ``sys.stdout`` then fails, because that logger no longer propagates.
    Reproduced as exactly two tests: ``test_pretooluse_guard.py::
    test_governance_module_main_dispatch_leg`` followed by
    ``test_nemotron_bridge.py::test_running_the_bridge_as_a_script_dispatches_main``.
    The full suite passed only because alphabetical collection happened to put
    them the other way round; reverse file order turned it red.

    Fourteen modules across all three suites run scripts this way, so the
    restore belongs here rather than in any one of them, and it is autouse
    because the coupling is invisible at the point of use. Production behaviour
    is untouched: this only unwinds state a test created.
    """
    logger = logging.getLogger("__main__")
    saved_handlers, saved_propagate, saved_level = logger.handlers[:], logger.propagate, logger.level
    try:
        yield
    finally:
        logger.handlers[:] = saved_handlers
        logger.propagate = saved_propagate
        logger.level = saved_level


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    hooks.deselect_langgraph(config, items)


def pytest_report_header(config: pytest.Config) -> list[str]:
    return hooks.report_header()


def pytest_runtest_logreport(report: pytest.TestReport) -> None:
    hooks.record_skip(report)


def pytest_collectreport(report: pytest.CollectReport) -> None:
    # A module-level importorskip skips at collection time and never produces a
    # TestReport, so without this hook the module vanishes with no evidence row.
    hooks.record_collect_skip(report)


def pytest_sessionfinish(session: pytest.Session, exitstatus: int) -> None:
    hooks.write_skip_evidence(session)
