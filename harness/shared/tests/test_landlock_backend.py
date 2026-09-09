"""Landlock isolation backend (R-AEI-13, C-AEI-3, AC-13, AC-16, AC-19)."""

from __future__ import annotations

import shlex
import subprocess
from pathlib import Path
from typing import Any

import pytest

from harness.shared.governance.evidence_record import build_execution_entry
from harness.shared.governance.execution_backend import (
    ISOLATION_ENFORCED,
    ISOLATION_UNDETERMINED,
    ISOLATION_UNENFORCED,
    LANDLOCK_BACKEND_NAME,
    ExecutionRequest,
    conforms_to_backend,
)
from harness.shared.governance.landlock_backend import LandlockBackend
from harness.shared.governance.landlock_restrict import MIN_ABI_FOR_NET, apply_landlock
from harness.shared.governance.process_backend import DEFAULT_TIMEOUT_SEC, ProcessBackend
from harness.shared.governance.sandbox_policy import SandboxPolicyError
from harness.shared.governance.verdict import BROKER_BLOCKED, BROKER_FAILED, BROKER_SUCCESS
from harness.shared.tests._isolation_request import TEST_EXECUTE_ACTION, isolation_request
from harness.shared.tests._landlock_fakes import (
    FAKE_RULESET_FD,
    counting_syscall,
    failing_prctl,
    install_fake_ruleset_close,
    noop_prctl,
    probe_report,
)

pytestmark = pytest.mark.governance

#: UAPI ABI that added ioctl-dev bits; derived from the named net floor.
_ABI_IOCTL = MIN_ABI_FOR_NET + 1
_ABI_ABOVE_IOCTL = MIN_ABI_FOR_NET + 2


def _request(workspace: Path, command: str, cwd: Path | None = None) -> ExecutionRequest:
    return isolation_request(workspace, command, cwd=cwd)


def _entry(backend: Any, *, outcome: str, exit_code: int = 0) -> dict[str, Any]:
    return build_execution_entry(
        command="true",
        outcome=outcome,
        action=TEST_EXECUTE_ACTION,
        exit_code=exit_code,
        baseline={"a.py": "abc"},
        backend=backend,
    )


def test_protocol_landlock_conforms() -> None:
    assert conforms_to_backend(LandlockBackend())
    assert LandlockBackend.name == LANDLOCK_BACKEND_NAME
    assert {ISOLATION_ENFORCED, ISOLATION_UNENFORCED, ISOLATION_UNDETERMINED} == {
        "enforced",
        "unenforced",
        "undetermined",
    }


def test_fake_ruleset_fd_is_not_stdio() -> None:
    assert FAKE_RULESET_FD not in {0, 1, 2}
    assert FAKE_RULESET_FD > 256


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
    missing = backend.execute(isolation_request(None, "true"))
    assert missing.status == BROKER_BLOCKED
    assert "workspace" in (missing.reason or "")


def test_cwd_outside_workspace_is_blocked(tmp_path: Path) -> None:
    workspace = tmp_path / "ws"
    workspace.mkdir()
    other = tmp_path / "other"
    other.mkdir()
    result = LandlockBackend().execute(_request(workspace, "true", cwd=other))
    assert result.status == BROKER_BLOCKED
    assert "cwd is outside" in (result.reason or "")


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
    probe_backend = LandlockBackend(
        probe_report=probe_report(landlock_abi={"state": "undetermined", "abi": None}),
    )
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


def test_sandbox_digest_unattestable() -> None:
    """AC-19 guard: ProcessBackend never claims the fifth INV-13 digest."""
    backend = ProcessBackend()
    entry = _entry(backend, outcome=BROKER_SUCCESS)
    assert entry.get("sandbox_attested") is False
    assert "sandbox_digest" not in entry
    lying = ProcessBackend(
        capability_probe={
            "filesystem_isolation": ISOLATION_ENFORCED,
            "network_isolation": ISOLATION_ENFORCED,
            "process_isolation": ISOLATION_ENFORCED,
        }
    )
    lying_entry = _entry(lying, outcome=BROKER_SUCCESS)
    assert lying_entry.get("sandbox_attested") is False
    assert "sandbox_digest" not in lying_entry


