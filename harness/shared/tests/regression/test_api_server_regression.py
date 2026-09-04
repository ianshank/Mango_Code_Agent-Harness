"""Regressions for the FastAPI orchestration server.

Defects reproduced here (all present on ``main`` before this change):

1. The API key was compared with ``!=``, which short-circuits on the first
   differing byte and leaks the matching prefix length through timing.
2. ``/api/orchestrate`` returned ``orchestrator.conversation_history``
   verbatim, so a credential that reached the history -- resolved inside the
   bridge, or echoed by a tool -- left the process over HTTP. The redactor that
   fixed it covered ``NVIDIA_API_KEY`` only, so ``API_SERVER_KEY`` and
   ``AGENT_EVIDENCE_KEY`` still left in clear text; the second is the HMAC key
   ``EvidenceBuilder`` signs with, so its disclosure permits forged evidence
   manifests rather than merely leaking a secret.
3. ``STATIC_DIR.mkdir()`` ran at module import, so merely importing the app
   (every pytest collection included) mutated the working tree.
4. ``TaskResponse.history`` was typed ``list[dict[str, str]]``, which admits
   only the system and user turns. A tool-using run appends an assistant turn
   with ``content: None`` and a ``tool_calls`` list, then a ``tool`` turn with
   ``tool_call_id``; pydantic rejected each, the blanket ``except`` converted
   the ``ValidationError`` to "Internal orchestration error", and every real
   run returned HTTP 500 with the verdict it had earned discarded
   (``docs/reports/2026-STANDARDS-AUDIT.md`` finding **B3**, Blocker).

The server lives in ``harness/api_server`` but its regressions live here with
the rest of the tier, so ``make test-regression`` asks one question in one
place.
"""

from __future__ import annotations

import ast
import asyncio
import os
import secrets
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

from harness.shared.tests._helpers import REPO

fastapi = pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

from harness.api_server.main import app, verify_api_key  # noqa: E402

MAIN_PY = REPO / "harness" / "api_server" / "main.py"


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

def _subprocess_env() -> dict[str, str]:
    """Child environment that can import ``harness`` from a clean interpreter.

    The package is not installed in every environment (the repo relies on
    pytest's ``pythonpath`` setting), so a bare subprocess needs the repo root
    on PYTHONPATH or it fails for a reason unrelated to what is under test.
    """
    env = dict(os.environ)
    existing = env.get("PYTHONPATH", "")
    env["PYTHONPATH"] = str(REPO) + (os.pathsep + existing if existing else "")
    return env


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)


@pytest.fixture
def server_key(monkeypatch: pytest.MonkeyPatch) -> str:
    key = secrets.token_urlsafe(32)
    monkeypatch.setenv("API_SERVER_KEY", key)
    return key


