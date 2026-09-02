"""`_skip_events.py`: the pytest-side producer of the Python zero-skip evidence.

The hooks in the repository-root `conftest.py` (via `_session_hooks.py`) are one
line each and call these two functions;
this is where their behaviour is pinned with plain objects, no pytester run
needed (tech-debt-hardening-plan R-TDH-19, DEC-026).
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from harness.shared.tests import _skip_events

pytestmark = pytest.mark.governance


def _report(**kwargs):
    base = {"nodeid": "harness/shared/tests/test_x.py::TestY::test_z[a]", "when": "call", "skipped": True}
    base.update(kwargs)
    return SimpleNamespace(**base)


class TestSkipEvent:
    def test_a_skipif_at_setup_is_recorded_with_its_reason(self) -> None:
        report = _report(when="setup", longrepr=("f.py", 3, "Skipped: langgraph not installed (DEC-026)"))
        assert _skip_events.skip_event(report) == (
            "harness/shared/tests/test_x.py::TestY::test_z[a]",
            "test_z[a]",
            "langgraph not installed (DEC-026)",
        )

    def test_a_pytest_skip_in_the_body_is_recorded(self) -> None:
        report = _report(when="call", longrepr=("f.py", 9, "Skipped: mcp package not installed (DEC-026)"))
        event = _skip_events.skip_event(report)
        assert event is not None and event[2] == "mcp package not installed (DEC-026)"

    def test_a_passed_report_is_ignored(self) -> None:
        assert _skip_events.skip_event(_report(skipped=False, longrepr=None)) is None

    def test_a_teardown_phase_is_ignored(self) -> None:
        assert _skip_events.skip_event(_report(when="teardown", longrepr=("f", 1, "Skipped: x"))) is None

    def test_an_xfail_is_not_a_skip(self) -> None:
        report = _report(longrepr="reason", wasxfail="expected")
        assert _skip_events.skip_event(report) is None

    def test_tabs_and_newlines_in_a_reason_cannot_break_the_tsv(self) -> None:
        report = _report(longrepr=("f", 1, "Skipped: a\treason\nwith breaks"))
        event = _skip_events.skip_event(report)
        assert event is not None
        assert "\t" not in event[2] and "\n" not in event[2]


class TestSkipReason:
    def test_prefix_is_stripped(self) -> None:
        assert _skip_events.skip_reason(("p", 1, "Skipped: why")) == "why"

    def test_non_tuple_longrepr_is_rendered(self) -> None:
        assert _skip_events.skip_reason("plain text") == "plain text"


class TestWriteEvents:
    def test_writes_the_tsv_the_gate_reads(self, tmp_path: Path) -> None:
        out = tmp_path / "nested" / "skips.tsv"
        rows = [("a.py::t1", "t1", "r1 (DEC-026)"), ("b.py::t2", "t2", "r2 (DEC-026)")]
        assert _skip_events.write_events(out, rows) == 2
        assert out.read_text(encoding="utf-8") == "a.py::t1\tt1\tr1 (DEC-026)\nb.py::t2\tt2\tr2 (DEC-026)\n"

    def test_no_skips_writes_an_empty_file_not_no_file(self, tmp_path: Path) -> None:
        """The gate fails closed on a missing file; zero skips must still leave evidence."""
        out = tmp_path / "skips.tsv"
        assert _skip_events.write_events(out, []) == 0
        assert out.exists() and out.read_text(encoding="utf-8") == ""


class TestEventsPath:
    def test_env_override_wins(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        monkeypatch.setenv(_skip_events.SKIP_EVENTS_ENV, str(tmp_path / "x.tsv"))
        assert _skip_events.events_path() == tmp_path / "x.tsv"

    def test_default_lives_beside_the_suite(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv(_skip_events.SKIP_EVENTS_ENV, raising=False)
        path = _skip_events.events_path()
        assert path.parent.name == ".artifacts" and path.parent.parent == Path(_skip_events.__file__).parent
