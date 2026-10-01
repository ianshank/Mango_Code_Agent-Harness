"""MG-E1 adapter edge-path coverage (OpenSandbox + SWE-ReX).

Split from test_mg_e1_backends.py to stay under limits.test_size_budget_lines
(700). Registry/selection/evidence/broker coverage remains in the sibling module.
"""

from __future__ import annotations

import io
from email.message import Message
from types import SimpleNamespace

import pytest

from harness.shared.governance.execution_backend import (
    ISOLATION_ENFORCED,
    ISOLATION_UNDETERMINED,
    ExecutionRequest,
)
from harness.shared.governance.opensandbox_backend import OpenSandboxBackend, _default_http
from harness.shared.governance.swerex_backend import SweRexBackend, grade_swerex_deployment
from harness.shared.governance.verdict import BROKER_BLOCKED, BROKER_FAILED, BROKER_SUCCESS


def _req(command: str = "echo hi") -> ExecutionRequest:
    return ExecutionRequest(
        command=command,
        workspace=None,
        cwd=None,
        timeout=5,
        max_output_bytes=1024,
        action="shell",
    )


def test_opensandbox_available_false_without_config() -> None:
    assert OpenSandboxBackend().available() is False


def test_opensandbox_available_probe_exception() -> None:
    def boom(*_a, **_k):
        raise RuntimeError("probe down")

    assert OpenSandboxBackend(base_url="http://example.test", http=boom).available() is False


def test_opensandbox_execute_blocked_without_base_url() -> None:
    backend = OpenSandboxBackend(use_isolated=True, require_enforced=False)
    result = backend.execute(_req())
    assert result.status == BROKER_BLOCKED
    assert "base_url" in (result.reason or "")


def test_opensandbox_http_error_exit_and_normalize() -> None:
    def http(method: str, url: str, body: bytes | None, timeout: float):
        if method == "POST":
            return 500, {"stdout": "x", "stderr": "", "exit_code": 0}
        return 200, {}

    backend = OpenSandboxBackend(
        base_url="http://example.test",
        use_isolated=False,
        http=http,
        capabilities_payload={"available": False},
    )
    result = backend.execute(_req())
    assert result.status == BROKER_FAILED
    assert result.exit_code == 1


def test_opensandbox_execute_exception_path() -> None:
    def boom(*_a, **_k):
        raise RuntimeError("exec boom")

    backend = OpenSandboxBackend(
        base_url="http://example.test",
        use_isolated=False,
        capabilities_payload={"available": False},
        http=boom,
    )
    result = backend.execute(_req())
    assert result.status == BROKER_FAILED
    assert "exec boom" in (result.reason or "")


def test_opensandbox_grade_undetermined_before_probe() -> None:
    backend = OpenSandboxBackend(base_url="http://example.test", use_isolated=True)
    assert backend.capabilities().filesystem_isolation == ISOLATION_UNDETERMINED


def test_opensandbox_probe_via_http_paths() -> None:
    def http_ok(method: str, url: str, body: bytes | None, timeout: float):
        return 200, {"isolation_available": True}

    backend = OpenSandboxBackend(base_url="http://example.test/", http=http_ok)
    assert backend.available() is True
    assert backend.capabilities().filesystem_isolation == ISOLATION_ENFORCED

    def http_bad(method: str, url: str, body: bytes | None, timeout: float):
        return 500, "nope"

    assert OpenSandboxBackend(base_url="http://example.test", http=http_bad).available() is False

    backend3 = OpenSandboxBackend(base_url="")
    backend3._http = http_ok
    assert backend3._probe_capabilities() == {}
    assert backend3._probe_ok is False


