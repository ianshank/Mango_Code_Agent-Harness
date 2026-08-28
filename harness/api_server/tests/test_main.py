import secrets
from unittest.mock import patch

import pytest
pytest.importorskip("fastapi")

from fastapi.testclient import TestClient

from harness.api_server.main import app

client = TestClient(app)


@pytest.fixture(autouse=True)
def _api_server_key(monkeypatch):
    """Provide a throwaway API_SERVER_KEY per test without committing a literal secret."""
    key = secrets.token_urlsafe(32)
    monkeypatch.setenv("API_SERVER_KEY", key)
    return key


def test_static_files():
    """Test that static UI files are served successfully."""
    response = client.get("/")
    assert response.status_code == 200
    assert "Mango MAS Dashboard" in response.text


def test_api_orchestrate_success(_api_server_key):
    """Test successful orchestration via the API."""
    with patch("harness.api_server.main.MangoMASOrchestrator") as mock_orchestrator_class:
        mock_instance = mock_orchestrator_class.return_value
        mock_instance.execute_sequential_thinking_loop.return_value = "PASS: verified"
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
def test_api_orchestrate_failure(mock_orchestrator_class, _api_server_key):
    """Test orchestration failure handling — internals must not leak to clients."""
    mock_instance = mock_orchestrator_class.return_value
    mock_instance.execute_sequential_thinking_loop.side_effect = RuntimeError("Nemotron API failed")

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
    # setattr, not attribute assignment: ModuleType declares no `run`, so a
    # direct assignment is an attr-defined error under --check-untyped-defs.
    # setattr expresses the same intent without suppressing the check, which is
    # better than a `type: ignore` that would also hide a real error here later.
    setattr(fake_uvicorn, "run", lambda app, **kwargs: calls.update(kwargs))
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
