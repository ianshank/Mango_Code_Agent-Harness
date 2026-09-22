"""SWE-ReX ExecutionBackend adapter (MG-E1).

Sync/async bridge: ``SweRexBackend.execute`` owns a single ``asyncio.run``
call on a fresh event loop. Callers must not nest this inside a running loop;
session/runtime close runs in ``finally`` on every exit path.

Docker / remote deployments never report ``filesystem_isolation=enforced``
unless a deployment-class map entry *and* a live probe both succeed; otherwise
``undetermined``. Host ``Local`` deployments are ``unenforced``.
``available()`` never feeds isolation evidence (R-AEI-10).
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from typing import Any

from harness.shared.governance.execution_backend import (
    ISOLATION_ENFORCED,
    ISOLATION_UNDETERMINED,
    ISOLATION_UNENFORCED,
    SWE_REX_BACKEND_NAME,
    BackendCapabilities,
    ExecutionBackend,
    ExecutionRequest,
    ExecutionResult,
    IsolationState,
)
from harness.shared.governance.process_backend import DEFAULT_MAX_OUTPUT_BYTES, DEFAULT_TIMEOUT_SEC, _cap
from harness.shared.governance.verdict import BROKER_BLOCKED, BROKER_FAILED, BROKER_SUCCESS

logger = logging.getLogger(__name__)

#: Deployment class name substrings graded as host (never enforced).
_HOST_DEPLOYMENT_MARKERS = ("local", "localruntime", "localdeployment", "host")

#: Deployment class name substrings that *may* be enforced after a live probe.
_ISOLATING_DEPLOYMENT_MARKERS = ("docker", "remote", "podman", "kubernetes", "k8s", "container")


def grade_swerex_deployment(
    deployment_class: str | None,
    *,
    probe_ok: bool | None,
) -> IsolationState:
    """Map deployment class + live probe to filesystem_isolation (arch §4.3)."""
    label = (deployment_class or "").strip().lower().replace("_", "").replace("-", "")
    if not label:
        return ISOLATION_UNDETERMINED
    if any(m in label for m in _HOST_DEPLOYMENT_MARKERS) and not any(m in label for m in _ISOLATING_DEPLOYMENT_MARKERS):
        return ISOLATION_UNENFORCED
    if any(m in label for m in _ISOLATING_DEPLOYMENT_MARKERS):
        if probe_ok is True:
            return ISOLATION_ENFORCED
        return ISOLATION_UNDETERMINED
    return ISOLATION_UNDETERMINED


class SweRexBackend:
    """Additive SWE-ReX adapter. Optional SDK; injectable runtime for tests."""

    name = SWE_REX_BACKEND_NAME
    version = "1.0.0"

    def __init__(
        self,
        *,
        deployment_class: str | None = None,
        runtime_factory: Callable[[], Any] | None = None,
        probe_alive: Callable[[Any], bool] | None = None,
        require_enforced: bool = False,
    ) -> None:
        self._deployment_class = deployment_class
        self._runtime_factory = runtime_factory
        self._probe_alive = probe_alive
        self._require_enforced = require_enforced
        self._runtime: Any | None = None
        self._probe_result: bool | None = None

    def available(self) -> bool:
        """Liveness only; never used as isolation evidence."""
        try:
            runtime = self._ensure_runtime()
        except Exception as exc:  # noqa: BLE001
            logger.warning("SweRexBackend unavailable: %s", exc)
            return False
        if runtime is None:
            return False
        try:
            if self._probe_alive is not None:
                self._probe_result = bool(self._probe_alive(runtime))
                return self._probe_result
            alive = getattr(runtime, "is_alive", None)
            if callable(alive):
                self._probe_result = bool(self._run_async(alive()))
                return self._probe_result
            self._probe_result = True
            return True
        except Exception as exc:  # noqa: BLE001
            logger.warning("SweRexBackend live probe failed: %s", exc)
            self._probe_result = False
            return False

    def capabilities(self) -> BackendCapabilities:
        grade = grade_swerex_deployment(self._deployment_class, probe_ok=self._probe_result)
        return BackendCapabilities(
            filesystem_isolation=grade,
            network_isolation=ISOLATION_UNDETERMINED,
            process_isolation=ISOLATION_UNDETERMINED,
            version=self.version,
        )

    def execute(self, request: ExecutionRequest) -> ExecutionResult:
        caps = self.capabilities()
        if self._require_enforced and caps.filesystem_isolation != ISOLATION_ENFORCED:
            return ExecutionResult(
                BROKER_BLOCKED,
                "",
                "",
                1,
                reason=(
                    f"BROKER_BLOCKED: swe-rex filesystem_isolation={caps.filesystem_isolation} (enforced required)"
                ),
                action=request.action,
            )
        runtime = None
        try:
            runtime = self._ensure_runtime()
            if runtime is None:
                return ExecutionResult(
                    BROKER_BLOCKED,
                    "",
                    "",
                    1,
                    reason="BLOCKED: swe-rex runtime unavailable",
                    action=request.action,
                )
            # Refresh probe for grading before claim paths.
            self.available()
            caps = self.capabilities()
            if self._require_enforced and caps.filesystem_isolation != ISOLATION_ENFORCED:
                return ExecutionResult(
                    BROKER_BLOCKED,
                    "",
                    "",
                    1,
                    reason=(f"BROKER_BLOCKED: swe-rex filesystem_isolation={caps.filesystem_isolation} after probe"),
                    action=request.action,
                )
            timeout = request.timeout if request.timeout > 0 else DEFAULT_TIMEOUT_SEC
            max_out = request.max_output_bytes if request.max_output_bytes > 0 else DEFAULT_MAX_OUTPUT_BYTES
            response = self._run_async(self._execute_async(runtime, request.command, timeout))
            stdout = _cap(str(getattr(response, "stdout", "") or ""), max_out)
            stderr = _cap(str(getattr(response, "stderr", "") or ""), max_out)
            exit_code = int(getattr(response, "exit_code", getattr(response, "returncode", 1)) or 0)
            status = BROKER_SUCCESS if exit_code == 0 else BROKER_FAILED
            return ExecutionResult(status, stdout, stderr, exit_code, action=request.action)
        except Exception as exc:  # noqa: BLE001
            logger.warning("SweRexBackend execute failed: %s", exc)
            return ExecutionResult(
                BROKER_FAILED,
                "",
                "",
                1,
                reason=f"swe-rex execute failed: {exc}",
                action=request.action,
            )
        finally:
            self._close_runtime(runtime)

    def _ensure_runtime(self) -> Any | None:
        if self._runtime is not None:
            return self._runtime
        if self._runtime_factory is not None:
            self._runtime = self._runtime_factory()
            return self._runtime
        try:
            # Optional extra; core CI never imports this path.
            from swerex.runtime.abstract import AbstractRuntime  # type: ignore[import-not-found]

            _ = AbstractRuntime
        except Exception:  # noqa: BLE001
            return None
        return None

    async def _execute_async(self, runtime: Any, command: str, timeout: int) -> Any:
        execute = getattr(runtime, "execute", None)
        if execute is None:
            raise RuntimeError("runtime has no execute()")
        # Prefer kwargs commonly used by AbstractRuntime Command wrappers.
        try:
            return await execute(command)
        except TypeError:
            return await execute(command=command, timeout=timeout)

    def _close_runtime(self, runtime: Any | None) -> None:
        if runtime is None:
            return
        closer = getattr(runtime, "close", None)
        try:
            if callable(closer):
                result = closer()
                if asyncio.iscoroutine(result):
                    self._run_async(result)
        except Exception as exc:  # noqa: BLE001
            logger.warning("SweRexBackend close failed: %s", exc)
        finally:
            if runtime is self._runtime:
                self._runtime = None

    def _run_async(self, coro: Any) -> Any:
        """Single approved sync/async bridge: fresh loop via ``asyncio.run``.

        Raises if called from a running event loop (no nested loops).
        """
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            return asyncio.run(coro)
        raise RuntimeError("SweRexBackend refuses nested event loops; call execute from sync code")


_: ExecutionBackend = SweRexBackend(deployment_class="LocalRuntime", runtime_factory=lambda: None)

__all__ = ["SweRexBackend", "grade_swerex_deployment"]
