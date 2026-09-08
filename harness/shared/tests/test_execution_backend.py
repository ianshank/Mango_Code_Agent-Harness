"""ExecutionBackend protocol, ProcessBackend adapter, and routing (AC-9, AC-10, AC-11, AC-17)."""

from __future__ import annotations

import ast
import json
from pathlib import Path

import pytest

from harness.shared.governance.execution_backend import (
    ExecutionRequest,
    conforms_to_backend,
)
from harness.shared.governance.process_backend import ProcessBackend
from harness.shared.policy_loader import PolicyError, execution_routing, load_policy
from harness.shared.tests._helpers import REPO

pytestmark = pytest.mark.governance

GOVERNANCE = REPO / "harness" / "shared" / "governance"

#: Existing spawners plus the process backend. New modules must not join this set
#: until they are the isolation backend or the capability probe (AC-17).
_SPAWN_ALLOWLIST = frozenset(
    {
        "process_backend.py",
        "attestation.py",
        "remotes.py",
        "pretooluse_guard.py",
        "check_secret_allowlist.py",
    }
)


def test_protocol_rejects_wrong_signature() -> None:
    """AC-9: right names, wrong signatures, rejected; ProcessBackend conforms."""

    class Wrong:
        name = "stub"
        version = "0"

        def execute(self, command: str) -> None:
            return None

        def capabilities(self) -> None:
            return None

        def available(self) -> bool:
            return True

    assert not conforms_to_backend(Wrong())
    assert conforms_to_backend(ProcessBackend())


def test_capabilities_three_state() -> None:
    """AC-10: requested network isolation the host cannot apply is unenforced."""
    backend = ProcessBackend(
        capability_probe={
            "requested_network_isolation": "enforced",
            "network_isolation": "unenforced",
            "filesystem_isolation": "unenforced",
            "process_isolation": "unenforced",
        }
    )
    caps = backend.capabilities()
    assert caps.network_isolation == "unenforced"
    assert caps.filesystem_isolation == "unenforced"
    assert caps.process_isolation == "unenforced"
    assert caps.version == backend.version
    request = ExecutionRequest(
        command="true",
        workspace=None,
        cwd=None,
        timeout=1,
        max_output_bytes=64,
        action="read",
    )
    # Adapter exists; RecordingBackend tests cover spawn. Here only the type.
    assert callable(backend.execute)
    assert request.command == "true"


def test_routing_block(tmp_path: Path) -> None:
    """AC-11: predating policies load; missing key and a third value are PolicyError."""
    predating = tmp_path / "old.json"
    predating.write_text("{}", encoding="utf-8")
    assert load_policy(predating) == {}
    assert execution_routing(predating) == "brokered"

    missing = tmp_path / "missing.json"
    missing.write_text(json.dumps({"execution": {"rationale": "no routing key"}}), encoding="utf-8")
    with pytest.raises(PolicyError, match="execution.routing"):
        execution_routing(missing)

    empty = tmp_path / "empty.json"
    empty.write_text(json.dumps({"execution": {}}), encoding="utf-8")
    with pytest.raises(PolicyError, match="execution.routing"):
        execution_routing(empty)

    third = tmp_path / "third.json"
    third.write_text(json.dumps({"execution": {"routing": "sandbox"}}), encoding="utf-8")
    with pytest.raises(PolicyError, match="brokered"):
        execution_routing(third)

    ok = tmp_path / "ok.json"
    ok.write_text(json.dumps({"execution": {"routing": "refuse"}}), encoding="utf-8")
    assert execution_routing(ok) == "refuse"


def _spawns(tree: ast.AST) -> bool:
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            if any(alias.name == "subprocess" or alias.name.startswith("subprocess.") for alias in node.names):
                return True
        if isinstance(node, ast.ImportFrom) and node.module == "subprocess":
            return True
        if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name):
            if node.value.id == "os" and node.attr in {
                "exec",
                "execl",
                "execle",
                "execlp",
                "execv",
                "execve",
                "execvp",
            }:
                return True
    return False


def test_refuse_routing_blocks_before_spawn(monkeypatch: pytest.MonkeyPatch) -> None:
    """Refuse routing is BLOCKED before spawn, independent of evidence."""
    from harness.shared.governance.broker import ExecutionBroker
    from harness.shared.governance.verdict import BROKER_BLOCKED
    from harness.shared.tests.test_governance_broker import IMPLEMENTER, RecordingBackend

    monkeypatch.setattr("harness.shared.governance.broker.execution_routing", lambda: "refuse")
    backend = RecordingBackend()
    broker = ExecutionBroker(backend=backend)
    result = broker.execute_command("echo hi", IMPLEMENTER)
    assert result.status == BROKER_BLOCKED
    assert "refuse" in (result.reason or "")
    assert backend.calls == []


def test_governance_no_direct_spawn() -> None:
    """AC-17: new governance modules must not spawn; existing spawners stay allowlisted."""
    offenders: list[str] = []
    for path in sorted(GOVERNANCE.glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        if _spawns(tree) and path.name not in _SPAWN_ALLOWLIST:
            offenders.append(path.name)
    assert not offenders, f"governance modules spawn outside the allowlist: {offenders}"
    for required in (
        "execution_backend.py",
        "evidence_manifest.py",
        "evidence_record.py",
    ):
        assert (GOVERNANCE / required).is_file(), required
        tree = ast.parse((GOVERNANCE / required).read_text(encoding="utf-8"))
        assert not _spawns(tree), f"{required} must not spawn"
