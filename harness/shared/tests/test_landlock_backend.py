"""Landlock isolation backend (R-AEI-13, C-AEI-3, AC-13, AC-16, AC-19)."""

from __future__ import annotations

import shlex
import subprocess
from pathlib import Path
from typing import Any

import pytest

from harness.shared.governance.evidence_record import build_execution_entry
from harness.shared.governance.execution_backend import ExecutionRequest, conforms_to_backend
from harness.shared.governance.landlock_backend import LandlockBackend
from harness.shared.governance.landlock_restrict import MIN_ABI_FOR_NET, apply_landlock
from harness.shared.governance.process_backend import ProcessBackend
from harness.shared.governance.sandbox_policy import SandboxPolicyError
from harness.shared.governance.verdict import BROKER_BLOCKED, BROKER_FAILED, BROKER_SUCCESS

pytestmark = pytest.mark.governance


def _request(workspace: Path, command: str, cwd: Path | None = None) -> ExecutionRequest:
    return ExecutionRequest(
        command=command,
        workspace=workspace,
        cwd=cwd if cwd is not None else workspace,
        timeout=8,
        max_output_bytes=4096,
        action="test_execute",
    )


def test_protocol_landlock_conforms() -> None:
    assert conforms_to_backend(LandlockBackend())


def test_isolated_backend_confines(tmp_path: Path) -> None:
    """AC-13: outside read/write fail when available; missing workspace is BLOCKED."""
    workspace = tmp_path / "ws"
    workspace.mkdir()
    (workspace / "inside.txt").write_text("in\n", encoding="utf-8")
    outside = tmp_path / "out"
    outside.mkdir()
    secret = outside / "secret.txt"
    secret.write_text("SECRET\n", encoding="utf-8")
    pwned = outside / "pwned.txt"
    backend = LandlockBackend()
    read_cmd = f"cat {shlex.quote(str(secret))}"
    write_cmd = f"printf x > {shlex.quote(str(pwned))}"
    if backend.available():
        read_result = backend.execute(_request(workspace, read_cmd))
        assert "SECRET" not in (read_result.stdout or "")
        assert read_result.status != BROKER_SUCCESS
        write_result = backend.execute(_request(workspace, write_cmd))
        assert write_result.status != BROKER_SUCCESS
        assert not pwned.exists()
        inside = backend.execute(_request(workspace, "cat inside.txt"))
        assert inside.status == BROKER_SUCCESS
        assert "in" in inside.stdout
    else:
        read_result = backend.execute(_request(workspace, read_cmd))
        assert read_result.status == BROKER_BLOCKED
        write_result = backend.execute(_request(workspace, write_cmd))
        assert write_result.status == BROKER_BLOCKED
    missing = backend.execute(
        ExecutionRequest(
            command="true",
            workspace=None,
            cwd=None,
            timeout=2,
            max_output_bytes=64,
            action="test_execute",
        )
    )
    assert missing.status == BROKER_BLOCKED
    assert "workspace" in (missing.reason or "")


def test_cwd_outside_workspace_is_blocked(tmp_path: Path) -> None:
    workspace = tmp_path / "ws"
    workspace.mkdir()
    other = tmp_path / "other"
    other.mkdir()
    result = LandlockBackend().execute(_request(workspace, "true", cwd=other))
    assert result.status == BROKER_BLOCKED
    assert "cwd" in (result.reason or "")