# Declared, not exempted (R-EGF-6): FastAPI's TestClient drives the app over a
# real loopback socket, so these genuinely need one. The declaration is visible
# here at the class rather than hidden in a global allow-list.
@pytest.mark.enable_socket
class TestConstantTimeKeyComparison:
    def test_key_check_routes_through_compare_digest(
        self, client: TestClient, server_key: str, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Timing itself is not measurable in a unit test, so this asserts the
        safe primitive is actually on the request path -- which is the part a
        refactor can silently remove."""
        calls: list[tuple[str, str]] = []
        real = secrets.compare_digest

        def recording(a, b):  # type: ignore[no-untyped-def]
            calls.append((a, b))
            return real(a, b)

        monkeypatch.setattr("harness.api_server.main.secrets.compare_digest", recording)
        client.post("/api/orchestrate", json={"task": "x"}, headers={"X-API-Key": "wrong"})
        assert calls, "the API key was compared without secrets.compare_digest"

    def test_source_contains_no_direct_key_equality(self) -> None:
        """A structural check on the auth function: no ``==``/``!=`` against
        the expected key can creep back in."""
        tree = ast.parse(MAIN_PY.read_text(encoding="utf-8"))
        verify = next(
            node for node in ast.walk(tree)
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == "verify_api_key"
        )
        compares = [
            node for node in ast.walk(verify)
            if isinstance(node, ast.Compare)
            and any(isinstance(op, (ast.Eq, ast.NotEq)) for op in node.ops)
        ]
        assert not compares, "verify_api_key compares the key with ==/!= instead of compare_digest"

    def test_wrong_key_is_rejected(self, client: TestClient, server_key: str) -> None:
        response = client.post("/api/orchestrate", json={"task": "x"}, headers={"X-API-Key": "nope"})
        assert response.status_code == 401

    def test_missing_key_is_rejected(self, client: TestClient, server_key: str) -> None:
        assert client.post("/api/orchestrate", json={"task": "x"}).status_code == 401

    def test_unconfigured_server_fails_closed(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("API_SERVER_KEY", raising=False)
        response = client.post("/api/orchestrate", json={"task": "x"}, headers={"X-API-Key": "anything"})
        assert response.status_code == 500

    @pytest.mark.parametrize("header", ["kéy-with-accent", "ключ", "\udcff"])
    def test_non_ascii_key_is_rejected_not_crashed(
        self, server_key: str, header: str
    ) -> None:
        """``secrets.compare_digest`` raises TypeError on a str with non-ASCII
        code points, where the old ``!=`` merely returned False.

        HTTP header bytes are decoded as latin-1 by the server stack, so such a
        string is reachable from the wire even though ``TestClient`` refuses to
        encode one -- hence calling the dependency directly rather than going
        through the client. Unhandled, this is a 500 any unauthenticated caller
        can trigger: hardening that trades a timing leak for a denial of
        service is not hardening.
        """
        with pytest.raises(fastapi.HTTPException) as excinfo:
            asyncio.run(verify_api_key(header))
        assert excinfo.value.status_code == 401


# Declared, not exempted (R-EGF-6): FastAPI's TestClient drives the app over a
# real loopback socket, so these genuinely need one. The declaration is visible
# here at the class rather than hidden in a global allow-list.
@pytest.mark.enable_socket
class TestHistoryRedaction:
    def test_credentials_do_not_leave_over_http(
        self, client: TestClient, server_key: str, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        secret = "nvapi-server-side-credential-4242"
        monkeypatch.setenv("NVIDIA_API_KEY", secret)

        with patch("harness.api_server.main.MangoMASOrchestrator") as orchestrator_cls:
            instance = orchestrator_cls.return_value
            instance.execute_loop.return_value = _passing_outcome("PASS")
            instance.conversation_history = [
                {"role": "user", "content": "do a thing"},
                {"role": "assistant", "content": f"used {secret} to call the API"},
            ]
            response = client.post(
                "/api/orchestrate", json={"task": "x"}, headers={"X-API-Key": server_key}
            )

        assert response.status_code == 200
        assert secret not in response.text
        assert "<REDACTED_API_KEY>" in response.text

    def test_ordinary_history_is_returned_unchanged(
        self, client: TestClient, server_key: str, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Redaction must not damage normal content -- otherwise the dashboard
        silently degrades and someone turns redaction off."""
        monkeypatch.delenv("NVIDIA_API_KEY", raising=False)
        history = [
            {"role": "user", "content": "Write a python function"},
            {"role": "assistant", "content": "Here is the code"},
        ]
        with patch("harness.api_server.main.MangoMASOrchestrator") as orchestrator_cls:
            instance = orchestrator_cls.return_value
            instance.execute_loop.return_value = _passing_outcome("PASS")
            instance.conversation_history = history
            response = client.post(
                "/api/orchestrate", json={"task": "x"}, headers={"X-API-Key": server_key}
            )
        assert response.json()["history"] == history


# Declared, not exempted (R-EGF-6): FastAPI's TestClient drives the app over a
# real loopback socket, so these genuinely need one. The declaration is visible
# here at the class rather than hidden in a global allow-list.
@pytest.mark.enable_socket
class TestImportPurity:
    def test_importing_the_app_creates_nothing(self, tmp_path: Path) -> None:
        """Run in a subprocess with the static directory removed from view: a
        clean import must not write to the tree. This is the api_server slice
        of the import-purity rule."""
        probe = tmp_path / "probe.py"
        probe.write_text(
            "import pathlib, sys\n"
            "before = {p for p in pathlib.Path('harness/api_server').rglob('*')}\n"
            "import harness.api_server.main  # noqa: F401\n"
            "after = {p for p in pathlib.Path('harness/api_server').rglob('*')}\n"
            "created = {p for p in after - before if '__pycache__' not in p.parts}\n"
            "sys.exit(1 if created else 0)\n",
            encoding="utf-8",
        )
        result = subprocess.run(
            [sys.executable, str(probe)],
            cwd=str(REPO), capture_output=True, text=True, timeout=60, env=_subprocess_env(),
        )
        assert result.returncode == 0, f"importing the app created files: {result.stdout}{result.stderr}"

    def test_import_writes_nothing_to_stdout(self) -> None:
        result = subprocess.run(
            [sys.executable, "-c", "import harness.api_server.main"],
            cwd=str(REPO), capture_output=True, text=True, timeout=60, env=_subprocess_env(),
        )
        assert result.returncode == 0, result.stderr
        assert result.stdout == "", f"import printed to stdout: {result.stdout!r}"

    def test_no_filesystem_mutation_at_module_scope(self) -> None:
        """The behavioural probe above cannot catch this on its own: ``static/``
        already exists in a working tree, so ``mkdir(exist_ok=True)`` creates
        nothing and the import looks pure. Assert structurally instead that no
        mutating call runs at import scope.
        """
        tree = ast.parse(MAIN_PY.read_text(encoding="utf-8"))
        mutators = {"mkdir", "touch", "write_text", "write_bytes", "makedirs", "unlink", "rmdir"}
        offenders = [
            f"{node.func.attr} (line {node.lineno})"
            for statement in tree.body
            if not isinstance(statement, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.If))
            for node in ast.walk(statement)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr in mutators
        ]
        assert not offenders, f"module-scope filesystem mutation on import: {offenders}"

    def test_static_directory_is_created_on_startup(self, client: TestClient) -> None:
        """Deferring creation must not break serving: entering the TestClient
        context runs lifespan, after which the directory exists."""
        with client:
            assert (REPO / "harness" / "api_server" / "static").is_dir()


