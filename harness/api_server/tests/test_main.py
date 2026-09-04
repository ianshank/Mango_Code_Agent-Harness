import json
import os
import secrets
from unittest.mock import patch

import pytest

# fastapi's presence is gated once, by this directory's conftest; the duplicate
# `importorskip` that stood here skipped nothing the conftest had not already
# decided (code-quality-tech-debt-plan R-CQ-30).
from fastapi.testclient import TestClient

from harness.api_server.main import app


@pytest.fixture
def client() -> TestClient:
    """A fresh TestClient per test.

    This stood at module level, built once at import. Under a randomised or
    parallel run (pytest-randomly, xdist) import-time state is shared across
    whatever order or worker the tests land in, so a client that one test left
    mid-request would leak into the next; a fixture is scoped to the test that
    asked for it (audit H8).

    No socket exemption either: TestClient drives the app through anyio's
    BlockingPortal, whose plumbing is a unix socketpair, which
    `--allow-unix-socket` in addopts permits. The per-test `enable_socket` marks
    that stood here said "loopback" and re-opened TCP for a need that was never
    TCP (audit M12).
    """
    return TestClient(app)


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


def test_static_files(client: TestClient):
    """Test that static UI files are served successfully."""
    response = client.get("/")
    assert response.status_code == 200
    assert "Mango MAS Dashboard" in response.text


def test_api_orchestrate_success(client: TestClient, _api_server_key):
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
def test_api_orchestrate_failure(mock_orchestrator_class, client: TestClient, _api_server_key):
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


def test_api_orchestrate_unauthorized(client: TestClient, _api_server_key):
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
    """The dev runner must default to the container port, loopback host, reload off."""
    monkeypatch.delenv("API_SERVER_PORT", raising=False)
    monkeypatch.delenv("API_SERVER_HOST", raising=False)
    monkeypatch.delenv("API_SERVER_RELOAD", raising=False)
    calls = _run_dev_runner(monkeypatch)
    assert calls["port"] == 8080
    assert calls["host"] == "127.0.0.1"
    assert calls["reload"] is False


def test_dev_runner_env_overrides(monkeypatch):
    """Port, host, and reload are opt-in via environment, never hard-coded."""
    monkeypatch.setenv("API_SERVER_PORT", "9001")
    monkeypatch.setenv("API_SERVER_HOST", "0.0.0.0")
    monkeypatch.setenv("API_SERVER_RELOAD", "1")
    calls = _run_dev_runner(monkeypatch)
    assert calls["port"] == 9001
    assert calls["host"] == "0.0.0.0"
    assert calls["reload"] is True


def test_the_response_carries_the_verdict_and_what_earned_it(client: TestClient, monkeypatch):
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


def test_a_failing_verdict_is_reported_while_status_stays_success(client: TestClient, monkeypatch):
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


# --- Audit B3: the history of a tool-using run must reach the client ---------

TOOL_USING_HISTORY = [
    {"role": "system", "content": "You are the reasoner."},
    {"role": "user", "content": "List the repository root."},
    {
        "role": "assistant",
        "content": None,
        "tool_calls": [
            {
                "id": "call_1",
                "type": "function",
                "function": {"name": "run_command", "arguments": '{"command": "ls"}'},
            }
        ],
    },
    {"role": "tool", "tool_call_id": "call_1", "name": "run_command", "content": "Makefile\nharness\n"},
    {"role": "assistant", "content": "Done: two entries."},
]


def _orchestrate_with_history(history, key):
    with patch("harness.api_server.main.MangoMASOrchestrator") as cls:
        cls.return_value.execute_loop.return_value = _passing_outcome()
        cls.return_value.conversation_history = history
        return client.post("/api/orchestrate", json={"task": "t"}, headers={"X-API-Key": key})


@pytest.mark.enable_socket  # TestClient drives the app over loopback (R-EGF-6)
def test_tool_using_history_round_trips(_api_server_key):
    """Audit B3. `history: list[dict[str, str]]` rejected `content: None`,
    `tool_calls` and `tool_call_id`, so every run that used a tool -- every real
    run -- returned 500 with its verdict discarded. The structure must come back
    exactly as the orchestrator built it, `null` content included."""
    response = _orchestrate_with_history(TOOL_USING_HISTORY, _api_server_key)

    assert response.status_code == 200, response.text
    history = response.json()["history"]
    assert history == TOOL_USING_HISTORY
    assistant_turn = history[2]
    assert assistant_turn["content"] is None
    assert assistant_turn["tool_calls"][0]["function"]["name"] == "run_command"
    assert history[3]["tool_call_id"] == "call_1"


@pytest.mark.enable_socket  # TestClient drives the app over loopback (R-EGF-6)
def test_string_only_history_keeps_its_wire_shape(_api_server_key):
    """Backward compatibility: the typed models must not add `null`-valued keys
    (`name`, `tool_calls`, ...) to a message that never had them."""
    history = [{"role": "user", "content": "hi"}, {"role": "assistant", "content": "hello"}]
    response = _orchestrate_with_history(history, _api_server_key)
    assert response.status_code == 200
    assert response.json()["history"] == history


