"""Apply a Landlock ruleset in the current process (R-AEI-13, DEC-069).

Called from the child ``preexec_fn`` so the parent pytest / ``make validate``
process is never restricted. Stdlib ctypes only. Never imports ``broker`` or
``subprocess``. Never treats proxy environment variables as isolation
(R-AEI-15).
"""

from __future__ import annotations

import ctypes
import ctypes.util
import os
import sys
from collections.abc import Callable, Iterable, Mapping, Sequence
from pathlib import Path

#: Kernel ABI that added TCP bind/connect access bits. Named in DEC-069;
#: operators must not lower it through policy.
MIN_ABI_FOR_NET = 4

#: Read-execute system trees the confined interpreter still needs. Named in
#: DEC-069. ``/etc`` is deliberately absent.
SYSTEM_RO_PATHS: tuple[str, ...] = (
    "/usr",
    "/lib",
    "/lib64",
    "/bin",
    "/sbin",
    "/proc",
    "/dev",
)

_NR_BY_MACHINE = {
    "x86_64": {"create": 444, "add": 445, "restrict": 446},
    "aarch64": {"create": 444, "add": 445, "restrict": 446},
    "arm64": {"create": 444, "add": 445, "restrict": 446},
}
_PR_SET_NO_NEW_PRIVS = 38
_RULE_PATH_BENEATH = 1
_NET_BIND_TCP = 1 << 0
_NET_CONNECT_TCP = 1 << 1


class _RulesetAttr(ctypes.Structure):
    _fields_ = [
        ("handled_access_fs", ctypes.c_uint64),
        ("handled_access_net", ctypes.c_uint64),
    ]


class _PathBeneath(ctypes.Structure):
    _fields_ = [
        ("allowed_access", ctypes.c_uint64),
        ("parent_fd", ctypes.c_int32),
    ]


def _fs_handled(abi: int) -> int:
    """Handled FS bits for this ABI. Unhandled bits stay permitted."""
    bits = (1 << 13) - 1
    if abi >= 2:
        bits |= 1 << 13
    if abi >= 3:
        bits |= 1 << 14
    if abi >= 5:
        bits |= 1 << 15
    return bits


def _ro_access(abi: int) -> int:
    access = (1 << 0) | (1 << 2) | (1 << 3)  # execute, read file, read dir
    if abi >= 5:
        access |= 1 << 15  # ioctl on /dev
    return access


def _runtime_ro_paths() -> tuple[Path, ...]:
    paths = [Path(item) for item in SYSTEM_RO_PATHS]
    prefix = Path(sys.prefix)
    paths.append(prefix)
    executable = Path(sys.executable).resolve()
    paths.append(executable.parent)
    return tuple(paths)


def _open_dir(path: Path) -> int:
    flags = os.O_RDONLY | os.O_CLOEXEC
    if hasattr(os, "O_PATH"):
        flags |= os.O_PATH
    if hasattr(os, "O_DIRECTORY"):
        flags |= os.O_DIRECTORY
    return os.open(path, flags)


def _add_path(syscall: Callable[..., int], nr_add: int, ruleset: int, path: Path, access: int) -> None:
    fd = _open_dir(path)
    try:
        attr = _PathBeneath(access, fd)
        ctypes.set_errno(0)
        ret = syscall(
            ctypes.c_long(nr_add),
            ctypes.c_int(ruleset),
            ctypes.c_uint(_RULE_PATH_BENEATH),
            ctypes.byref(attr),
            ctypes.c_uint(0),
        )
        err = ctypes.get_errno()
        if int(ret) < 0:
            raise OSError(err, f"landlock_add_rule {path}: {os.strerror(err)}")
    finally:
        os.close(fd)


def _libc_syscall() -> Callable[..., int]:
    libname = ctypes.util.find_library("c")
    if not libname:
        raise OSError("landlock: libc not found")
    try:
        libc = ctypes.CDLL(libname, use_errno=True)
    except OSError as exc:
        raise OSError(f"landlock: libc load failed: {exc}") from exc
    try:
        syscall = libc.syscall
    except AttributeError as exc:
        raise OSError("landlock: libc has no syscall") from exc
    syscall.restype = ctypes.c_long

    def _call(*args: object) -> int:
        return int(syscall(*args))

    return _call


def apply_landlock(
    workspace: Path,
    abi: int,
    *,
    machine: str | None = None,
    extra_ro: Sequence[Path] | None = None,
    syscall: Callable[..., int] | None = None,
    prctl: Callable[..., int] | None = None,
) -> None:
    """Restrict the current thread to ``workspace`` RW and system RO paths.

    Default-denies TCP bind/connect by handling those bits with no port rules.
    Raises ``OSError`` on any kernel or path failure so the parent treats it
    as BLOCKED rather than an unisolated spawn.
    """
    if abi < MIN_ABI_FOR_NET:
        raise OSError(f"landlock ABI {abi} is below MIN_ABI_FOR_NET")
    resolved = workspace.resolve()
    if not resolved.is_dir():
        raise OSError(f"landlock workspace is not a directory: {resolved}")
    uname = getattr(os, "uname", None)
    mach = machine
    if mach is None:
        if uname is None:
            raise OSError("landlock: no uname")
        mach = str(uname().machine)
    nrs: Mapping[str, int] | None = _NR_BY_MACHINE.get(mach)
    if nrs is None:
        raise OSError(f"landlock: unsupported machine {mach!r}")
    sc = syscall if syscall is not None else _libc_syscall()
    handled_fs = _fs_handled(abi)
    attr = _RulesetAttr(handled_fs, _NET_BIND_TCP | _NET_CONNECT_TCP)
    ctypes.set_errno(0)
    ruleset = sc(
        ctypes.c_long(nrs["create"]),
        ctypes.byref(attr),
        ctypes.c_size_t(ctypes.sizeof(attr)),
        ctypes.c_uint(0),
    )
    err = ctypes.get_errno()
    if int(ruleset) < 0:
        raise OSError(err, f"landlock_create_ruleset: {os.strerror(err)}")
    fd = int(ruleset)
    try:
        _add_path(sc, nrs["add"], fd, resolved, handled_fs)
        seen: set[Path] = {resolved}
        ro_access = _ro_access(abi)
        ro_iter: Iterable[Path] = _runtime_ro_paths() if extra_ro is None else extra_ro
        for raw in ro_iter:
            try:
                path = raw.resolve()
            except OSError:
                continue
            if path in seen or not path.is_dir():
                continue
            try:
                _add_path(sc, nrs["add"], fd, path, ro_access)
            except OSError:
                continue
            seen.add(path)
        prctl_fn = prctl
        if prctl_fn is None:
            libname = ctypes.util.find_library("c")
            if not libname:
                raise OSError("landlock: libc not found for prctl")
            prctl_fn = ctypes.CDLL(libname, use_errno=True).prctl
        ctypes.set_errno(0)
        if int(prctl_fn(_PR_SET_NO_NEW_PRIVS, 1, 0, 0, 0)) != 0:
            raise OSError(ctypes.get_errno(), "PR_SET_NO_NEW_PRIVS")
        ctypes.set_errno(0)
        ret = sc(ctypes.c_long(nrs["restrict"]), ctypes.c_int(fd), ctypes.c_uint(0))
        err = ctypes.get_errno()
        if int(ret) < 0:
            raise OSError(err, f"landlock_restrict_self: {os.strerror(err)}")
    finally:
        os.close(fd)


__all__ = [
    "MIN_ABI_FOR_NET",
    "SYSTEM_RO_PATHS",
    "apply_landlock",
]
