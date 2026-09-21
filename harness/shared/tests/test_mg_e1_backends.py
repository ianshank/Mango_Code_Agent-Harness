"""MG-E1 SWE-ReX + OpenSandbox adapters and fail-closed registry.

R-AEI-10 cross-links: harness/CONTRACT.md INV-13; DEC-010; DEC-069;
docs/specs/attested-execution-isolation.md R-AEI-10; OpenSpec tasks §12.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from harness.shared.governance.backend_registry import (
    BackendSelectionError,
    assert_isolation_requirement,
    resolve_backend,
)
from harness.shared.governance.evidence_record import _sandbox_fields
from harness.shared.governance.execution_backend import (
    ISOLATION_ENFORCED,
    ISOLATION_UNDETERMINED,
    ISOLATION_UNENFORCED,
    OPEN_SANDBOX_BACKEND_NAME,
    SWE_REX_BACKEND_NAME,
    BackendCapabilities,
    ExecutionRequest,
)
from harness.shared.governance.opensandbox_backend import OpenSandboxBackend
from harness.shared.governance.process_backend import ProcessBackend
from harness.shared.governance.swerex_backend import SweRexBackend, grade_swerex_deployment
from harness.shared.governance.verdict import BROKER_BLOCKED, BROKER_SUCCESS


def _req(command: str = "echo hi") -> ExecutionRequest:
    return ExecutionRequest(
        command=command,
        workspace=None,
        cwd=None,
        timeout=5,
        max_output_bytes=1024,
        action="shell",
    )


def test_default_resolve_is_process() -> None:
    backend = resolve_backend(backend_id="process", factories={"process": ProcessBackend})
    assert isinstance(backend, ProcessBackend)
    assert backend.name == "process"


def test_unknown_backend_id_denies() -> None:
    with pytest.raises(BackendSelectionError, match="unknown"):
        resolve_backend(backend_id="not-a-backend", factories={"process": ProcessBackend})


def test_swerex_local_never_enforced() -> None:
    assert grade_swerex_deployment("LocalRuntime", probe_ok=True) == ISOLATION_UNENFORCED
    assert grade_swerex_deployment("LocalDeployment", probe_ok=False) == ISOLATION_UNENFORCED


def test_swerex_docker_needs_probe_for_enforced() -> None:
    assert grade_swerex_deployment("DockerDeployment", probe_ok=None) == ISOLATION_UNDETERMINED
    assert grade_swerex_deployment("DockerDeployment", probe_ok=False) == ISOLATION_UNDETERMINED
    assert grade_swerex_deployment("DockerDeployment", probe_ok=True) == ISOLATION_ENFORCED


def test_swerex_require_enforced_blocks_when_undetermined() -> None:
    backend = SweRexBackend(
        deployment_class="DockerDeployment",
        runtime_factory=lambda: SimpleNamespace(
            execute=lambda command: SimpleNamespace(stdout="ok", stderr="", exit_code=0),
            is_alive=lambda: False,
            close=lambda: None,
        ),
        probe_alive=lambda _rt: False,
        require_enforced=True,
    )
    result = backend.execute(_req())
    assert result.status == BROKER_BLOCKED
    assert backend.capabilities().filesystem_isolation != ISOLATION_ENFORCED


def test_swerex_async_bridge_executes_and_closes() -> None:
    closed = {"n": 0}

    class _RT:
        async def execute(self, command: str):
            return SimpleNamespace(stdout=f"out:{command}", stderr="", exit_code=0)

        async def is_alive(self):
            return True

        async def close(self):
            closed["n"] += 1

    backend = SweRexBackend(
        deployment_class="LocalRuntime",
        runtime_factory=_RT,
        require_enforced=False,
    )
    result = backend.execute(_req("hello"))
    assert result.status == BROKER_SUCCESS
    assert "hello" in result.stdout
    assert closed["n"] == 1
    assert backend.capabilities().filesystem_isolation == ISOLATION_UNENFORCED


def test_opensandbox_non_isolated_is_unenforced() -> None:
    def http(method: str, url: str, body: bytes | None, timeout: float):
        return 200, {"stdout": "ok", "stderr": "", "exit_code": 0}

    backend = OpenSandboxBackend(
        base_url="http://example.test",
        use_isolated=False,
        http=http,
        capabilities_payload={"available": False},
    )
    assert backend.capabilities().filesystem_isolation == ISOLATION_UNENFORCED
    result = backend.execute(_req())
    assert result.status == BROKER_SUCCESS


def test_opensandbox_require_enforced_blocks_without_probe() -> None:
    backend = OpenSandboxBackend(
        base_url="http://example.test",
        use_isolated=True,
        require_enforced=True,
        capabilities_payload={"available": False},
        http=lambda *a, **k: (500, {}),
    )
    result = backend.execute(_req())
    assert result.status == BROKER_BLOCKED


def test_opensandbox_enforced_path_with_probe() -> None:
    sessions: list[str] = []

    def http(method: str, url: str, body: bytes | None, timeout: float):
        if method == "POST" and url.endswith("/v1/isolated/session"):
            return 200, {"id": "sess-1"}
        if method == "POST" and "/run" in url:
            return 200, {"stdout": "sandboxed", "stderr": "", "exit_code": 0}
        if method == "DELETE":
            sessions.append(url)
            return 200, {}
        return 404, {}

    backend = OpenSandboxBackend(
        base_url="http://example.test",
        use_isolated=True,
        require_enforced=True,
        capabilities_payload={"available": True},
        http=http,
    )
    assert backend.available() is True
    assert backend.capabilities().filesystem_isolation == ISOLATION_ENFORCED
    result = backend.execute(_req())
    assert result.status == BROKER_SUCCESS
    assert result.stdout == "sandboxed"
    assert sessions, "session must be deleted on exit"


def test_assert_isolation_requirement_fail_closed() -> None:
    backend = SweRexBackend(deployment_class="DockerDeployment", probe_alive=lambda _r: False)
    backend.available()
    with pytest.raises(BackendSelectionError, match="BROKER_BLOCKED"):
        assert_isolation_requirement(backend, required=ISOLATION_ENFORCED)


def test_rae10_evidence_rejects_available_only_claim() -> None:
    """R-AEI-10: available() true without enforced capabilities is not attested."""

    class Lying:
        name = SWE_REX_BACKEND_NAME
        version = "1.0.0"

        def available(self) -> bool:
            return True

        def capabilities(self) -> BackendCapabilities:
            return BackendCapabilities(
                filesystem_isolation=ISOLATION_UNENFORCED,
                network_isolation=ISOLATION_UNENFORCED,
                process_isolation=ISOLATION_UNENFORCED,
                version=self.version,
            )

    fields = _sandbox_fields(Lying(), BROKER_SUCCESS)
    assert fields.get("sandbox_attested") is False


def test_rae10_evidence_attests_enforced_swerex() -> None:
    class Honest:
        name = SWE_REX_BACKEND_NAME
        version = "1.0.0"

        def capabilities(self) -> BackendCapabilities:
            return BackendCapabilities(
                filesystem_isolation=ISOLATION_ENFORCED,
                network_isolation=ISOLATION_UNDETERMINED,
                process_isolation=ISOLATION_UNDETERMINED,
                version=self.version,
            )

    fields = _sandbox_fields(Honest(), BROKER_SUCCESS)
    assert fields.get("sandbox_attested") is True
    assert "sandbox_digest" in fields


def test_rae10_evidence_attests_enforced_opensandbox() -> None:
    class Honest:
        name = OPEN_SANDBOX_BACKEND_NAME
        version = "1.0.0"

        def capabilities(self) -> BackendCapabilities:
            return BackendCapabilities(
                filesystem_isolation=ISOLATION_ENFORCED,
                network_isolation=ISOLATION_UNDETERMINED,
                process_isolation=ISOLATION_UNDETERMINED,
                version=self.version,
            )

    assert _sandbox_fields(Honest(), BROKER_SUCCESS).get("sandbox_attested") is True


def test_evidence_entry_additive_schema_and_rae10_crosslinks() -> None:
    """OpenSpec tasks §12: R-AEI-10 + additive evidence fields (Data Steward)."""
    from harness.shared.governance.evidence_record import build_execution_entry

    class EnforcedSweRex:
        name = SWE_REX_BACKEND_NAME
        version = "1.0.0"

        def capabilities(self) -> BackendCapabilities:
            return BackendCapabilities(
                filesystem_isolation=ISOLATION_ENFORCED,
                network_isolation=ISOLATION_UNDETERMINED,
                process_isolation=ISOLATION_UNDETERMINED,
                version=self.version,
            )

    entry = build_execution_entry(
        command="echo ok",
        outcome=BROKER_SUCCESS,
        action="shell",
        exit_code=0,
        baseline={"a": "b"},
        backend=EnforcedSweRex(),
        node_ids=(),
    )
    # Legacy digests remain present (no breaking mutation).
    for key in ("policy_digest", "source_digest", "backend_name", "backend_version", "test_digest"):
        assert key in entry
    # Additive MG-E1 fields.
    assert entry["evidence_schema_version"] == 1
    assert entry["filesystem_isolation"] == ISOLATION_ENFORCED
    assert entry["sandbox_attested"] is True
    # R-AEI-10: available()-only lie still not attested (covered above); enforced path ok.
