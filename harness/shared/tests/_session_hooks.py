"""Session-wide pytest hook logic: langgraph deselection and skip evidence.

Wired by the repository-root ``conftest.py``, which is the only place a hook can
sit and still see every suite: pytest scopes a conftest's per-item hooks
(``pytest_runtest_logreport`` among them) to the directory that conftest lives
in, so while these lived in ``harness/shared/tests/conftest.py`` a skip under
``harness/api_server/tests`` was never written to the evidence file the Python
zero-skip gate reads (found while colocating ``harness/control-plane/tests``,
tech-debt-hardening-plan R-TDH-26; the gap dates from R-TDH-19). The logic is a
plain module so ``test_session_hooks.py`` can exercise it directly and through a
``pytester`` run of the real root conftest.

Two concerns live here on purpose, because they share one fact: the name of the
variable a CI leg sets when it cannot install an optional extra. It comes from
``coverage.optional_extras`` in the governance policy, which ``coverage_gate.py``
reads for the matching per-file waiver, so the deselect signal and the waiver
cannot drift apart (DEC-028).
"""

from __future__ import annotations

import os

import pytest

from harness.shared.langgraph import LANGGRAPH_AVAILABLE
from harness.shared.policy_loader import coverage_optional_extras
from harness.shared.tests import _skip_events

# CI legs whose interpreter cannot install langgraph (it declares
# Requires-Python >=3.10) set this to "1". The `langgraph`-marked suites are
# then *deselected* -- reported in pytest's summary line, never counted as a
# skip -- instead of tripping their skipif guards, which is what INV-2's
# zero-skip posture requires. Every other leg installs the library and runs
# them; test_workflow_contracts.py pins that wiring. Local runs without the
# library keep the skipif behaviour, so a developer sees what did not run.
LANGGRAPH_MARKER = "langgraph"

#: Used when the policy declares no ``langgraph`` optional extra. The policy is the
#: source of truth when it speaks; an adopter fork that trims the block must still be
#: able to *collect* a test suite, so a missing key falls back here instead of raising
#: ``KeyError`` out of a module-level index during conftest import — which would kill
#: the session before pytest could report a reason. Malformed still fails closed:
#: ``coverage_optional_extras`` raises ``PolicyError`` for a block it cannot parse.
_FALLBACK_DESELECT_ENV = "MANGO_CI_DESELECT_LANGGRAPH"


def _resolve_deselect_env() -> str:
    extra = coverage_optional_extras().get(LANGGRAPH_MARKER)
    if extra is None:
        return _FALLBACK_DESELECT_ENV
    return str(extra["deselect_env"])


LANGGRAPH_DESELECT_ENV: str = _resolve_deselect_env()

_LANGGRAPH_DESELECTED_KEY = pytest.StashKey[int]()

#: Every skip this session produced, as `(unique_id, display, reason)`; written
#: at session end to the file `make verify-zero-skips-python` reads.
SKIP_ROWS: list[tuple[str, str, str]] = []


def langgraph_deselection_requested() -> bool:
    return os.environ.get(LANGGRAPH_DESELECT_ENV) == "1" and not LANGGRAPH_AVAILABLE


def deselect_langgraph(config: pytest.Config, items: list[pytest.Item]) -> None:
    """Deselect ``langgraph``-marked tests on legs that opted in and lack the library."""
    if not langgraph_deselection_requested():
        return
    deselected = [item for item in items if item.get_closest_marker(LANGGRAPH_MARKER) is not None]
    if not deselected:
        return
    config.hook.pytest_deselected(items=deselected)
    items[:] = [item for item in items if item.get_closest_marker(LANGGRAPH_MARKER) is None]
    config.stash.setdefault(_LANGGRAPH_DESELECTED_KEY, len(deselected))


def report_header() -> list[str]:
    """Make the deselection visible in the run header, not only in the tally."""
    if not langgraph_deselection_requested():
        return []
    return [
        (
            f"langgraph: not installed and {LANGGRAPH_DESELECT_ENV}=1; "
            f"tests marked '{LANGGRAPH_MARKER}' are deselected on this leg"
        )
    ]


def record_skip(report: pytest.TestReport) -> None:
    event = _skip_events.skip_event(report)
    if event is not None:
        SKIP_ROWS.append(event)


def record_collect_skip(report: pytest.CollectReport) -> None:
    """Record a skip that happened during collection (see ``collect_skip_event``)."""
    event = _skip_events.collect_skip_event(report)
    if event is not None:
        SKIP_ROWS.append(event)


def is_xdist_worker(config: pytest.Config) -> bool:
    """True inside a pytest-xdist worker process; xdist stamps `workerinput` on its config."""
    return hasattr(config, "workerinput")


def write_skip_evidence(session: pytest.Session) -> None:
    # Under xdist every worker forwards its runtime and collection reports to
    # the controller, so the controller's SKIP_ROWS is the complete set and the
    # controller's session end is the last to run. A worker writing its partial
    # set to the same path would only ever be overwritten -- unless the ordering
    # ever changed, at which point the gate would read a fragment and pass on it.
    # Writing from the controller alone removes that dependence on ordering.
    if is_xdist_worker(session.config):
        return
    path = _skip_events.events_path()
    count = _skip_events.write_events(path, SKIP_ROWS)
    reporter = session.config.pluginmanager.get_plugin("terminalreporter")
    if reporter is not None and count:
        reporter.write_line(f"skip evidence: {count} skip(s) written to {path} for verify-zero-skips-python")