def test_opensandbox_session_create_failures() -> None:
    def http_no_id(method: str, url: str, body: bytes | None, timeout: float):
        if method == "POST" and url.endswith("/v1/isolated/session"):
            return 200, {"not_id": True}
        return 200, {"available": True}

    backend = OpenSandboxBackend(
        base_url="http://example.test",
        use_isolated=True,
        require_enforced=True,
        capabilities_payload={"available": True},
        http=http_no_id,
    )
    assert backend.execute(_req()).status == BROKER_FAILED

    def http_bad_code(method: str, url: str, body: bytes | None, timeout: float):
        if method == "POST" and url.endswith("/v1/isolated/session"):
            return 500, {"id": "x"}
        return 200, {}

    backend2 = OpenSandboxBackend(
        base_url="http://example.test",
        use_isolated=True,
        require_enforced=True,
        capabilities_payload={"available": True},
        http=http_bad_code,
    )
    assert backend2.execute(_req()).status == BROKER_FAILED


def test_opensandbox_delete_session_paths() -> None:
    calls: list[tuple] = []

    def tracking_http(*args, **_kwargs):
        calls.append(args)
        return 200, {}

    # Empty base_url must not issue HTTP.
    OpenSandboxBackend(base_url="", http=tracking_http)._delete_session("sess")
    assert calls == []

    boom_hits = {"n": 0}

    def boom(*_a, **_k):
        boom_hits["n"] += 1
        raise RuntimeError("delete failed")

    # HTTP failures are swallowed; delete remains best-effort.
    OpenSandboxBackend(base_url="http://example.test", http=boom)._delete_session("sess")
    assert boom_hits["n"] == 1

    calls.clear()
    OpenSandboxBackend(base_url="http://example.test", http=tracking_http)._delete_session("sess")
    assert len(calls) == 1
    assert calls[0][0] == "DELETE"
    assert "sess" in str(calls[0][1])


def test_opensandbox_normalize_payload_variants() -> None:
    assert OpenSandboxBackend._normalize_payload("raw-text") == ("raw-text", "", 0)
    assert OpenSandboxBackend._normalize_payload(123)[2] == 1


def test_opensandbox_default_http_success_and_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    import urllib.error as urllib_error

    class _Resp:
        status = 200

        def read(self) -> bytes:
            return b'{"ok": true}'

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    monkeypatch.setattr(
        "harness.shared.governance.opensandbox_backend.urllib.request.urlopen",
        lambda *a, **k: _Resp(),
    )
    code, payload = _default_http("GET", "http://example.test/x", None, 1.0)
    assert code == 200
    assert payload == {"ok": True}

    class _RespRaw:
        status = 200

        def read(self) -> bytes:
            return b"not-json"

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    monkeypatch.setattr(
        "harness.shared.governance.opensandbox_backend.urllib.request.urlopen",
        lambda *a, **k: _RespRaw(),
    )
    code, payload = _default_http("POST", "http://example.test/x", b"{}", 1.0)
    assert code == 200
    assert payload == "not-json"

    def raise_http(*_a, **_k):
        raise urllib_error.HTTPError(
            "http://example.test/x",
            404,
            "missing",
            Message(),
            io.BytesIO(b'{"error": "missing"}'),
        )

    monkeypatch.setattr(
        "harness.shared.governance.opensandbox_backend.urllib.request.urlopen",
        raise_http,
    )
    code, payload = _default_http("GET", "http://example.test/x", None, 1.0)
    assert code == 404
    assert isinstance(payload, dict)

    def raise_http_raw(*_a, **_k):
        raise urllib_error.HTTPError(
            "http://example.test/x",
            502,
            "bad",
            Message(),
            io.BytesIO(b"gateway"),
        )

    monkeypatch.setattr(
        "harness.shared.governance.opensandbox_backend.urllib.request.urlopen",
        raise_http_raw,
    )
    code, payload = _default_http("GET", "http://example.test/x", None, 1.0)
    assert code == 502
    assert payload == "gateway"


def test_swerex_grade_empty_and_unknown() -> None:
    assert grade_swerex_deployment("", probe_ok=True) == ISOLATION_UNDETERMINED
    assert grade_swerex_deployment(None, probe_ok=True) == ISOLATION_UNDETERMINED
    assert grade_swerex_deployment("WeirdRuntime", probe_ok=True) == ISOLATION_UNDETERMINED


