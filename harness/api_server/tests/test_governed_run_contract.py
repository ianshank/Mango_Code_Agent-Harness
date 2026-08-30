"""Wire and static-console contracts for governed orchestration runs."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

pytest.importorskip("fastapi")

from fastapi.testclient import TestClient  # noqa: E402

from harness.api_server.main import app  # noqa: E402
from harness.shared.governance.verdict import LoopOutcome, Verdict  # noqa: E402

STATIC = Path(__file__).resolve().parents[1] / "static"


def _outcome(
    status: str = "VERIFIED",
    reason: str = "check passed",
    termination: str = "",
    code: int = 0,
) -> LoopOutcome:
    return LoopOutcome(
        Verdict(status, reason, termination, "make -f Makefile test-python", code),
        "verifier assessment",
        "plan",
        "code",
    )


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)


def test_api_preserves_legacy_fields_and_exposes_structured_verdict_and_trace(
    client: TestClient, api_server_key: str
) -> None:
    emitted = [
        {"sequence": 1, "phase": "planner", "state": "started", "elapsed_ms": 0},
        {"sequence": 2, "phase": "planner", "state": "completed", "elapsed_ms": 2},
    ]
    with patch("harness.api_server.main.MangoMASOrchestrator") as cls:
        instance = cls.return_value

        def execute(_task: str, *, trace_sink) -> LoopOutcome:
            for event in emitted:
                trace_sink(event)
            return _outcome()

        instance.execute_loop.side_effect = execute
        instance.conversation_history = [{"role": "assistant", "content": "ordinary history"}]
        response = client.post("/api/orchestrate", json={"task": "task"}, headers={"X-API-Key": api_server_key})

    assert response.status_code == 200
    body = response.json()
    assert {key: body[key] for key in ("status", "result", "history")} == {
        "status": "success",
        "result": "verifier assessment",
        "history": [{"role": "assistant", "content": "ordinary history"}],
    }
    assert body["verdict"] == "VERIFIED"
    assert body["verdict_command"] == "make -f Makefile test-python"
    assert body["verdict_exit_code"] == 0
    assert body["verdict_detail"] == "make -f Makefile test-python exited 0: check passed"
    assert body["trace"] == emitted


@pytest.mark.parametrize(
    ("status", "reason", "termination", "code"),
    [
        ("VERIFIED", "test-python exited 0", "", 0),
        ("FAILED", "test-python exited 1", "verification_failed", 1),
        ("BLOCKED", "verification unavailable", "verification_unavailable", -1),
    ],
)
def test_api_preserves_distinct_harness_verdict_semantics(
    client: TestClient, api_server_key: str, status: str, reason: str, termination: str, code: int
) -> None:
    with patch("harness.api_server.main.MangoMASOrchestrator") as cls:
        cls.return_value.execute_loop.return_value = _outcome(status, reason, termination, code)
        cls.return_value.conversation_history = []
        response = client.post("/api/orchestrate", json={"task": "task"}, headers={"X-API-Key": api_server_key})

    body = response.json()
    assert response.status_code == 200
    assert body["status"] == "success"
    assert (body["verdict"], body["termination_reason"], body["verdict_exit_code"]) == (
        status,
        termination or None,
        code,
    )


def test_api_redacts_result_verdict_evidence_and_nested_nullable_history(
    client: TestClient, api_server_key: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    provider_key = "nvapi-regression-secret-12345678"
    monkeypatch.setenv("NVIDIA_API_KEY", provider_key)
    outcome = LoopOutcome(
        Verdict(
            "FAILED",
            f"reason carries {api_server_key} and {provider_key}",
            "verification_failed",
            f"make test --key={api_server_key}",
            1,
        ),
        f"result carries {provider_key}",
        "plan",
        "code",
    )
    history = [{
        "role": "assistant",
        "content": None,
        "tool_calls": [{
            "id": f"call-{api_server_key}",
            "function": {"name": "run_command", "arguments": f'{{"token":"{provider_key}"}}'},
            "metadata": [None, {"credential": api_server_key}],
        }],
    }]
    with patch("harness.api_server.main.MangoMASOrchestrator") as cls:
        cls.return_value.execute_loop.return_value = outcome
        cls.return_value.conversation_history = history
        response = client.post("/api/orchestrate", json={"task": "task"}, headers={"X-API-Key": api_server_key})

    assert response.status_code == 200
    body = response.json()
    assert body["history"][0]["content"] is None
    assert body["history"][0]["tool_calls"][0]["metadata"][0] is None
    serialised = response.text
    assert provider_key not in serialised
    assert api_server_key not in serialised
    assert "<REDACTED_API_KEY>" in serialised


def test_api_returns_content_free_failed_trace_without_leaking_failure(
    client: TestClient, api_server_key: str, caplog: pytest.LogCaptureFixture
) -> None:
    sensitive_failure = "provider response contained synthetic-secret-12345678"
    with patch("harness.api_server.main.MangoMASOrchestrator") as cls:
        instance = cls.return_value

        def execute(_task: str, *, trace_sink) -> LoopOutcome:
            trace_sink({"sequence": 1, "phase": "planner", "state": "started", "elapsed_ms": 0})
            trace_sink({"sequence": 2, "phase": "planner", "state": "failed", "elapsed_ms": 3})
            try:
                raise ValueError(sensitive_failure)
            except ValueError as provider_error:
                raise RuntimeError(sensitive_failure) from provider_error

        instance.execute_loop.side_effect = execute
        response = client.post("/api/orchestrate", json={"task": "task"}, headers={"X-API-Key": api_server_key})

    assert response.status_code == 500
    assert response.json() == {
        "detail": "Internal orchestration error",
        "trace": [
            {"sequence": 1, "phase": "planner", "state": "started", "elapsed_ms": 0},
            {"sequence": 2, "phase": "planner", "state": "failed", "elapsed_ms": 3},
        ],
    }
    assert sensitive_failure not in response.text
    assert sensitive_failure not in caplog.text
    assert "Orchestration failed" in caplog.text


def test_static_console_uses_safe_dom_trace_data_and_separate_assessments(client: TestClient) -> None:
    response = client.get("/")
    assert response.status_code == 200
    assert "Mango MAS Dashboard" in response.text  # legacy title contract

    html = STATIC.joinpath("index.html").read_text(encoding="utf-8")
    script = STATIC.joinpath("app.js").read_text(encoding="utf-8")
    css = STATIC.joinpath("styles.css").read_text(encoding="utf-8")
    assert "Harness verdict" in script
    assert "Verifier assessment" in script
    assert "event.state" in script
    assert "event.elapsed_ms" in script
    assert "renderError(message, data)" in script
    for forbidden in ("innerHTML", "localStorage", "sessionStorage"):
        assert forbidden not in script
    assert "fonts.googleapis.com" not in html + css
    assert "font-family: system-ui" in css