def test_backend_failure_blocks(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """AC-16: probe, compile, and attestation failure are BLOCKED; no process fallback."""
    spawned: list[str] = []

    def boom(self: Any, *args: Any, **kwargs: Any) -> Any:
        spawned.append("process")
        raise AssertionError("ProcessBackend must not run after isolation failure")

    monkeypatch.setattr(ProcessBackend, "execute", boom)
    monkeypatch.setattr(ProcessBackend, "run", boom)
    workspace = tmp_path / "ws"
    workspace.mkdir()
    probe_report = {
        "schema_version": 1,
        "lsm": {"state": "enforced", "names": ["landlock"]},
        "landlock_abi": {"state": "undetermined", "abi": None},
        "unprivileged_userns": {"state": "absent", "sysctls": {}},
        "container_runtimes": {"state": "absent", "reachable": []},
    }
    probe_backend = LandlockBackend(probe_report=probe_report)
    probe_result = probe_backend.execute(_request(workspace, "true"))
    assert probe_result.status == BROKER_BLOCKED
    assert "probe" in (probe_result.reason or "")

    def bad_compile() -> Any:
        raise SandboxPolicyError("injected compile failure")

    compile_backend = LandlockBackend(compiler=bad_compile)
    compile_result = compile_backend.execute(_request(workspace, "true"))
    assert compile_result.status == BROKER_BLOCKED
    assert "compilation" in (compile_result.reason or "")

    attest_backend = LandlockBackend(attest=lambda _caps: False)
    attest_result = attest_backend.execute(_request(workspace, "true"))
    assert attest_result.status == BROKER_BLOCKED
    if attest_backend.available():
        assert "attest" in (attest_result.reason or "")
    assert spawned == []


def test_sandbox_digest_unattestable(tmp_path: Path) -> None:
    """AC-19 guard: ProcessBackend never claims the fifth INV-13 digest."""
    backend = ProcessBackend()
    entry = build_execution_entry(
        command="true",
        outcome="SUCCESS",
        action="test_execute",
        exit_code=0,
        baseline={"a.py": "abc"},
        backend=backend,
    )
    assert entry.get("sandbox_attested") is False
    assert "sandbox_digest" not in entry
    lying = ProcessBackend(
        capability_probe={
            "filesystem_isolation": "enforced",
            "network_isolation": "enforced",
            "process_isolation": "enforced",
        }
    )
    lying_entry = build_execution_entry(
        command="true",
        outcome="SUCCESS",
        action="test_execute",
        exit_code=0,
        baseline={"a.py": "abc"},
        backend=lying,
    )
    assert lying_entry.get("sandbox_attested") is False
    assert "sandbox_digest" not in lying_entry


def test_landlock_success_records_sandbox_digest(tmp_path: Path) -> None:
    workspace = tmp_path / "ws"
    workspace.mkdir()
    backend = LandlockBackend()
    result = backend.execute(_request(workspace, "true"))
    entry = build_execution_entry(
        command="true",
        outcome=result.status,
        action="test_execute",
        exit_code=result.exit_code,
        baseline={"a.py": "abc"},
        backend=backend,
    )
    if result.status == BROKER_SUCCESS:
        assert entry["sandbox_attested"] is True
        assert entry["sandbox_digest"]
        assert backend.capabilities().filesystem_isolation == "enforced"
        assert backend.capabilities().network_isolation == "enforced"
        assert backend.capabilities().process_isolation == "unenforced"
    else:
        assert result.status == BROKER_BLOCKED
        assert entry.get("sandbox_attested") is False


def test_apply_landlock_rejects_missing_workspace(tmp_path: Path) -> None:
    with pytest.raises(OSError, match="not a directory"):
        apply_landlock(tmp_path / "missing", MIN_ABI_FOR_NET)


def test_apply_landlock_rejects_low_abi(tmp_path: Path) -> None:
    workspace = tmp_path / "ws"
    workspace.mkdir()
    with pytest.raises(OSError, match="MIN_ABI_FOR_NET"):
        apply_landlock(workspace, MIN_ABI_FOR_NET - 1)


def test_apply_landlock_rejects_unknown_machine(tmp_path: Path) -> None:
    workspace = tmp_path / "ws"
    workspace.mkdir()
    with pytest.raises(OSError, match="unsupported machine"):
        apply_landlock(workspace, MIN_ABI_FOR_NET, machine="sparc")


def test_unavailable_on_windows(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    import harness.shared.governance.landlock_backend as backend_mod

    monkeypatch.setattr(backend_mod.sys, "platform", "win32")
    backend = LandlockBackend()
    assert backend.available() is False
    workspace = tmp_path / "ws"
    workspace.mkdir()
    result = backend.execute(_request(workspace, "true"))
    assert result.status == BROKER_BLOCKED


def test_apply_landlock_with_injected_syscalls(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Cover the apply path without restricting the pytest process."""
    import os

    workspace = tmp_path / "ws"
    workspace.mkdir()
    calls: list[str] = []
    real_close = os.close

    def fake_close(fd: int) -> None:
        if fd == 11:
            return
        real_close(fd)

    monkeypatch.setattr(os, "close", fake_close)

    def fake_syscall(*_args: object, **_kwargs: object) -> int:
        calls.append("syscall")
        if calls.count("syscall") == 1:
            return 11
        return 0

    def fake_prctl(*_args: object, **_kwargs: object) -> int:
        calls.append("prctl")
        return 0

    apply_landlock(
        workspace,
        6,
        machine="x86_64",
        extra_ro=None,
        syscall=fake_syscall,
        prctl=fake_prctl,
    )
    assert "prctl" in calls
    assert calls.count("syscall") >= 3


def test_apply_landlock_create_failure(tmp_path: Path) -> None:
    workspace = tmp_path / "ws"
    workspace.mkdir()

    def boom(*_args: object, **_kwargs: object) -> int:
        return -1

    with pytest.raises(OSError, match="create_ruleset"):
        apply_landlock(workspace, MIN_ABI_FOR_NET, machine="x86_64", syscall=boom, extra_ro=())


def test_libc_missing_is_apply_error(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    import ctypes.util

    from harness.shared.governance import landlock_restrict as restrict

    workspace = tmp_path / "ws"
    workspace.mkdir()
    monkeypatch.setattr(ctypes.util, "find_library", lambda _name: None)
    with pytest.raises(OSError, match="libc not found"):
        restrict.apply_landlock(workspace, MIN_ABI_FOR_NET, machine="x86_64")


def test_libc_cdll_and_syscall_attr_failures(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    import ctypes
    import ctypes.util

    from harness.shared.governance import landlock_restrict as restrict

    workspace = tmp_path / "ws"
    workspace.mkdir()
    monkeypatch.setattr(ctypes.util, "find_library", lambda _name: "libc.so.6")

    def boom_cdll(*_a: object, **_k: object) -> object:
        raise OSError("nope")

    monkeypatch.setattr(ctypes, "CDLL", boom_cdll)
    with pytest.raises(OSError, match="libc load failed"):
        restrict.apply_landlock(workspace, MIN_ABI_FOR_NET, machine="x86_64")

    class Empty:
        pass

    monkeypatch.setattr(ctypes, "CDLL", lambda *_a, **_k: Empty())
    with pytest.raises(OSError, match="has no syscall"):
        restrict.apply_landlock(workspace, MIN_ABI_FOR_NET, machine="x86_64")


def test_apply_landlock_uname_and_ro_skips(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import os

    from harness.shared.governance import landlock_restrict as restrict

    workspace = tmp_path / "ws"
    workspace.mkdir()
    ro = tmp_path / "ro"
    ro.mkdir()

    class OsWithoutUname:
        def __getattr__(self, name: str) -> object:
            if name == "uname":
                raise AttributeError("uname")
            return getattr(os, name)

    monkeypatch.setattr(restrict, "os", OsWithoutUname())
    with pytest.raises(OSError, match="no uname"):
        apply_landlock(workspace, 6, extra_ro=(), syscall=lambda *_a, **_k: 0, prctl=lambda *_a, **_k: 0)

    monkeypatch.setattr(restrict, "os", os)
    real_close = os.close

    def fake_close(fd: int) -> None:
        if fd == 11:
            return
        real_close(fd)

    monkeypatch.setattr(os, "close", fake_close)
    n = {"n": 0}

    def fake_syscall(*_a: object, **_k: object) -> int:
        n["n"] += 1
        if n["n"] == 1:
            return 11
        if n["n"] == 3:
            return -1
        return 0

    class BoomPath:
        def resolve(self) -> Path:
            raise OSError("resolve failed")

    apply_landlock(
        workspace,
        6,
        extra_ro=(BoomPath(), tmp_path / "missing-dir", ro),  # type: ignore[arg-type]
        syscall=fake_syscall,
        prctl=lambda *_a, **_k: 0,
    )


def test_apply_prctl_and_restrict_failures(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import os

    workspace = tmp_path / "ws"
    workspace.mkdir()
    real_close = os.close

    def fake_close(fd: int) -> None:
        if fd == 11:
            return
        real_close(fd)

    monkeypatch.setattr(os, "close", fake_close)

    created_n = {"n": 0}

    def created(*_a: object, **_k: object) -> int:
        created_n["n"] += 1
        return 11 if created_n["n"] == 1 else 0

    with pytest.raises(OSError, match="PR_SET_NO_NEW_PRIVS"):
        apply_landlock(workspace, 6, machine="x86_64", extra_ro=(), syscall=created, prctl=lambda *_a, **_k: 1)

    restrict_n = {"n": 0}

    def then_restrict(*_a: object, **_k: object) -> int:
        restrict_n["n"] += 1
        if restrict_n["n"] == 1:
            return 11
        if restrict_n["n"] == 3:
            return -1
        return 0

    with pytest.raises(OSError, match="restrict_self"):
        apply_landlock(workspace, 6, machine="x86_64", extra_ro=(), syscall=then_restrict, prctl=lambda *_a, **_k: 0)


def test_apply_prctl_libc_missing(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    import ctypes.util
    import os

    workspace = tmp_path / "ws"
    workspace.mkdir()
    real_close = os.close

    def fake_close(fd: int) -> None:
        if fd == 11:
            return
        real_close(fd)

    monkeypatch.setattr(os, "close", fake_close)
    n = {"n": 0}

    def fake_syscall(*_a: object, **_k: object) -> int:
        n["n"] += 1
        return 11 if n["n"] == 1 else 0

    monkeypatch.setattr(ctypes.util, "find_library", lambda _name: None)
    with pytest.raises(OSError, match="libc not found for prctl"):
        apply_landlock(workspace, 6, machine="x86_64", extra_ro=(), syscall=fake_syscall)


def test_backend_timeout_and_apply_oserror(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Execute's timeout / spawn-error handlers must not depend on a live Landlock host."""
    workspace = tmp_path / "ws"
    workspace.mkdir()

    def timeout(*_a: object, **_k: object) -> object:
        raise subprocess.TimeoutExpired(cmd="true", timeout=1)

    timed = LandlockBackend(apply_fn=lambda *_a, **_k: None)
    monkeypatch.setattr(timed, "available", lambda: True)
    monkeypatch.setattr("harness.shared.governance.landlock_backend.subprocess.run", timeout)
    failed = timed.execute(_request(workspace, "true"))
    assert failed.status == BROKER_FAILED
    assert "timed out" in (failed.reason or "")

    def boom_run(*_a: object, **_k: object) -> object:
        raise OSError("confine failed")

    broken = LandlockBackend(apply_fn=lambda *_a, **_k: None)
    monkeypatch.setattr(broken, "available", lambda: True)
    monkeypatch.setattr("harness.shared.governance.landlock_backend.subprocess.run", boom_run)
    blocked = broken.execute(_request(workspace, "true"))
    assert blocked.status == BROKER_BLOCKED
    assert "apply failed" in (blocked.reason or "")

    def decode_error(*_a: object, **_k: object) -> object:
        raise UnicodeDecodeError("utf-8", b"\xff", 0, 1, "bad")

    odd = LandlockBackend(apply_fn=lambda *_a, **_k: None)
    monkeypatch.setattr(odd, "available", lambda: True)
    monkeypatch.setattr("harness.shared.governance.landlock_backend.subprocess.run", decode_error)
    crashed = odd.execute(_request(workspace, "true"))
    assert crashed.status == BROKER_BLOCKED
    assert "execute failed" in (crashed.reason or "")


def test_probe_field_shapes_and_stale_abi(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    workspace = tmp_path / "ws"
    workspace.mkdir()
    report: dict[str, object] = {
        "schema_version": 1,
        "lsm": {"state": "enforced", "names": ["landlock"]},
        "landlock_abi": "enforced",
        "unprivileged_userns": {"state": "absent", "sysctls": {}},
        "container_runtimes": {"state": "absent", "reachable": []},
    }
    backend = LandlockBackend(probe_report=report)
    assert backend.available() is False
    caps = backend.capabilities()
    assert caps.filesystem_isolation == "unenforced"

    bool_abi = dict(report)
    bool_abi["landlock_abi"] = {"state": "enforced", "abi": True}
    live = LandlockBackend(probe_report=bool_abi)
    assert live.available() is False
    unavailable = live.execute(_request(workspace, "true"))
    assert unavailable.status == BROKER_BLOCKED
    assert "unavailable" in (unavailable.reason or "")

    missing_abi = dict(report)
    missing_abi["landlock_abi"] = {"state": "enforced"}
    missing = LandlockBackend(probe_report=missing_abi)
    monkeypatch.setattr(missing, "available", lambda: True)
    result = missing.execute(_request(workspace, "true"))
    assert result.status == BROKER_BLOCKED
    assert "ABI missing" in (result.reason or "")


def test_workspace_resolve_oserror_is_blocked(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    workspace = tmp_path / "ws"
    workspace.mkdir()

    def boom_resolve(self: Path, strict: bool = False) -> Path:
        raise OSError("cannot resolve")

    backend = LandlockBackend(apply_fn=lambda *_a, **_k: None)
    monkeypatch.setattr(backend, "available", lambda: True)
    monkeypatch.setattr(Path, "resolve", boom_resolve)
    result = backend.execute(_request(workspace, "true"))
    assert result.status == BROKER_BLOCKED
    assert "unreadable" in (result.reason or "")


def test_policy_error_at_construction_blocks(tmp_path: Path) -> None:
    from harness.shared.policy_loader import PolicyError

    workspace = tmp_path / "ws"
    workspace.mkdir()

    def boom() -> Any:
        raise PolicyError("routing missing")

    backend = LandlockBackend(compiler=boom)
    result = backend.execute(_request(workspace, "true"))
    assert result.status == BROKER_BLOCKED
    assert "compilation" in (result.reason or "")


def test_missing_policy_object_blocks(tmp_path: Path) -> None:
    workspace = tmp_path / "ws"
    workspace.mkdir()
    backend = LandlockBackend(apply_fn=lambda *_a, **_k: None)
    backend._compile_error = None
    backend._policy = None
    result = backend.execute(_request(workspace, "true"))
    assert result.status == BROKER_BLOCKED
    assert "missing policy" in (result.reason or "")


def test_sandbox_fields_ignore_non_landlock_and_unenforced() -> None:
    class UnenforcedLandlock:
        name = "landlock"
        version = "1.0.0"

        def capabilities(self) -> Any:
            return type(
                "C",
                (),
                {
                    "filesystem_isolation": "enforced",
                    "network_isolation": "unenforced",
                    "process_isolation": "unenforced",
                },
            )()

    entry = build_execution_entry(
        command="true",
        outcome="SUCCESS",
        action="test_execute",
        exit_code=0,
        baseline={"a.py": "abc"},
        backend=UnenforcedLandlock(),
    )
    assert entry.get("sandbox_attested") is False
    assert "sandbox_digest" not in entry

    class Nameless:
        version = "0"

    nameless = build_execution_entry(
        command="true",
        outcome="SUCCESS",
        action="test_execute",
        exit_code=0,
        baseline={"a.py": "abc"},
        backend=Nameless(),
    )
    assert nameless.get("sandbox_attested") is False

    class StickyLandlock:
        name = "landlock"
        version = "1.0.0"

        def capabilities(self) -> Any:
            return type(
                "C",
                (),
                {
                    "filesystem_isolation": "enforced",
                    "network_isolation": "enforced",
                    "process_isolation": "unenforced",
                },
            )()

    reused = StickyLandlock()
    blocked = build_execution_entry(
        command="true",
        outcome=BROKER_BLOCKED,
        action="test_execute",
        exit_code=1,
        baseline={"a.py": "abc"},
        backend=reused,
    )
    assert blocked.get("sandbox_attested") is False
    assert "sandbox_digest" not in blocked
    ok = build_execution_entry(
        command="true",
        outcome=BROKER_SUCCESS,
        action="test_execute",
        exit_code=0,
        baseline={"a.py": "abc"},
        backend=reused,
    )
    assert ok["sandbox_attested"] is True
    assert ok["sandbox_digest"]


def test_apply_workspace_add_rule_failure(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import os

    workspace = tmp_path / "ws"
    workspace.mkdir()
    real_close = os.close

    def fake_close(fd: int) -> None:
        if fd == 11:
            return
        real_close(fd)

    monkeypatch.setattr(os, "close", fake_close)
    n = {"n": 0}

    def fake_syscall(*_a: object, **_k: object) -> int:
        n["n"] += 1
        return 11 if n["n"] == 1 else -1

    with pytest.raises(OSError, match="landlock_add_rule"):
        apply_landlock(workspace, 4, machine="x86_64", extra_ro=(), syscall=fake_syscall, prctl=lambda *_a, **_k: 0)


def test_libc_syscall_wrapper_and_abi_bits(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Drive ``_libc_syscall`` and ABI 4 vs 5 handled-access bits without the kernel."""
    import ctypes
    import ctypes.util
    import os

    workspace = tmp_path / "ws"
    workspace.mkdir()
    real_close = os.close

    def fake_close(fd: int) -> None:
        if fd == 11:
            return
        real_close(fd)

    monkeypatch.setattr(os, "close", fake_close)

    class FakeSyscall:
        restype = None
        n = 0

        def __call__(self, *_a: object, **_k: object) -> int:
            type(self).n += 1
            return 11 if type(self).n == 1 else 0

    class FakeLibc:
        def __init__(self) -> None:
            self.syscall = FakeSyscall()

    monkeypatch.setattr(ctypes.util, "find_library", lambda _n: "libc.so.6")
    monkeypatch.setattr(ctypes, "CDLL", lambda *_a, **_k: FakeLibc())
    FakeSyscall.n = 0
    apply_landlock(workspace, 4, machine="arm64", extra_ro=(), prctl=lambda *_a, **_k: 0)
    assert FakeSyscall.n >= 3
    FakeSyscall.n = 0
    apply_landlock(workspace, 5, machine="aarch64", extra_ro=(), prctl=lambda *_a, **_k: 0)
    assert FakeSyscall.n >= 3


def test_apply_prctl_from_injected_libc(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Cover the CDLL prctl load without calling the real PR_SET_NO_NEW_PRIVS."""
    import ctypes
    import ctypes.util
    import os

    workspace = tmp_path / "ws"
    workspace.mkdir()
    real_close = os.close

    def fake_close(fd: int) -> None:
        if fd == 11:
            return
        real_close(fd)

    monkeypatch.setattr(os, "close", fake_close)
    n = {"n": 0}

    def fake_syscall(*_a: object, **_k: object) -> int:
        n["n"] += 1
        return 11 if n["n"] == 1 else 0

    class FakeLibc:
        def prctl(self, *_a: object, **_k: object) -> int:
            return 0

    monkeypatch.setattr(ctypes.util, "find_library", lambda _n: "libc.so.6")
    monkeypatch.setattr(ctypes, "CDLL", lambda *_a, **_k: FakeLibc())
    apply_landlock(workspace, 6, machine="x86_64", extra_ro=(), syscall=fake_syscall)
    assert n["n"] >= 3
