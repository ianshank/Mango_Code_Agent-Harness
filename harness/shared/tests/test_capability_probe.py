"""Host-inventory probe for INV-13 isolation primitives (R-AEI-12 / AC-12).

Named functions are the matrix AC-12 collects. Injected hosts keep the suite
deterministic; ``test_stdout_under_json_flag_is_loadable`` is the live CLI.
"""

from __future__ import annotations

import ast
import copy
import errno
import json
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

import pytest

from harness.shared.governance import capability_probe
from harness.shared.tests._helpers import REPO

pytestmark = pytest.mark.governance

_MODULE = REPO / "harness" / "shared" / "governance" / "capability_probe.py"

_LEGAL = capability_probe.LEGAL_STATES


def _enosys(_nr: int) -> tuple[int, int]:
    return -1, errno.ENOSYS


def _host(
    *,
    platform: str = "linux",
    machine: str = "x86_64",
    lsm_path: Path | None = None,
    userns_files: Mapping[str, Path] | None = None,
    landlock_syscall: Callable[[int], tuple[int, int]] = _enosys,
    which: Callable[[str], str | None] | None = None,
    runtime_sockets: Mapping[str, Path] | None = None,
) -> dict[str, Any]:
    """A fully determined host: LSM missing, Landlock ENOSYS, no userns, no runtimes."""
    missing = Path("/nonexistent/capability-probe")
    return capability_probe.probe(
        platform=platform,
        machine=machine,
        lsm_path=lsm_path if lsm_path is not None else missing,
        userns_files={} if userns_files is None else userns_files,
        landlock_syscall=landlock_syscall,
        which=(lambda _name: None) if which is None else which,
        runtime_sockets={} if runtime_sockets is None else runtime_sockets,
    )


def _determined() -> dict[str, Any]:
    return {
        "schema_version": 1,
        "lsm": {"state": "enforced", "names": ["capability"]},
        "landlock_abi": {"state": "absent", "abi": None},
        "unprivileged_userns": {"state": "absent", "sysctls": {}},
        "container_runtimes": {"state": "absent", "reachable": []},
    }


class _DeniedText:
    """Duck-typed path whose ``read_text`` is EACCES."""

    def read_text(self, encoding: str = "utf-8") -> str:
        raise PermissionError("denied")


class _DeniedSock:
    """Duck-typed path whose ``exists`` is EACCES."""

    def exists(self) -> bool:
        raise OSError(errno.EACCES, "denied")


def test_json_states_are_the_three_legal_words() -> None:
    report = _host()
    for name in capability_probe._FIELDS:
        state = report[name]["state"]
        assert state in _LEGAL
        assert state != "unenforced"
    undetermined = _host(machine="riscv64")
    assert undetermined["landlock_abi"]["state"] == "undetermined"
    assert undetermined["landlock_abi"]["state"] in _LEGAL


def test_missing_lsm_file_is_absent_exit_zero(tmp_path: Path) -> None:
    report = _host(lsm_path=tmp_path / "missing-lsm")
    assert report["lsm"] == {"state": "absent", "names": []}
    assert capability_probe.exit_status(report) == 0


def test_eacces_on_lsm_file_is_undetermined_exit_one() -> None:
    report = _host(lsm_path=_DeniedText())  # type: ignore[arg-type]
    assert report["lsm"] == {"state": "undetermined", "names": []}
    assert capability_probe.exit_status(report) == 1


def test_landlock_enosys_is_absent() -> None:
    report = _host(landlock_syscall=_enosys)
    assert report["landlock_abi"] == {"state": "absent", "abi": None}
    assert capability_probe.exit_status(report) == 0


def test_landlock_abi_integer_is_enforced() -> None:
    report = _host(landlock_syscall=lambda _nr: (6, 0))
    assert report["landlock_abi"] == {"state": "enforced", "abi": 6}
    assert capability_probe.exit_status(report) == 0


def test_missing_userns_sysctl_is_absent(tmp_path: Path) -> None:
    files = {"unprivileged_userns_clone": tmp_path / "no-such-sysctl"}
    report = _host(userns_files=files)
    assert report["unprivileged_userns"] == {"state": "absent", "sysctls": {}}
    assert capability_probe.exit_status(report) == 0