def test_swerex_available_paths() -> None:
    def boom_factory():
        raise RuntimeError("no runtime")

    assert SweRexBackend(runtime_factory=boom_factory).available() is False

    backend = SweRexBackend(runtime_factory=lambda: SimpleNamespace())
    assert backend.available() is True
    assert backend._probe_result is True

    backend2 = SweRexBackend(
        runtime_factory=lambda: SimpleNamespace(),
        probe_alive=lambda _rt: True,
    )
    assert backend2.available() is True

    backend3 = SweRexBackend(
        runtime_factory=lambda: SimpleNamespace(),
        probe_alive=lambda _rt: (_ for _ in ()).throw(RuntimeError("probe fail")),
    )
    assert backend3.available() is False


def test_swerex_execute_runtime_unavailable() -> None:
    backend = SweRexBackend(
        deployment_class="LocalRuntime",
        runtime_factory=lambda: None,
        require_enforced=False,
    )
    result = backend.execute(_req())
    assert result.status == BROKER_BLOCKED
    assert "unavailable" in (result.reason or "")


def test_swerex_execute_require_enforced_after_probe() -> None:
    backend = SweRexBackend(
        deployment_class="DockerDeployment",
        runtime_factory=lambda: SimpleNamespace(
            execute=lambda command: SimpleNamespace(stdout="ok", stderr="", exit_code=0),
            close=lambda: None,
        ),
        probe_alive=lambda _rt: False,
        require_enforced=True,
    )
    backend._probe_result = True
    result = backend.execute(_req())
    assert result.status == BROKER_BLOCKED
    assert "after probe" in (result.reason or "")


def test_swerex_execute_exception_and_close_failure() -> None:
    class _RT:
        def execute(self, command: str):
            raise RuntimeError("exec blow")

        def close(self):
            raise RuntimeError("close blow")

    backend = SweRexBackend(
        deployment_class="LocalRuntime",
        runtime_factory=_RT,
        require_enforced=False,
    )
    assert backend.execute(_req()).status == BROKER_FAILED


def test_swerex_ensure_runtime_without_sdk() -> None:
    assert SweRexBackend(deployment_class="LocalRuntime")._ensure_runtime() is None


def test_swerex_ensure_runtime_with_fake_sdk(monkeypatch: pytest.MonkeyPatch) -> None:
    import sys
    import types

    abstract = types.ModuleType("swerex.runtime.abstract")

    class AbstractRuntime:
        pass

    abstract.AbstractRuntime = AbstractRuntime  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "swerex", types.ModuleType("swerex"))
    monkeypatch.setitem(sys.modules, "swerex.runtime", types.ModuleType("swerex.runtime"))
    monkeypatch.setitem(sys.modules, "swerex.runtime.abstract", abstract)
    assert SweRexBackend(deployment_class="LocalRuntime")._ensure_runtime() is None


def test_swerex_execute_async_variants() -> None:
    class KwOnly:
        async def execute(self, *, command: str, timeout: int = 0):
            return SimpleNamespace(stdout=command, stderr="", exit_code=0)

    backend = SweRexBackend(
        deployment_class="LocalRuntime",
        runtime_factory=KwOnly,
        require_enforced=False,
    )
    result = backend.execute(_req("kw"))
    assert result.status == BROKER_SUCCESS
    assert "kw" in result.stdout

    class NoExec:
        def close(self):
            return None

    backend2 = SweRexBackend(
        deployment_class="LocalRuntime",
        runtime_factory=NoExec,
        require_enforced=False,
    )
    assert backend2.execute(_req()).status == BROKER_FAILED


def test_swerex_close_none() -> None:
    backend = SweRexBackend(runtime_factory=lambda: None)
    sentinel = object()
    backend._runtime = sentinel
    # None runtime: early return, must not clear an unrelated held runtime.
    backend._close_runtime(None)
    assert backend._runtime is sentinel

    closed = {"n": 0}

    class _RT:
        def close(self) -> None:
            closed["n"] += 1

    rt = _RT()
    backend._runtime = rt
    backend._close_runtime(rt)
    assert closed["n"] == 1
    assert backend._runtime is None
