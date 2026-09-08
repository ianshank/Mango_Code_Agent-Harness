"""Execution backend protocol, request, capabilities, and result.

Does not import ``broker`` (C-AEI-5). ``ExecutionResult`` lives here so the
abstraction does not import its implementation (R-AEI-9).
"""

from __future__ import annotations

import inspect
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, Protocol, runtime_checkable

IsolationState = Literal["enforced", "unenforced", "undetermined"]

_EXECUTE_PARAM = "request"


@dataclass(frozen=True)
class BackendCapabilities:
    """What a backend actually enforced, not what a caller asked for (R-AEI-10)."""

    filesystem_isolation: IsolationState
    network_isolation: IsolationState
    process_isolation: IsolationState
    version: str


@dataclass(frozen=True)
class ExecutionRequest:
    """The single value a backend executes (R-AEI-8)."""

    command: str
    workspace: Path | None
    cwd: Path | None
    timeout: int
    max_output_bytes: int
    action: str
    required_capabilities: BackendCapabilities | None = None


@dataclass(frozen=True)
class ExecutionResult:
    """The outcome of an execution attempt."""

    status: str  # one of verdict.BROKER_SUCCESS / BROKER_FAILED / BROKER_BLOCKED
    stdout: str
    stderr: str
    exit_code: int
    #: Why the broker reached this status. Empty for a plain command failure,
    #: where the command's own stderr is the explanation.
    reason: str = ""
    #: The action the command was classified as, recorded so an evidence entry
    #: can state what was decided rather than only what was run.
    action: str = ""


@runtime_checkable
class ExecutionBackend(Protocol):
    """A backend that can run a governed command (R-AEI-8, R-AEI-9)."""

    name: str
    version: str

    def available(self) -> bool:
        """Whether this backend can start work on this host."""
        ...

    def capabilities(self) -> BackendCapabilities:
        """Isolation actually applied, as three-state fields plus version."""
        ...

    def execute(self, request: ExecutionRequest) -> ExecutionResult:
        """Run ``request`` and return a result. Must not fall back to another backend."""
        ...


def _public_params(method: object) -> tuple[str, ...]:
    """Parameter names excluding ``self``, for signature comparison (AC-9)."""
    if not callable(method):
        return ()
    names: list[str] = []
    for param in inspect.signature(method).parameters.values():
        if param.name == "self":
            continue
        if param.kind is inspect.Parameter.VAR_POSITIONAL or param.kind is inspect.Parameter.VAR_KEYWORD:
            return ()
        names.append(param.name)
    return tuple(names)


def conforms_to_backend(obj: object) -> bool:
    """True when ``obj`` has ``ExecutionBackend`` methods with the protocol signatures.

    ``runtime_checkable`` only checks names. AC-9 requires a stub with the right
    attribute names and the wrong signatures to be rejected.
    """
    execute = getattr(obj, "execute", None)
    capabilities = getattr(obj, "capabilities", None)
    available = getattr(obj, "available", None)
    if not all(callable(item) for item in (execute, capabilities, available)):
        return False
    if _public_params(execute) != (_EXECUTE_PARAM,):
        return False
    if _public_params(capabilities) != ():
        return False
    return _public_params(available) == ()


__all__ = [
    "BackendCapabilities",
    "ExecutionBackend",
    "ExecutionRequest",
    "ExecutionResult",
    "IsolationState",
    "conforms_to_backend",
]
