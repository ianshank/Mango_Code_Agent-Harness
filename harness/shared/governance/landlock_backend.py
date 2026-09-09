"""Landlock ``ExecutionBackend`` (R-AEI-13, C-AEI-3, DEC-069).

Confines the child to ``ExecutionRequest.workspace`` and default-denies TCP.
Probe, compile, or attestation failure returns BLOCKED and never falls
through to ``ProcessBackend``. Tests construct this class directly; the
broker default stays ``ProcessBackend()``.
"""

from __future__ import annotations

import logging
import os
import subprocess
import sys
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

from harness.shared.debug_dump import credential_env_names
from harness.shared.governance.capability_probe import probe
from harness.shared.governance.execution_backend import (
    ISOLATION_ENFORCED,
    ISOLATION_UNENFORCED,
    LANDLOCK_BACKEND_NAME,
    BackendCapabilities,
    ExecutionBackend,
    ExecutionRequest,
    ExecutionResult,
)
from harness.shared.governance.landlock_restrict import MIN_ABI_FOR_NET as MIN_ABI_FOR_NET
from harness.shared.governance.landlock_restrict import apply_landlock
from harness.shared.governance.process_backend import (
    DEFAULT_MAX_OUTPUT_BYTES,
    DEFAULT_TIMEOUT_SEC,
    ProcessBackend,
    _cap,
)
from harness.shared.governance.sandbox_policy import (
    CompiledSandboxPolicy,
    SandboxPolicyError,
    compile_sandbox_policy,
)
from harness.shared.governance.verdict import BROKER_BLOCKED, BROKER_FAILED, BROKER_SUCCESS
from harness.shared.policy_loader import PolicyError

logger = logging.getLogger(__name__)

_ApplyFn = Callable[[Path, int], None]
_AttestFn = Callable[[BackendCapabilities], bool]
_CompileFn = Callable[[], CompiledSandboxPolicy]


