"""Tests for harness/shared/coverage_gate.py — per-metric floors, fail-closed reads.

The gate's contract: thresholds come only from governance-policy.json, each
metric is compared against its own numerator/denominator from coverage.json,
and every unreadable or malformed input exits 1 with a reason (absence of
evidence is never a pass).
"""

from __future__ import annotations

import json
import logging
import runpy
import sys
from pathlib import Path

import pytest

from harness.shared import coverage_gate as cg

GATE = Path(cg.__file__).resolve()

pytestmark = pytest.mark.governance


def _write_json(path: Path, obj: object) -> Path:
    path.write_text(json.dumps(obj), encoding="utf-8")
    return path


@pytest.fixture
def policy_file(tmp_path: Path) -> Path:
    return _write_json(tmp_path / "policy.json", {"coverage": {"lines": 80, "branches": 70}})


@pytest.fixture
def coverage_file(tmp_path: Path) -> Path:
    return _write_json(
        tmp_path / "coverage.json",
        {
            "totals": {
                "covered_lines": 90,
                "num_statements": 100,
                "covered_branches": 75,
                "num_branches": 100,
            }
        },
    )


# --- load_thresholds ---


def test_load_thresholds_reads_both_metrics(policy_file: Path):
    assert cg.load_thresholds(policy_file) == {"lines": 80.0, "branches": 70.0}


def test_load_thresholds_missing_coverage_block_fails_closed(tmp_path: Path, caplog):
    policy = _write_json(tmp_path / "policy.json", {"limits": {}})
    with caplog.at_level(logging.ERROR, logger=cg.logger.name):
        with pytest.raises(SystemExit) as exc:
            cg.load_thresholds(policy)
    assert exc.value.code == 1
    assert "no coverage block" in caplog.text


@pytest.mark.parametrize("bad_value", ["90", None, True])
def test_load_thresholds_non_numeric_metric_fails_closed(tmp_path: Path, bad_value, caplog):
    policy = _write_json(tmp_path / "policy.json", {"coverage": {"lines": bad_value, "branches": 70}})
    with caplog.at_level(logging.ERROR, logger=cg.logger.name):
        with pytest.raises(SystemExit) as exc:
            cg.load_thresholds(policy)
    assert exc.value.code == 1
    assert "missing or non-numeric" in caplog.text


def test_load_thresholds_unreadable_policy_fails_closed(tmp_path: Path):
    with pytest.raises(SystemExit) as exc:
        cg.load_thresholds(tmp_path / "absent.json")
    assert exc.value.code == 1


def test_load_thresholds_non_object_root_fails_closed(tmp_path: Path, caplog):
    policy = _write_json(tmp_path / "policy.json", ["not", "an", "object"])
    with caplog.at_level(logging.ERROR, logger=cg.logger.name):
        with pytest.raises(SystemExit) as exc:
            cg.load_thresholds(policy)
    assert exc.value.code == 1
    assert "root must be a JSON object" in caplog.text


# --- measure ---


def test_measure_extracts_percentages(coverage_file: Path):
    measured = cg.measure(coverage_file)
    assert measured == {"lines": 90.0, "branches": 75.0}


def test_measure_missing_totals_fails_closed(tmp_path: Path, caplog):
    report = _write_json(tmp_path / "coverage.json", {"files": {}})
    with caplog.at_level(logging.ERROR, logger=cg.logger.name):
        with pytest.raises(SystemExit) as exc:
            cg.measure(report)
    assert exc.value.code == 1
    assert "no totals block" in caplog.text


def test_measure_missing_branch_counters_fails_closed(tmp_path: Path, caplog):
    """A coverage.json produced without branch coverage lacks num_branches;
    that must exit 1 with the actionable hint, not divide by a default."""
    report = _write_json(
        tmp_path / "coverage.json",
        {"totals": {"covered_lines": 90, "num_statements": 100}},
    )
    with caplog.at_level(logging.ERROR, logger=cg.logger.name):
        with pytest.raises(SystemExit) as exc:
            cg.measure(report)
    assert exc.value.code == 1
    assert "branch coverage enabled" in caplog.text


def test_measure_zero_denominator_fails_closed(tmp_path: Path, caplog):
    report = _write_json(
        tmp_path / "coverage.json",
        {
            "totals": {
                "covered_lines": 0,
                "num_statements": 0,
                "covered_branches": 0,
                "num_branches": 10,
            }
        },
    )
    with caplog.at_level(logging.ERROR, logger=cg.logger.name):
        with pytest.raises(SystemExit) as exc:
            cg.measure(report)
    assert exc.value.code == 1
    assert "measured zero" in caplog.text


# --- check / main ---


def test_check_passes_when_all_floors_met(caplog):
    with caplog.at_level(logging.INFO, logger=cg.logger.name):
        assert cg.check({"lines": 80.0, "branches": 70.0}, {"lines": 90.0, "branches": 75.0}) is True
    assert "[PASS]" in caplog.text


def test_check_fails_when_one_metric_below_floor(caplog):
    with caplog.at_level(logging.ERROR, logger=cg.logger.name):
        assert cg.check({"lines": 80.0, "branches": 90.0}, {"lines": 90.0, "branches": 75.0}) is False
    assert "below the policy floor" in caplog.text


def test_main_returns_zero_on_pass(policy_file: Path, coverage_file: Path):
    assert cg.main(["--coverage-json", str(coverage_file), "--policy", str(policy_file)]) == 0


def test_main_returns_one_on_violation(tmp_path: Path, coverage_file: Path):
    policy = _write_json(tmp_path / "strict.json", {"coverage": {"lines": 99, "branches": 99}})
    assert cg.main(["--coverage-json", str(coverage_file), "--policy", str(policy)]) == 1


def test_main_dispatch_leg(policy_file: Path, coverage_file: Path, monkeypatch: pytest.MonkeyPatch):
    """The `if __name__ == "__main__"` leg (basicConfig + sys.exit) run exactly
    as `python harness/shared/coverage_gate.py` would run it."""
    monkeypatch.setattr(
        sys,
        "argv",
        ["coverage_gate.py", "--coverage-json", str(coverage_file), "--policy", str(policy_file)],
    )
    with pytest.raises(SystemExit) as exc:
        runpy.run_path(str(GATE), run_name="__main__")
    assert exc.value.code == 0