@pytest.mark.enable_socket  # TestClient drives the app over loopback (R-EGF-6)
def test_a_malformed_message_is_an_internal_error_that_leaks_nothing(_api_server_key):
    """An unknown role is not a shape the wire models invent a meaning for. It
    is refused as the same opaque 500 every other internal failure produces:
    no pydantic error text, no field path, no echo of the offending value."""
    malformed = [{"role": "user", "content": "hi"}, {"role": "wizard", "content": "abracadabra"}]
    response = _orchestrate_with_history(malformed, _api_server_key)

    assert response.status_code == 500
    assert response.json() == {"detail": "Internal orchestration error"}
    for internals in ("wizard", "abracadabra", "validation", "pydantic", "history"):
        assert internals not in response.text


# --- Audit M14: liveness and readiness -----------------------------------------


@pytest.mark.enable_socket  # TestClient drives the app over loopback (R-EGF-6)
def test_healthz_is_200_without_any_credential(monkeypatch):
    """Liveness answers even on a misconfigured server: it reports the process
    is up, not that it is usable. No key required, none configured."""
    monkeypatch.delenv("API_SERVER_KEY", raising=False)
    response = client.get("/healthz")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


@pytest.mark.enable_socket  # TestClient drives the app over loopback (R-EGF-6)
def test_readyz_is_200_when_key_and_policy_are_in_place(_api_server_key):
    response = client.get("/readyz")
    assert response.status_code == 200
    assert response.json() == {"status": "ready", "checks": {"api_key": True, "policy": True}}


@pytest.mark.enable_socket  # TestClient drives the app over loopback (R-EGF-6)
def test_readyz_is_503_without_the_api_key(monkeypatch):
    """The negative side of readiness: an unconfigured key is exactly the
    state `/api/orchestrate` would 500 on, so the probe must say so first."""
    monkeypatch.delenv("API_SERVER_KEY", raising=False)
    response = client.get("/readyz")
    assert response.status_code == 503
    body = response.json()
    assert body["status"] == "unavailable"
    assert body["checks"]["api_key"] is False
    assert body["checks"]["policy"] is True


@pytest.mark.enable_socket  # TestClient drives the app over loopback (R-EGF-6)
def test_readyz_is_503_when_the_policy_does_not_load(_api_server_key, monkeypatch, tmp_path):
    """A present-but-broken policy fails the run closed (`PolicyError`), so the
    server is not ready. The probe reports a boolean, never the path the error
    names."""
    broken = tmp_path / "governance-policy.json"
    broken.write_text("{not json", encoding="utf-8")
    monkeypatch.setattr("harness.shared.policy_loader.POLICY_PATH", broken)

    response = client.get("/readyz")

    assert response.status_code == 503
    body = response.json()
    assert body["checks"] == {"api_key": True, "policy": False}
    assert str(tmp_path) not in response.text
    assert "governance-policy.json" not in response.text


# --- Logging is configured at startup, not import ------------------------------


@pytest.mark.enable_socket  # TestClient drives the app over loopback (R-EGF-6)
def test_lifespan_installs_the_json_handler():
    """Entering lifespan (what uvicorn does on startup) configures the root
    logger with the JSON formatter. The root logger is restored afterwards so
    pytest's own capture handlers survive this test."""
    import logging

    from harness.shared.json_logging import JSONFormatter

    root = logging.getLogger()
    saved_handlers, saved_level = root.handlers[:], root.level
    try:
        with TestClient(app):
            assert any(isinstance(h.formatter, JSONFormatter) for h in root.handlers)
    finally:
        for handler in root.handlers[:]:
            root.removeHandler(handler)
        for handler in saved_handlers:
            root.addHandler(handler)
        root.setLevel(saved_level)


def test_json_logging_is_installed_by_lifespan_not_by_import():
    """Importing the app must leave the importing process's root logger alone;
    serving it (lifespan, which uvicorn runs on startup) installs the JSON
    handler exactly as the import-time call used to. Run in a subprocess so the
    import-time observation is of a genuinely fresh interpreter, and so the
    root-logger rewrite does not reach this pytest process."""
    import subprocess
    import sys

    from harness.api_server.main import PROJECT_ROOT

    probe = (
        "import json, logging\n"
        "from harness.shared.json_logging import JSONFormatter\n"
        "def has_json(): return any(isinstance(h.formatter, JSONFormatter) for h in logging.getLogger().handlers)\n"
        "from harness.api_server.main import app\n"
        "after_import = has_json()\n"
        "from fastapi.testclient import TestClient\n"
        "with TestClient(app):\n"
        "    during_lifespan = has_json()\n"
        "print(json.dumps({'after_import': after_import, 'during_lifespan': during_lifespan}))\n"
    )
    env = dict(os.environ, PYTHONPATH=str(PROJECT_ROOT))
    result = subprocess.run(
        [sys.executable, "-c", probe], cwd=str(PROJECT_ROOT), capture_output=True, text=True, timeout=120, env=env
    )
    assert result.returncode == 0, result.stderr
    # The last stdout line is the probe's verdict; anything before it would be
    # JSON log lines the newly installed handler wrote to stdout.
    observed = json.loads(result.stdout.strip().splitlines()[-1])
    assert observed == {"after_import": False, "during_lifespan": True}
