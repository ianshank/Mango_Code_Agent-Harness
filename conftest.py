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

import pytest

from harness.shared.tests import _session_hooks as hooks

# `pytester` is the fixture test_session_hooks.py uses to run a real pytest
# session against a copy of this file. Only a rootdir conftest may declare it.
pytest_plugins = ["pytester"]


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    hooks.deselect_langgraph(config, items)


def pytest_report_header(config: pytest.Config) -> list[str]:
    return hooks.report_header()


def pytest_runtest_logreport(report: pytest.TestReport) -> None:
    hooks.record_skip(report)


def pytest_sessionfinish(session: pytest.Session, exitstatus: int) -> None:
    hooks.write_skip_evidence(session)