class TestEveryCredentialIsRedactedOnTheWayOut:
    """Defect 2, second half. The response path was fixed; the redactor behind it
    still knew about one provider."""

    def test_evidence_and_server_keys_do_not_leave_over_http(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from harness.shared.debug_dump import redact_history

        monkeypatch.setenv("AGENT_EVIDENCE_KEY", "evidence-hmac-key-value")
        monkeypatch.setenv("API_SERVER_KEY", "api-server-key-value")

        history = [
            {"role": "tool", "content": "AGENT_EVIDENCE_KEY=evidence-hmac-key-value"},
            {"role": "tool", "content": "X-API-Key: api-server-key-value"},
        ]
        serialised = str(redact_history(history, api_key=None))

        assert "evidence-hmac-key-value" not in serialised, "the evidence signing key left over HTTP"
        assert "api-server-key-value" not in serialised, "the API server key left over HTTP"


# Declared, not exempted (R-EGF-6): FastAPI's TestClient drives the app over a
# real loopback socket, so these genuinely need one. The declaration is visible
# here at the class rather than hidden in a global allow-list.
@pytest.mark.enable_socket
class TestToolUsingRunsReachTheClient:
    """Defect 4 (audit B3). Each case is one of the three shapes the audit
    reproduced a 500 on; the assistant/tool pair is what ``loop.py:166`` and
    ``dispatcher.py:130`` append on every tool call."""

    def _post(self, client: TestClient, key: str, history: list[dict[str, object]]):
        with patch("harness.api_server.main.MangoMASOrchestrator") as orchestrator_cls:
            instance = orchestrator_cls.return_value
            instance.execute_loop.return_value = _passing_outcome("PASS")
            instance.conversation_history = history
            return client.post("/api/orchestrate", json={"task": "x"}, headers={"X-API-Key": key})

    def test_assistant_tool_call_and_tool_result_round_trip(self, client: TestClient, server_key: str) -> None:
        history: list[dict[str, object]] = [
            {"role": "user", "content": "x"},
            {
                "role": "assistant",
                "content": None,
                "tool_calls": [{"id": "c1", "type": "function", "function": {"name": "read_file", "arguments": "{}"}}],
            },
            {"role": "tool", "tool_call_id": "c1", "name": "read_file", "content": "contents"},
            {"role": "assistant", "content": "PASS"},
        ]
        response = self._post(client, server_key, history)
        assert response.status_code == 200, response.text
        assert response.json()["history"] == history

    def test_empty_content_with_tool_calls_is_accepted(self, client: TestClient, server_key: str) -> None:
        """The audit's strengthening: a provider that sends ``""`` rather than
        ``null`` still failed, on the ``tool_calls`` list."""
        history: list[dict[str, object]] = [
            {"role": "assistant", "content": "", "tool_calls": [{"function": {"name": "f", "arguments": None}}]},
        ]
        assert self._post(client, server_key, history).status_code == 200

    def test_tool_result_for_a_call_without_id_is_accepted(self, client: TestClient, server_key: str) -> None:
        """``dispatcher.py`` writes ``tool_call_id: None`` when the provider
        sent no ``id``; that is history, not an error."""
        history: list[dict[str, object]] = [
            {"role": "tool", "tool_call_id": None, "name": "f", "content": "r"},
        ]
        response = self._post(client, server_key, history)
        assert response.status_code == 200
        assert response.json()["history"][0]["tool_call_id"] is None

    def test_an_unknown_role_is_still_refused_opaquely(self, client: TestClient, server_key: str) -> None:
        """Loosening to ``list[dict[str, Any]]`` would also have fixed the 500;
        the typed models are chosen because they keep refusing shapes the
        orchestrator never produces, without echoing them."""
        response = self._post(client, server_key, [{"role": "wizard", "content": "spell"}])
        assert response.status_code == 500
        assert response.json() == {"detail": "Internal orchestration error"}
        assert "wizard" not in response.text
