"""Host-inventory probe for INV-13 isolation primitives (R-AEI-12 / AC-12).

Stdlib only. Spawn-free. Reports whether a primitive *exists* on this host
(enforced / absent / undetermined), not whether a backend applied it.
Never imports ``broker`` or ``process_backend``. Never calls
``landlock_restrict_self`` or ``landlock_add_rule``.

Spec: docs/specs/attested-execution-isolation.md.
"""

from __future__ import annotations

import argparse
import ctypes
import ctypes.util
import errno
import json
import os
import shutil
import sys
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any

LEGAL_STATES = frozenset({"enforced", "absent", "undetermined"})
_FIELDS = ("lsm", "landlock_abi", "unprivileged_userns", "container_runtimes")

#: asm-generic / x86_64 ``__NR_landlock_create_ruleset``. A dict so
#: TestTheInventoryIsComplete does not treat the numbers as operational limits.
_landlock_create_ruleset_nr_by_machine = {
    "x86_64": 444,
    "aarch64": 444,
    "arm64": 444,
}

_lsm_path = Path("/sys/kernel/security/lsm")
_userns_files = {
    "unprivileged_userns_clone": Path("/proc/sys/kernel/unprivileged_userns_clone"),
    "apparmor_restrict_unprivileged_userns": Path("/proc/sys/kernel/apparmor_restrict_unprivileged_userns"),
    "max_user_namespaces": Path("/proc/sys/user/max_user_namespaces"),
}
_runtime_sockets = {
    "docker": Path("/var/run/docker.sock"),
    "podman": Path("/run/podman/podman.sock"),
}

_ABSENT_ERRNOS = {errno.ENOSYS, errno.ENOTSUP, getattr(errno, "EOPNOTSUPP", errno.ENOTSUP)}


def _is_windows(platform: str) -> bool:
    return platform == "win32"


def _uname_machine() -> str | None:
    uname = getattr(os, "uname", None)
    if uname is None:
        return None
    return str(uname().machine)


def _absent_fields() -> dict[str, Any]:
    return {
        "schema_version": 1,
        "lsm": {"state": "absent", "names": []},
        "landlock_abi": {"state": "absent", "abi": None},
        "unprivileged_userns": {"state": "absent", "sysctls": {}},
        "container_runtimes": {"state": "absent", "reachable": []},
    }


def _read_sysfs(path: Path) -> tuple[str | None, str]:
    """Return ``(text, kind)`` where kind is ``ok``, ``missing``, or ``denied``."""
    try:
        return path.read_text(encoding="utf-8"), "ok"
    except FileNotFoundError:
        return None, "missing"
    except PermissionError:
        return None, "denied"
    except OSError as exc:
        if exc.errno in {errno.ENOENT, errno.ENOTDIR}:
            return None, "missing"
        return None, "denied"


def _probe_lsm(path: Path) -> dict[str, Any]:
    text, kind = _read_sysfs(path)
    if kind == "missing":
        return {"state": "absent", "names": []}
    if kind == "denied":
        return {"state": "undetermined", "names": []}
    names = [part.strip() for part in (text or "").split(",") if part.strip()]
    return {"state": "enforced", "names": names}


def _probe_userns(files: Mapping[str, Path]) -> dict[str, Any]:
    sysctls: dict[str, str] = {}
    saw_denied = False
    for name, path in files.items():
        text, kind = _read_sysfs(path)
        if kind == "denied":
            saw_denied = True
            continue
        if kind == "ok" and text is not None:
            sysctls[name] = text.strip()
    if saw_denied:
        return {"state": "undetermined", "sysctls": sysctls}
    if not sysctls:
        return {"state": "absent", "sysctls": {}}
    return {"state": "enforced", "sysctls": sysctls}


