"""Skip evidence for the Python half of INV-2 (zero unapproved skips).

The Node stack proves "no unapproved skip" from Vitest's JSON report. Python
had no equivalent: a skipped test was a line in a summary nobody gated, which is
how 36 langgraph cases and four empty-parametrize skips ran unaccounted on every
CI leg (tech-debt-hardening-plan R-TDH-19).

``conftest.py`` calls :func:`skip_event` from ``pytest_runtest_logreport`` and
:func:`write_events` from ``pytest_sessionfinish``; the file it writes is the
TSV ``verify_zero_skips.py --junit-events`` already consumes
(``unique_id \\t display \\t reason``), so the existing gate needs no new format
and no new dependency. ``make verify-zero-skips-python`` reads it against
``harness/shared/tests/skip-waivers.json``; a skip whose reason does not carry
the waiver's ``DEC-`` id is unapproved, exactly as for Vitest.

Kept free of pytest hooks so the two functions are unit-testable with plain
objects (``test_skip_events.py``); the hooks themselves are three lines each.
"""

from __future__ import annotations

import os
from collections.abc import Iterable
from pathlib import Path
from typing import Any

#: Environment override for the events file; the default lives beside the
#: suite so no root-level ``.governance/`` directory is needed (DEC-005 keeps
#: that dormant; tech-debt-hardening-plan open question 6).
SKIP_EVENTS_ENV = "MANGO_PYTEST_SKIP_EVENTS"
DEFAULT_SKIP_EVENTS = Path(__file__).resolve().parent / ".artifacts" / "pytest-skips.tsv"

_SKIPPED_PREFIX = "Skipped: "


def events_path() -> Path:
    override = os.environ.get(SKIP_EVENTS_ENV)
    return Path(override) if override else DEFAULT_SKIP_EVENTS


def skip_reason(longrepr: Any) -> str:
    """The human reason out of a skip report's ``longrepr``.

    pytest records a skip as ``(path, lineno, "Skipped: <reason>")``; anything
    else (a string, an xfail wrapper) is rendered as text. The ``Skipped: ``
    prefix is dropped so the waiver gate matches the reason the author wrote.
    """
    if isinstance(longrepr, tuple) and len(longrepr) == 3:
        message = str(longrepr[2])
    else:
        message = str(longrepr)
    message = message.strip()
    if message.startswith(_SKIPPED_PREFIX):
        message = message[len(_SKIPPED_PREFIX) :]
    return message.replace("\t", " ").replace("\n", " ").strip()


def skip_event(report: Any) -> tuple[str, str, str] | None:
    """``(unique_id, display, reason)`` for a skipped test report, else None.

    Only the ``call`` and ``setup`` phases carry a skip (a ``skipif`` marker
    skips at setup; ``pytest.skip()`` inside the body skips at call). An
    ``xfail`` outcome is *not* a skip and is not recorded; CLAUDE.md forbids
    xfail without a decision entry, which ``test_test_quality.py`` polices.
    """
    if not getattr(report, "skipped", False):
        return None
    if getattr(report, "when", "call") not in ("setup", "call"):
        return None
    if hasattr(report, "wasxfail"):
        return None
    nodeid = str(report.nodeid)
    display = nodeid.rsplit("::", 1)[-1]
    return nodeid, display, skip_reason(getattr(report, "longrepr", ""))


def collect_skip_event(report: Any) -> tuple[str, str, str] | None:
    """``(unique_id, display, reason)`` for a skipped *collection* report, else None.

    A module-level ``pytest.importorskip`` or ``pytest.skip(allow_module_level=True)``
    skips during collection, which pytest reports as a ``CollectReport`` (``when ==
    "collect"``) and never as the ``TestReport`` :func:`skip_event` reads. The whole
    module — sometimes a whole directory, when it is a conftest that skips — then
    disappears with no evidence row at all, and ``verify_zero_skips.py`` reads an
    empty file and prints ``passed``.

    That is the DEC-030 failure mode one layer up: there the hooks saw only one of
    three suites, here they see only one of two report types. Four live sites skip
    at collection today, including ``test_egress_floor.py`` — the suite that proves
    the egress floor is armed, whose silent disappearance is exactly what the gate
    exists to prevent.
    """
    if not getattr(report, "skipped", False):
        return None
    if getattr(report, "when", None) != "collect":
        return None
    nodeid = str(report.nodeid)
    # A collection nodeid is a path, not a ``::``-addressed test; the basename is
    # the useful display half, and the waiver registry matches on the full id.
    display = nodeid.rsplit("/", 1)[-1] or nodeid
    return nodeid, display, skip_reason(getattr(report, "longrepr", ""))


def write_events(path: Path, rows: Iterable[tuple[str, str, str]]) -> int:
    """Write the TSV (one skip per line), creating the directory; returns the row count."""
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [f"{unique_id}\t{display}\t{reason}" for unique_id, display, reason in rows]
    path.write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")
    return len(lines)