def test_landlock_success_records_sandbox_digest(tmp_path: Path) -> None:
    workspace = tmp_path / "ws"
    workspace.mkdir()
    backend = LandlockBackend()
    result = backend.execute(_request(workspace, "true"))
    entry = _entry(backend, outcome=result.status, exit_code=result.exit_code)
    if result.status == BROKER_SUCCESS:
        assert entry["sandbox_attested"] is True
        assert entry["sandbox_digest"]
        caps = backend.capabilities()
        assert caps.filesystem_isolation == ISOLATION_ENFORCED
        assert caps.network_isolation == ISOLATION_ENFORCED
        assert caps.process_isolation == ISOLATION_UNENFORCED
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
    workspace = tmp_path / "ws"
    workspace.mkdir()
    install_fake_ruleset_close(monkeypatch)
    fake_syscall, n = counting_syscall()
    prctl_n = {"n": 0}

    def fake_prctl(*_args: object, **_kwargs: object) -> int:
        prctl_n["n"] += 1
        return 0

    apply_landlock(
        workspace,
        _ABI_ABOVE_IOCTL,
        machine="x86_64",
        extra_ro=None,
        syscall=fake_syscall,
        prctl=fake_prctl,
    )
    assert prctl_n["n"] == 1
    assert n["n"] >= 3


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
        apply_landlock(
            workspace,
            _ABI_ABOVE_IOCTL,
            extra_ro=(),
            syscall=lambda *_a, **_k: 0,
            prctl=noop_prctl,
        )

    monkeypatch.setattr(restrict, "os", os)
    install_fake_ruleset_close(monkeypatch)
    fake_syscall, _n = counting_syscall(fail_on=3)

    class BoomPath:
        def resolve(self) -> Path:
            raise OSError("resolve failed")

    apply_landlock(
        workspace,
        _ABI_ABOVE_IOCTL,
        extra_ro=(BoomPath(), tmp_path / "missing-dir", ro),  # type: ignore[arg-type]
        syscall=fake_syscall,
        prctl=noop_prctl,
    )