def test_no_container_runtime_is_absent(tmp_path: Path) -> None:
    sockets = {
        "docker": tmp_path / "docker.sock",
        "podman": tmp_path / "podman.sock",
    }
    report = _host(which=lambda _name: None, runtime_sockets=sockets)
    assert report["container_runtimes"] == {"state": "absent", "reachable": []}
    assert capability_probe.exit_status(report) == 0


def test_windows_all_fields_absent(monkeypatch: pytest.MonkeyPatch) -> None:
    win = capability_probe.probe(platform="win32")
    for name in capability_probe._FIELDS:
        assert win[name]["state"] == "absent"
    assert capability_probe.exit_status(win) == 0
    monkeypatch.setattr(capability_probe.os, "uname", None, raising=False)
    hidden = capability_probe.probe(platform="linux")
    for name in capability_probe._FIELDS:
        assert hidden[name]["state"] == "absent"
    assert capability_probe.exit_status(hidden) == 0


def test_unknown_machine_landlock_is_undetermined_exit_one() -> None:
    report = _host(machine="riscv64")
    assert report["landlock_abi"] == {"state": "undetermined", "abi": None}
    assert report["lsm"]["state"] == "absent"
    assert report["unprivileged_userns"]["state"] == "absent"
    assert report["container_runtimes"]["state"] == "absent"
    assert capability_probe.exit_status(report) == 1


def test_stdout_under_json_flag_is_loadable(capsys: pytest.CaptureFixture[str]) -> None:
    code = capability_probe.main(["--json"])
    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert payload["schema_version"] == 1
    for name in capability_probe._FIELDS:
        assert payload[name]["state"] in _LEGAL
        assert payload[name]["state"] != "unenforced"
    assert code == capability_probe.exit_status(payload)
    assert captured.out.lstrip().startswith("{")
    capability_probe.main([])
    quiet = capsys.readouterr()
    assert quiet.out == ""


def test_undetermined_is_the_only_nonzero_exit() -> None:
    """Mutation: treating undetermined as exit 0 must turn this test red."""
    base = _determined()
    assert capability_probe.exit_status(base) == 0
    for name in capability_probe._FIELDS:
        mutated = copy.deepcopy(base)
        mutated[name]["state"] = "undetermined"
        assert capability_probe.exit_status(mutated) == 1, name
        mutated[name]["state"] = "absent"
        assert capability_probe.exit_status(mutated) == 0, name
        mutated[name]["state"] = "enforced"
        assert capability_probe.exit_status(mutated) == 0, name
    illegal = copy.deepcopy(base)
    illegal["lsm"]["state"] = "unenforced"
    assert capability_probe.exit_status(illegal) == 1
    missing = copy.deepcopy(base)
    del missing["lsm"]
    assert capability_probe.exit_status(missing) == 1


def test_module_does_not_reference_restrict_self_or_subprocess() -> None:
    source = _MODULE.read_text(encoding="utf-8")
    tree = ast.parse(source)
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            imported.add((node.module or "").split(".")[0])
            if node.module and node.module.startswith("harness"):
                pytest.fail(f"probe imports first-party module {node.module}")
    assert "subprocess" not in imported
    names = {node.id for node in ast.walk(tree) if isinstance(node, ast.Name)}
    attrs = {node.attr for node in ast.walk(tree) if isinstance(node, ast.Attribute)}
    assert "landlock_restrict_self" not in names
    assert "landlock_add_rule" not in names
    assert "landlock_restrict_self" not in attrs
    assert "landlock_add_rule" not in attrs
    assert "Popen" not in names
    assert "execve" not in attrs


def test_present_lsm_names_are_enforced(tmp_path: Path) -> None:
    path = tmp_path / "lsm"
    path.write_text("capability,landlock,selinux\n", encoding="utf-8")
    report = _host(lsm_path=path)
    assert report["lsm"]["state"] == "enforced"
    assert report["lsm"]["names"] == ["capability", "landlock", "selinux"]


