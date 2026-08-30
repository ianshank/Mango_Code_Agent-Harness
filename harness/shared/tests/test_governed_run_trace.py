"""Contract tests for the content-free governed-run lifecycle trace."""

from __future__ import annotations

from pathlib import Path
from typing import cast

import pytest

from harness.shared import mango_mas_orchestrator as orch_module
from harness.shared.governance.verdict import LoopOutcome, Verdict
from harness.shared.mango_mas_orchestrator import MangoMASOrchestrator


def _outcome() -> LoopOutcome:
    return LoopOutcome(Verdict("VERIFIED", "ok", "", "make test", 0), "verifier text", "plan", "code")


def _orchestrator(workspace: Path, monkeypatch: pytest.MonkeyPatch) -> MangoMASOrchestrator:
    """Build an orchestrator whose phases are local deterministic functions."""
    orchestrator = MangoMASOrchestrator(workspace_dir=workspace)
    messages = {
        "planner": "plan",
        "nemotron-reasoner": "code",
        "verifier": "verifier text",
    }
    monkeypatch.setattr(orchestrator, "execute_agent", lambda role, *_args, **_kwargs: messages[role])
    monkeypatch.setattr(orchestrator, "_harness_verdict", lambda: _outcome().verdict)
    return orchestrator


def test_trace_has_exact_phase_lifecycle_order_and_monotonic_elapsed(
    mock_workspace: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    orchestrator = _orchestrator(mock_workspace, monkeypatch)
    # execute_loop reads one origin, one planner timing value, then one value per
    # emitted event. Deliberately repeat the origin to pin non-negative timing.
    readings = iter([50.0, 50.0, 50.001, 50.002, 50.004, 50.006, 50.009, 50.013, 50.018, 50.025])
    monkeypatch.setattr(orch_module.time, "monotonic", lambda: next(readings))
    trace: list[dict[str, object]] = []

    outcome = orchestrator.execute_loop("task", trace_sink=trace.append)

    assert outcome == _outcome()
    assert [(event["sequence"], event["phase"], event["state"]) for event in trace] == [
        (1, "planner", "started"),
        (2, "planner", "completed"),
        (3, "reasoner", "started"),
        (4, "reasoner", "completed"),
        (5, "verifier", "started"),
        (6, "verifier", "completed"),
        (7, "harness_verification", "started"),
        (8, "harness_verification", "completed"),
    ]
    elapsed = [cast(int, event["elapsed_ms"]) for event in trace]
    assert all(isinstance(value, int) and value >= 0 for value in elapsed)
    assert elapsed == sorted(elapsed)


def test_failed_phase_emits_started_then_failed_and_reraises(
    mock_workspace: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    orchestrator = MangoMASOrchestrator(workspace_dir=mock_workspace)
    failure = RuntimeError("planner failure")

    def fail_planner(role: str, *_args: object, **_kwargs: object) -> str:
        assert role == "planner"
        raise failure

    monkeypatch.setattr(orchestrator, "execute_agent", fail_planner)
    readings = iter([10.0, 10.0, 10.0, 10.001])
    monkeypatch.setattr(orch_module.time, "monotonic", lambda: next(readings))
    trace: list[dict[str, object]] = []

    with pytest.raises(RuntimeError) as raised:
        orchestrator.execute_loop("task", trace_sink=trace.append)

    assert raised.value is failure
    assert [(event["sequence"], event["phase"], event["state"]) for event in trace] == [
        (1, "planner", "started"),
        (2, "planner", "failed"),
    ]


def test_sink_failure_does_not_change_successful_orchestration(
    mock_workspace: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    orchestrator = _orchestrator(mock_workspace, monkeypatch)

    def broken_sink(_event: dict[str, object]) -> None:
        raise OSError("telemetry unavailable")

    assert orchestrator.execute_loop("task", trace_sink=broken_sink) == _outcome()


def test_execute_loop_without_sink_and_legacy_wrapper_remain_compatible(
    mock_workspace: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    orchestrator = _orchestrator(mock_workspace, monkeypatch)
    assert orchestrator.execute_loop("task") == _outcome()

    monkeypatch.setattr(orchestrator, "execute_loop", lambda task: _outcome())
    assert orchestrator.execute_sequential_thinking_loop("task") == "verifier text"
