import secrets
from unittest.mock import patch

import pytest

pytest.importorskip("fastapi")

from fastapi.testclient import TestClient  # noqa: E402

from harness.api_server.main import app  # noqa: E402

client = TestClient(app)


def _passing_outcome(message: str = "PASS: verified"):
    """A LoopOutcome a stubbed orchestrator can return.

    The orchestrator class is patched wholesale here, so `execute_loop` would
    otherwise yield a MagicMock, which Pydantic rejects for a `str` field and the
    endpoint's blanket `except` converts to a 500. Stubbing a real value keeps
    these tests about what they were written for.
    """
    from harness.shared.governance.verdict import LoopOutcome, Verdict

    verdict = Verdict("VERIFIED", "make -f Makefile test-python exited 0", "", "make -f Makefile test-python", 0)
    return LoopOutcome(verdict, message, "plan", "code")

@pytest.fixture(autouse=True)
def _api_server_key(monkeypatch):
    """Provide a throwaway API_SERVER_KEY per test without committing a literal secret."""
    key = secrets.token_urlsafe(32)
    monkeypatch.setenv("API_SERVER_KEY", key)
    return key


@pytest.mark.enable_socket  # TestClient drives the app over loopback (R-EGF-6)
def test_static_files():
    """Test that static UI files are served successfully."""
    response = client.get("/")
    assert response.status_code == 200
    assert "Mango MAS Dashboard" in response.text


@pytest.mark.enable_socket  # TestClient drives the app over loopback (R-EGF-6)
def test_api_orchestrate_success(_api_server_key):
    """Test successful orchestration via the API."""
    with patch("harness.api_server.main.MangoMASOrchestrator") as mock_orchestrator_class:
        mock_instance = mock_orchestrator_class.return_value
        mock_instance.execute_loop.return_value = _passing_outcome()
        mock_instance.conversation_history = [
            {"role": "user", "content": "Write a python function"},
            {"role": "assistant", "content": "Here is the code"},
        ]

        response = client.post(
            "/api/orchestrate",
            json={"task": "Create a dummy test"},
            headers={"X-API-Key": _api_server_key},
        )

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "success"
        assert data["result"] == "PASS: verified"
        assert isinstance(data["history"], list)


@patch("harness.api_server.main.MangoMASOrchestrator")
@pytest.mark.enable_socket  # TestClient drives the app over loopback (R-EGF-6)
def test_api_orchestrate_failure(mock_orchestrator_class, _api_server_key):
    """Test orchestration failure handling — internals must not leak to clients."""
    mock_instance = mock_orchestrator_class.return_value
    mock_instance.execute_loop.side_effect = RuntimeError("Nemotron API failed")

    response = client.post(
        "/api/orchestrate",
        json={"task": "Fail me"},
        headers={"X-API-Key": _api_server_key},
    )

    assert response.status_code == 500
    detail = response.json()["detail"]
    # Security: the underlying exception message must not be echoed to clients.
    assert "Nemotron API failed" not in detail
    assert detail == "Internal orchestration error"


@pytest.mark.enable_socket  # TestClient drives the app over loopback (R-EGF-6)
def test_api_orchestrate_unauthorized(_api_server_key):
    """Test unauthorized access."""
    response = client.post(
        "/api/orchestrate",
        json={"task": "Create a dummy test"},
        headers={"X-API-Key": "wrong-key"},
    )
    assert response.status_code == 401


def _run_dev_runner(monkeypatch):
    """Execute main.py's __main__ block with a stubbed uvicorn, returning the run kwargs."""
    import runpy
    import sys
    import types

    calls = {}
    fake_uvicorn = types.ModuleType("uvicorn")
    # monkeypatch.setattr, not a direct assignment and not the builtin setattr:
    # ModuleType declares no `run`, so `fake_uvicorn.run = ...` is an
    # attr-defined error under --check-untyped-defs, while bare setattr with a
    # constant name is B010. This form satisfies both and is undone for us at
    # teardown. raising=False because the attribute is being created, not
    # replaced -- without it pytest rejects the patch on a missing attribute.
    monkeypatch.setattr(
        fake_uvicorn, "run", lambda app, **kwargs: calls.update(kwargs), raising=False
    )
    monkeypatch.setitem(sys.modules, "uvicorn", fake_uvicorn)
    runpy.run_module("harness.api_server.main", run_name="__main__")
    return calls


def test_dev_runner_defaults_match_container(monkeypatch):
    """The dev runner must default to the container port with reload off."""
    monkeypatch.delenv("API_SERVER_PORT", raising=False)
    monkeypatch.delenv("API_SERVER_RELOAD", raising=False)
    calls = _run_dev_runner(monkeypatch)
    assert calls["port"] == 8080
    assert calls["reload"] is False


def test_dev_runner_env_overrides(monkeypatch):
    """Port and reload are opt-in via environment, never hard-coded."""
    monkeypatch.setenv("API_SERVER_PORT", "9001")
    monkeypatch.setenv("API_SERVER_RELOAD", "1")
    calls = _run_dev_runner(monkeypatch)
    assert calls["port"] == 9001
    assert calls["reload"] is True


@pytest.mark.enable_socket  # TestClient drives the app over loopback (R-EGF-6)
def test_the_response_carries_the_verdict_and_what_earned_it(monkeypatch):
    """AC-11 / R-VP-13: the verdict names the command and its exit code.

    `status` is deliberately unchanged -- it still means "the orchestration did
    not raise" -- so a client reading only that field learns nothing. That is why
    the verdict has its own fields and why they say what was run: the configured
    target is one gate, not the repository's full matrix.
    """
    monkeypatch.setenv("API_SERVER_KEY", "k" * 32)
    with patch("harness.api_server.main.MangoMASOrchestrator") as cls:
        cls.return_value.execute_loop.return_value = _passing_outcome()
        cls.return_value.conversation_history = []
        response = client.post("/api/orchestrate", json={"task": "t"}, headers={"X-API-Key": "k" * 32})

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "success"
    assert body["verdict"] == "VERIFIED"
    assert "make -f Makefile test-python" in body["verdict_detail"]
    assert "exited 0" in body["verdict_detail"]
    assert body["termination_reason"] is None


@pytest.mark.enable_socket  # TestClient drives the app over loopback (R-EGF-6)
def test_a_failing_verdict_is_reported_while_status_stays_success(monkeypatch):
    """The defect, pinned: before this change these two runs were identical."""
    from harness.shared.governance.verdict import LoopOutcome, Verdict

    monkeypatch.setenv("API_SERVER_KEY", "k" * 32)
    failing = LoopOutcome(
        Verdict("FAILED", "exited 1", "verification_failed", "make -f Makefile test-python", 1),
        "VERIFY: PASS",  # the model still claims a pass; it is not the authority
        "plan",
        "code",
    )
    with patch("harness.api_server.main.MangoMASOrchestrator") as cls:
        cls.return_value.execute_loop.return_value = failing
        cls.return_value.conversation_history = []
        response = client.post("/api/orchestrate", json={"task": "t"}, headers={"X-API-Key": "k" * 32})

    body = response.json()
    assert body["status"] == "success"
    assert body["verdict"] == "FAILED"
    assert body["termination_reason"] == "verification_failed"
    assert body["result"] == "VERIFY: PASS"