def _live_landlock_abi(nr: int) -> tuple[int, int]:
    """VERSION-flag query only. Returns ``(syscall_return, errno)``."""
    libname = ctypes.util.find_library("c")
    if not libname:
        return -1, errno.ENOSYS
    try:
        libc = ctypes.CDLL(libname, use_errno=True)
    except OSError:
        return -1, errno.ENOSYS
    try:
        syscall = libc.syscall
    except AttributeError:
        return -1, errno.ENOSYS
    syscall.restype = ctypes.c_long
    ctypes.set_errno(0)
    version_flag = 1 << 0
    ret = syscall(
        ctypes.c_long(nr),
        None,
        ctypes.c_size_t(0),
        ctypes.c_uint(version_flag),
    )
    return int(ret), ctypes.get_errno()


def _probe_landlock(
    machine: str,
    syscall: Callable[[int], tuple[int, int]],
) -> dict[str, Any]:
    nr = _landlock_create_ruleset_nr_by_machine.get(machine)
    if nr is None:
        return {"state": "undetermined", "abi": None}
    ret, err = syscall(nr)
    if ret >= 1:
        return {"state": "enforced", "abi": ret}
    if err in _ABSENT_ERRNOS:
        return {"state": "absent", "abi": None}
    return {"state": "undetermined", "abi": None}


def _probe_runtimes(
    which: Callable[[str], str | None],
    sockets: Mapping[str, Path],
) -> dict[str, Any]:
    reachable: list[str] = []
    saw_denied = False
    for name, sock in sockets.items():
        try:
            sock_ok = sock.exists()
        except OSError as exc:
            if exc.errno in {errno.EACCES, errno.EPERM}:
                saw_denied = True
                continue
            sock_ok = False
        if which(name) and sock_ok:
            reachable.append(name)
    if saw_denied and not reachable:
        return {"state": "undetermined", "reachable": []}
    if not reachable:
        return {"state": "absent", "reachable": []}
    return {"state": "enforced", "reachable": reachable}


def probe(
    *,
    platform: str | None = None,
    machine: str | None = None,
    lsm_path: Path | None = None,
    userns_files: Mapping[str, Path] | None = None,
    landlock_syscall: Callable[[int], tuple[int, int]] | None = None,
    which: Callable[[str], str | None] | None = None,
    runtime_sockets: Mapping[str, Path] | None = None,
) -> dict[str, Any]:
    """Measure the four R-AEI-12 fields. Defaults read this host."""
    plat = sys.platform if platform is None else platform
    if _is_windows(plat):
        return _absent_fields()
    resolved_machine = machine
    if resolved_machine is None:
        resolved_machine = _uname_machine()
        if resolved_machine is None:
            return _absent_fields()
    report = {
        "schema_version": 1,
        "lsm": _probe_lsm(lsm_path if lsm_path is not None else _lsm_path),
        "landlock_abi": _probe_landlock(
            resolved_machine,
            landlock_syscall if landlock_syscall is not None else _live_landlock_abi,
        ),
        "unprivileged_userns": _probe_userns(userns_files if userns_files is not None else _userns_files),
        "container_runtimes": _probe_runtimes(
            which if which is not None else shutil.which,
            runtime_sockets if runtime_sockets is not None else _runtime_sockets,
        ),
    }
    return report


def exit_status(report: Mapping[str, Any]) -> int:
    """1 iff any field is undetermined; 0 for enforced or absent (AC-12)."""
    for name in _FIELDS:
        field = report.get(name)
        if not isinstance(field, Mapping) or field.get("state") == "undetermined":
            return 1
        if field.get("state") not in LEGAL_STATES:
            return 1
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    """CLI. Returns the exit code so tests can drive it in-process."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0] if __doc__ else None)
    parser.add_argument("--json", action="store_true", help="print the inventory as JSON")
    args = parser.parse_args(argv)
    report = probe()
    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True))
    return exit_status(report)


if __name__ == "__main__":  # pragma: no cover - exercised through main()
    raise SystemExit(main())