def test_apply_prctl_and_restrict_failures(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    workspace = tmp_path / "ws"
    workspace.mkdir()
    install_fake_ruleset_close(monkeypatch)
    created, _n = counting_syscall()
    with pytest.raises(OSError, match="PR_SET_NO_NEW_PRIVS"):
        apply_landlock(
            workspace,
            _ABI_ABOVE_IOCTL,
            machine="x86_64",
            extra_ro=(),
            syscall=created,
            prctl=failing_prctl,
        )
    then_restrict, _m = counting_syscall(fail_on=3)
    with pytest.raises(OSError, match="restrict_self"):
        apply_landlock(
            workspace,
            _ABI_ABOVE_IOCTL,
            machine="x86_64",
            extra_ro=(),
            syscall=then_restrict,
            prctl=noop_prctl,
        )


def test_apply_prctl_libc_missing(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    import ctypes.util

    workspace = tmp_path / "ws"
    workspace.mkdir()
    install_fake_ruleset_close(monkeypatch)
    fake_syscall, _n = counting_syscall()
    monkeypatch.setattr(ctypes.util, "find_library", lambda _name: None)
    with pytest.raises(OSError, match="libc not found for prctl"):
        apply_landlock(
            workspace,
            _ABI_ABOVE_IOCTL,
            machine="x86_64",
            extra_ro=(),
            syscall=fake_syscall,
        )


def test_backend_timeout_and_apply_oserror(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Execute's timeout / spawn-error handlers must not depend on a live Landlock host."""
    workspace = tmp_path / "ws"
    workspace.mkdir()
    run_mod = "harness.shared.governance.landlock_backend.subprocess.run"

    def timeout(*_a: object, **_k: object) -> object:
        raise subprocess.TimeoutExpired(cmd="true", timeout=DEFAULT_TIMEOUT_SEC)

    timed = LandlockBackend(apply_fn=lambda *_a, **_k: None)
    monkeypatch.setattr(timed, "available", lambda: True)
    monkeypatch.setattr(run_mod, timeout)
    failed = timed.execute(_request(workspace, "true"))
    assert failed.status == BROKER_FAILED
    assert "timed out" in (failed.reason or "")

    def boom_run(*_a: object, **_k: object) -> object:
        raise OSError("confine failed")

    broken = LandlockBackend(apply_fn=lambda *_a, **_k: None)
    monkeypatch.setattr(broken, "available", lambda: True)
    monkeypatch.setattr(run_mod, boom_run)
    blocked = broken.execute(_request(workspace, "true"))
    assert blocked.status == BROKER_BLOCKED
    assert "apply failed" in (blocked.reason or "")

    def decode_error(*_a: object, **_k: object) -> object:
        raise UnicodeDecodeError("utf-8", b"\xff", 0, 1, "bad")

    odd = LandlockBackend(apply_fn=lambda *_a, **_k: None)
    monkeypatch.setattr(odd, "available", lambda: True)
    monkeypatch.setattr(run_mod, decode_error)
    crashed = odd.execute(_request(workspace, "true"))
    assert crashed.status == BROKER_BLOCKED
    assert "execute failed" in (crashed.reason or "")


def test_probe_field_shapes_and_stale_abi(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    workspace = tmp_path / "ws"
    workspace.mkdir()
    backend = LandlockBackend(probe_report=probe_report(landlock_abi=ISOLATION_ENFORCED))
    assert backend.available() is False
    assert backend.capabilities().filesystem_isolation == ISOLATION_UNENFORCED

    live = LandlockBackend(
        probe_report=probe_report(landlock_abi={"state": ISOLATION_ENFORCED, "abi": True}),
    )
    assert live.available() is False
    unavailable = live.execute(_request(workspace, "true"))
    assert unavailable.status == BROKER_BLOCKED
    assert "unavailable" in (unavailable.reason or "")

    missing = LandlockBackend(
        probe_report=probe_report(landlock_abi={"state": ISOLATION_ENFORCED}),
    )
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
    assert "workspace unreadable" in (result.reason or "")


def test_cwd_resolve_oserror_is_unreadable_not_outside(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """A failed cwd resolve is BLOCKED as unreadable, not 'outside' or apply-failed."""
    workspace = tmp_path / "ws"
    workspace.mkdir()
    nested = workspace / "nested"
    nested.mkdir()
    real_resolve = Path.resolve

    def selective(self: Path, strict: bool = False) -> Path:
        if self == nested:
            raise OSError("cannot resolve cwd")
        return real_resolve(self, strict=strict)

    backend = LandlockBackend(apply_fn=lambda *_a, **_k: None)
    monkeypatch.setattr(backend, "available", lambda: True)
    monkeypatch.setattr(Path, "resolve", selective)
    result = backend.execute(_request(workspace, "true", cwd=nested))
    assert result.status == BROKER_BLOCKED
    reason = result.reason or ""
    assert "cwd unreadable" in reason
    assert "outside" not in reason
    assert "apply failed" not in reason


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
        name = LANDLOCK_BACKEND_NAME
        version = "1.0.0"

        def capabilities(self) -> Any:
            return type(
                "C",
                (),
                {
                    "filesystem_isolation": ISOLATION_ENFORCED,
                    "network_isolation": ISOLATION_UNENFORCED,
                    "process_isolation": ISOLATION_UNENFORCED,
                },
            )()

    entry = _entry(UnenforcedLandlock(), outcome=BROKER_SUCCESS)
    assert entry.get("sandbox_attested") is False
    assert "sandbox_digest" not in entry

    class Nameless:
        version = "0"

    nameless = _entry(Nameless(), outcome=BROKER_SUCCESS)
    assert nameless.get("sandbox_attested") is False

    class StickyLandlock:
        name = LANDLOCK_BACKEND_NAME
        version = "1.0.0"

        def capabilities(self) -> Any:
            return type(
                "C",
                (),
                {
                    "filesystem_isolation": ISOLATION_ENFORCED,
                    "network_isolation": ISOLATION_ENFORCED,
                    "process_isolation": ISOLATION_UNENFORCED,
                },
            )()

    reused = StickyLandlock()
    blocked = _entry(reused, outcome=BROKER_BLOCKED, exit_code=1)
    assert blocked.get("sandbox_attested") is False
    assert "sandbox_digest" not in blocked
    ok = _entry(reused, outcome=BROKER_SUCCESS)
    assert ok["sandbox_attested"] is True
    assert ok["sandbox_digest"]


def test_apply_workspace_add_rule_failure(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    workspace = tmp_path / "ws"
    workspace.mkdir()
    install_fake_ruleset_close(monkeypatch)
    fake_syscall, _n = counting_syscall(fail_on=2)
    with pytest.raises(OSError, match="landlock_add_rule"):
        apply_landlock(
            workspace,
            MIN_ABI_FOR_NET,
            machine="x86_64",
            extra_ro=(),
            syscall=fake_syscall,
            prctl=noop_prctl,
        )


def test_libc_syscall_wrapper_and_abi_bits(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Drive ``_libc_syscall`` and net-floor vs ioctl-dev bits without the kernel."""
    import ctypes
    import ctypes.util

    workspace = tmp_path / "ws"
    workspace.mkdir()
    install_fake_ruleset_close(monkeypatch)

    class FakeSyscall:
        restype = None
        n = 0

        def __call__(self, *_a: object, **_k: object) -> int:
            type(self).n += 1
            return FAKE_RULESET_FD if type(self).n == 1 else 0

    class FakeLibc:
        def __init__(self) -> None:
            self.syscall = FakeSyscall()

    monkeypatch.setattr(ctypes.util, "find_library", lambda _n: "libc.so.6")
    monkeypatch.setattr(ctypes, "CDLL", lambda *_a, **_k: FakeLibc())
    FakeSyscall.n = 0
    apply_landlock(workspace, MIN_ABI_FOR_NET, machine="arm64", extra_ro=(), prctl=noop_prctl)
    assert FakeSyscall.n >= 3
    FakeSyscall.n = 0
    apply_landlock(workspace, _ABI_IOCTL, machine="aarch64", extra_ro=(), prctl=noop_prctl)
    assert FakeSyscall.n >= 3


def test_apply_prctl_from_injected_libc(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Cover the CDLL prctl load without calling the real PR_SET_NO_NEW_PRIVS."""
    import ctypes
    import ctypes.util

    workspace = tmp_path / "ws"
    workspace.mkdir()
    install_fake_ruleset_close(monkeypatch)
    fake_syscall, n = counting_syscall()

    class FakeLibc:
        def prctl(self, *_a: object, **_k: object) -> int:
            return 0

    monkeypatch.setattr(ctypes.util, "find_library", lambda _n: "libc.so.6")
    monkeypatch.setattr(ctypes, "CDLL", lambda *_a, **_k: FakeLibc())
    apply_landlock(
        workspace,
        _ABI_ABOVE_IOCTL,
        machine="x86_64",
        extra_ro=(),
        syscall=fake_syscall,
    )
    assert n["n"] >= 3