class LandlockBackend:
    """Isolation backend. Available on POSIX with ABI at or above ``MIN_ABI_FOR_NET``."""

    name = LANDLOCK_BACKEND_NAME
    version = "1.0.0"
    shell = ProcessBackend.shell

    def __init__(
        self,
        *,
        probe_report: Mapping[str, Any] | None = None,
        policy: CompiledSandboxPolicy | None = None,
        compiler: _CompileFn | None = None,
        apply_fn: _ApplyFn | None = None,
        attest: _AttestFn | None = None,
    ) -> None:
        self._probe_report: Mapping[str, Any] | None = dict(probe_report) if probe_report is not None else None
        self._apply = apply_fn if apply_fn is not None else apply_landlock
        self._attest = attest
        self._applied: BackendCapabilities | None = None
        self._compile_error: str | None = None
        self._policy: CompiledSandboxPolicy | None = None
        try:
            live = compiler() if compiler is not None else compile_sandbox_policy()
            if policy is not None and policy.compiled_digest != live.compiled_digest:
                self._compile_error = "sandbox policy mismatch"
            else:
                self._policy = policy if policy is not None else live
        except (SandboxPolicyError, PolicyError, OSError, ValueError) as exc:
            self._compile_error = str(exc)
            logger.warning("LandlockBackend policy compilation failed: %s", exc)

    def _report(self) -> Mapping[str, Any]:
        if self._probe_report is None:
            self._probe_report = probe()
        return self._probe_report

    def _abi(self) -> int | None:
        field = self._report().get("landlock_abi")
        if not isinstance(field, Mapping):
            return None
        state = field.get("state")
        abi = field.get("abi")
        if state != "enforced" or isinstance(abi, bool) or not isinstance(abi, int):
            return None
        return abi

    def available(self) -> bool:
        """POSIX + Landlock ABI at or above ``MIN_ABI_FOR_NET`` (DEC-069)."""
        if sys.platform == "win32" or os.name != "posix":
            return False
        abi = self._abi()
        return abi is not None and abi >= MIN_ABI_FOR_NET

    def capabilities(self) -> BackendCapabilities:
        """Isolation actually applied, or unenforced until a confined spawn."""
        if self._applied is not None:
            return self._applied
        return BackendCapabilities(
            filesystem_isolation=ISOLATION_UNENFORCED,
            network_isolation=ISOLATION_UNENFORCED,
            process_isolation=ISOLATION_UNENFORCED,
            version=self.version,
        )

    def _blocked(self, reason: str, action: str = "") -> ExecutionResult:
        logger.warning("LandlockBackend BLOCKED: %s", reason)
        return ExecutionResult(BROKER_BLOCKED, "", "", 1, reason=reason, action=action)

    def _inside(self, path: Path, root: Path) -> bool:
        """True when ``path`` is ``root`` or a descendant. Both must be resolved."""
        try:
            path.relative_to(root)
        except ValueError:
            return False
        return True

    def _confine_paths(self, workspace: Path, cwd: Path | None, action: str) -> tuple[Path, Path] | ExecutionResult:
        """Resolve workspace and cwd once; BLOCKED if either is unreadable or outside."""
        try:
            workspace_res = workspace.resolve()
        except OSError as exc:
            return self._blocked(f"workspace unreadable: {exc}", action)
        if cwd is None or cwd == workspace:
            cwd_res = workspace_res
        else:
            try:
                cwd_res = cwd.resolve()
            except OSError as exc:
                return self._blocked(f"cwd unreadable: {exc}", action)
        if not self._inside(cwd_res, workspace_res):
            return self._blocked("cwd is outside the request workspace", action)
        return workspace_res, cwd_res

    def _child_env(self) -> dict[str, str]:
        denied = set(credential_env_names())
        env = {key: value for key, value in os.environ.items() if key not in denied}
        env["PYTHONDONTWRITEBYTECODE"] = "1"
        return env

    def execute(self, request: ExecutionRequest) -> ExecutionResult:
        """Confine then spawn. Failures here are BLOCKED, never process fallback."""
        action = request.action
        if self._compile_error or self._policy is None:
            return self._blocked(
                f"sandbox policy compilation failed: {self._compile_error or 'missing policy'}",
                action,
            )
        if not self.available():
            field = self._report().get("landlock_abi")
            state = field.get("state") if isinstance(field, Mapping) else None
            if state == "undetermined":
                return self._blocked("isolation probe failed: landlock_abi undetermined", action)
            return self._blocked("isolation backend unavailable on this host", action)
        workspace = request.workspace
        if workspace is None or not workspace.is_dir():
            return self._blocked("isolation requires a workspace directory", action)
        confined = self._confine_paths(workspace, request.cwd, action)
        if isinstance(confined, ExecutionResult):
            return confined
        workspace_res, cwd_res = confined
        abi = self._abi()
        if abi is None:
            return self._blocked("isolation probe failed: landlock ABI missing", action)
        apply_fn = self._apply

        def preexec() -> None:
            apply_fn(workspace_res, abi)

        timeout = request.timeout if request.timeout > 0 else DEFAULT_TIMEOUT_SEC
        cap = request.max_output_bytes if request.max_output_bytes > 0 else DEFAULT_MAX_OUTPUT_BYTES
        try:
            kwargs: dict[str, Any] = {
                "cwd": str(cwd_res),
                "capture_output": True,
                "encoding": "utf-8",
                "timeout": timeout,
                "env": self._child_env(),
            }
            if os.name == "posix":
                kwargs["preexec_fn"] = preexec
            completed = subprocess.run([self.shell, "-c", request.command], **kwargs)
        except subprocess.TimeoutExpired:
            return ExecutionResult(
                BROKER_FAILED, "", "", 1, reason=f"command timed out after {timeout}s", action=action
            )
        except (OSError, subprocess.SubprocessError) as exc:
            return self._blocked(f"isolation apply failed: {exc}", action)
        except Exception as exc:  # noqa: BLE001 - isolation backend must answer every call
            return self._blocked(f"isolation execute failed: {exc}", action)
        caps = BackendCapabilities(
            filesystem_isolation=ISOLATION_ENFORCED,
            network_isolation=ISOLATION_ENFORCED,
            process_isolation=ISOLATION_UNENFORCED,
            version=self.version,
        )
        if self._attest is not None and not self._attest(caps):
            return self._blocked("isolation attestation failed", action)
        self._applied = caps
        stdout = _cap(completed.stdout or "", cap)
        stderr = _cap(completed.stderr or "", cap)
        status = BROKER_SUCCESS if completed.returncode == 0 else BROKER_FAILED
        return ExecutionResult(status, stdout, stderr, completed.returncode, action=action)


_: ExecutionBackend = LandlockBackend()

__all__ = ["LandlockBackend", "MIN_ABI_FOR_NET"]
