"""Policy-selected ExecutionBackend registry (MG-E1).

Backend ids live under the protected top-level ``execution_backend`` policy
block (new block per DEC-043 so adopters without the key stay valid). Agents
and environment variables cannot select a backend. Unknown ids deny.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from pathlib import Path
from typing import cast

from harness.shared.governance.execution_backend import (
    ISOLATION_ENFORCED,
    OPEN_SANDBOX_BACKEND_NAME,
    SWE_REX_BACKEND_NAME,
    ExecutionBackend,
    IsolationState,
)
from harness.shared.governance.process_backend import ProcessBackend
from harness.shared.policy_io import PolicyError, _log_resolution, _section

DEFAULT_BACKEND_ID = "process"
KNOWN_BACKEND_IDS = frozenset({"process", SWE_REX_BACKEND_NAME, OPEN_SANDBOX_BACKEND_NAME, "landlock"})

BackendFactory = Callable[[], ExecutionBackend]


class BackendSelectionError(Exception):
    """Fail-closed selection failure (unknown id, isolation mismatch, etc.)."""


def _default_factories() -> dict[str, BackendFactory]:
    from harness.shared.governance.landlock_backend import LandlockBackend
    from harness.shared.governance.opensandbox_backend import OpenSandboxBackend
    from harness.shared.governance.swerex_backend import SweRexBackend

    return {
        "process": ProcessBackend,
        "landlock": LandlockBackend,
        SWE_REX_BACKEND_NAME: SweRexBackend,
        OPEN_SANDBOX_BACKEND_NAME: OpenSandboxBackend,
    }


def execution_backend_id(policy_path: Path | None = None) -> str:
    """Return configured backend id; absent ``execution_backend`` block => process."""
    section = _section("execution_backend", policy_path)
    if not section.declared():
        resolved = DEFAULT_BACKEND_ID
        _log_resolution("execution_backend", {"backend_id": resolved}, policy_path)
        return resolved
    raw = section._value("backend_id", DEFAULT_BACKEND_ID)
    if not isinstance(raw, str) or not raw.strip():
        raise PolicyError("policy execution_backend.backend_id must be a non-empty string")
    resolved = raw.strip()
    _log_resolution("execution_backend", {"backend_id": resolved}, policy_path)
    return resolved


def required_filesystem_isolation(policy_path: Path | None = None) -> IsolationState | None:
    """Optional required isolation; ``None`` when unset."""
    section = _section("execution_backend", policy_path)
    if not section.declared():
        return None
    raw = section._value("require_filesystem_isolation", None)
    if raw is None:
        return None
    if raw not in {"enforced", "unenforced", "undetermined"}:
        raise PolicyError(
            "policy execution_backend.require_filesystem_isolation must be enforced|unenforced|undetermined"
        )
    return cast(IsolationState, raw)


def resolve_backend(
    *,
    policy_path: Path | None = None,
    factories: Mapping[str, BackendFactory] | None = None,
    backend_id: str | None = None,
) -> ExecutionBackend:
    """Construct the policy-selected backend or raise ``BackendSelectionError``."""
    selected = backend_id if backend_id is not None else execution_backend_id(policy_path)
    factory_map = dict(factories) if factories is not None else _default_factories()
    if selected not in factory_map:
        raise BackendSelectionError(f"unknown execution backend_id {selected!r}; known={sorted(factory_map)}")
    return factory_map[selected]()


def assert_isolation_requirement(
    backend: ExecutionBackend,
    *,
    policy_path: Path | None = None,
    required: IsolationState | None = None,
) -> None:
    """Raise when policy requires enforced isolation the backend does not provide."""
    need = required if required is not None else required_filesystem_isolation(policy_path)
    if need != ISOLATION_ENFORCED:
        return
    caps = backend.capabilities()
    if caps.filesystem_isolation != ISOLATION_ENFORCED:
        raise BackendSelectionError(
            "BROKER_BLOCKED: policy requires filesystem_isolation=enforced but "
            f"backend {getattr(backend, 'name', '?')!r} reports "
            f"{caps.filesystem_isolation!r}"
        )


def select_execution_backend(
    *,
    policy_path: Path | None = None,
    factories: Mapping[str, BackendFactory] | None = None,
    backend_id: str | None = None,
) -> ExecutionBackend:
    """Resolve the policy-selected backend and enforce require_filesystem_isolation.

    Composes ``resolve_backend`` + ``assert_isolation_requirement`` so the
    ``execution_backend.require_filesystem_isolation`` policy key is threaded
    into adapter selection. Agents and environment variables cannot select a
    backend; only the protected policy file (or an explicit injectable
    ``backend`` on ``ExecutionBroker``) can.
    """
    backend = resolve_backend(
        policy_path=policy_path,
        factories=factories,
        backend_id=backend_id,
    )
    assert_isolation_requirement(backend, policy_path=policy_path)
    return backend


__all__ = [
    "BackendFactory",
    "BackendSelectionError",
    "DEFAULT_BACKEND_ID",
    "KNOWN_BACKEND_IDS",
    "assert_isolation_requirement",
    "execution_backend_id",
    "required_filesystem_isolation",
    "resolve_backend",
    "select_execution_backend",
]