def test_userns_eacces_is_undetermined() -> None:
    report = _host(userns_files={"max_user_namespaces": _DeniedText()})  # type: ignore[dict-item]
    assert report["unprivileged_userns"]["state"] == "undetermined"
    assert capability_probe.exit_status(report) == 1


def test_userns_present_file_is_enforced(tmp_path: Path) -> None:
    path = tmp_path / "max_user_namespaces"
    path.write_text("64035\n", encoding="utf-8")
    report = _host(userns_files={"max_user_namespaces": path})
    assert report["unprivileged_userns"] == {
        "state": "enforced",
        "sysctls": {"max_user_namespaces": "64035"},
    }


def test_landlock_eperm_is_undetermined() -> None:
    report = _host(landlock_syscall=lambda _nr: (-1, errno.EPERM))
    assert report["landlock_abi"]["state"] == "undetermined"


def test_landlock_enotsup_is_absent() -> None:
    report = _host(landlock_syscall=lambda _nr: (-1, errno.ENOTSUP))
    assert report["landlock_abi"]["state"] == "absent"


def test_landlock_aarch64_uses_known_syscall() -> None:
    seen: list[int] = []

    def capture(nr: int) -> tuple[int, int]:
        seen.append(nr)
        return 4, 0

    report = _host(machine="aarch64", landlock_syscall=capture)
    assert seen == [444]
    assert report["landlock_abi"]["state"] == "enforced"


def test_missing_libc_is_landlock_absent(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(capability_probe.ctypes.util, "find_library", lambda _name: None)
    assert capability_probe._live_landlock_abi(444) == (-1, errno.ENOSYS)


def test_unloadable_libc_is_landlock_absent(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(capability_probe.ctypes.util, "find_library", lambda _name: "libc.so.6")

    def _raise_oserror(*_args: object, **_kwargs: object) -> object:
        raise OSError("cannot load libc")

    monkeypatch.setattr(capability_probe.ctypes, "CDLL", _raise_oserror)
    assert capability_probe._live_landlock_abi(444) == (-1, errno.ENOSYS)


def test_missing_syscall_symbol_is_landlock_absent(monkeypatch: pytest.MonkeyPatch) -> None:
    class _NoSyscall:
        pass

    monkeypatch.setattr(capability_probe.ctypes.util, "find_library", lambda _name: "libc.so.6")
    monkeypatch.setattr(capability_probe.ctypes, "CDLL", lambda *_args, **_kwargs: _NoSyscall())
    assert capability_probe._live_landlock_abi(444) == (-1, errno.ENOSYS)


def test_runtime_binary_and_socket_is_enforced(tmp_path: Path) -> None:
    sock = tmp_path / "docker.sock"
    sock.write_text("", encoding="utf-8")
    report = _host(
        which=lambda name: "/usr/bin/docker" if name == "docker" else None,
        runtime_sockets={"docker": sock},
    )
    assert report["container_runtimes"] == {"state": "enforced", "reachable": ["docker"]}


def test_runtime_binary_without_socket_is_absent(tmp_path: Path) -> None:
    report = _host(
        which=lambda _name: "/usr/bin/docker",
        runtime_sockets={"docker": tmp_path / "missing.sock"},
    )
    assert report["container_runtimes"]["state"] == "absent"


def test_runtime_socket_eacces_is_undetermined() -> None:
    report = _host(
        which=lambda _name: "/usr/bin/docker",
        runtime_sockets={"docker": _DeniedSock()},  # type: ignore[dict-item]
    )
    assert report["container_runtimes"]["state"] == "undetermined"


def test_oserror_enoent_on_sysfs_is_missing(tmp_path: Path) -> None:
    class Missing:
        def read_text(self, encoding: str = "utf-8") -> str:
            raise OSError(errno.ENOENT, "gone")

    report = _host(lsm_path=Missing())  # type: ignore[arg-type]
    assert report["lsm"]["state"] == "absent"


def test_oserror_eio_on_sysfs_is_undetermined() -> None:
    class Broken:
        def read_text(self, encoding: str = "utf-8") -> str:
            raise OSError(errno.EIO, "io")

    report = _host(lsm_path=Broken())  # type: ignore[arg-type]
    assert report["lsm"]["state"] == "undetermined"
