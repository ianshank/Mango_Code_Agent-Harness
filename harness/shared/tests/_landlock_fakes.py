"""Landlock apply doubles shared by isolation tests.

The synthetic ruleset fd must not be a live descriptor: ``apply_landlock``
closes it, and closing pytest's stdin/out/err (or another open fd) would
corrupt the suite. Tests patch ``os.close`` through ``install_fake_ruleset_close``.
"""

from __future__ import annotations

import os
from collections.abc import Callable
from typing import Any

import pytest

#: Synthetic ``landlock_create_ruleset`` fd. Chosen above typical process
#: tables so a missed close-patch cannot hit stdio or a pytest temp fd.
FAKE_RULESET_FD = 10_007


def install_fake_ruleset_close(monkeypatch: pytest.MonkeyPatch) -> None:
    """No-op ``os.close`` for the synthetic ruleset fd only."""
    real_close = os.close

    def fake_close(fd: int) -> None:
        if fd == FAKE_RULESET_FD:
            return
        real_close(fd)

    monkeypatch.setattr(os, "close", fake_close)


def counting_syscall(
    *,
    fail_on: int | None = None,
    counter: dict[str, int] | None = None,
) -> tuple[Callable[..., int], dict[str, int]]:
    """First call yields ``FAKE_RULESET_FD``; later calls return 0 or -1.

    ``fail_on`` is a 1-based call index. The counter is returned so callers
    can assert how many syscalls the apply path issued.
    """
    n = counter if counter is not None else {"n": 0}

    def fake_syscall(*_a: object, **_k: object) -> int:
        n["n"] += 1
        if n["n"] == 1:
            return FAKE_RULESET_FD
        if fail_on is not None and n["n"] == fail_on:
            return -1
        return 0

    return fake_syscall, n


def noop_prctl(*_a: object, **_k: object) -> int:
    return 0


def failing_prctl(*_a: object, **_k: object) -> int:
    return 1


def probe_report(*, landlock_abi: object) -> dict[str, Any]:
    """Capability-probe shaped fixture. LSM name is the kernel name, not the backend."""
    return {
        "schema_version": 1,
        "lsm": {"state": "enforced", "names": ["landlock"]},
        "landlock_abi": landlock_abi,
        "unprivileged_userns": {"state": "absent", "sysctls": {}},
        "container_runtimes": {"state": "absent", "reachable": []},
    }
