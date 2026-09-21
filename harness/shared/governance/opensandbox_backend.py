"""OpenSandbox ExecutionBackend adapter (MG-E1).

Prefers ``/v1/isolated/*`` when isolation is required. Capabilities probe
failure or non-isolated APIs never report ``enforced``. ``available()`` is
liveness only (R-AEI-10).
"""

from __future__ import annotations

import json
import logging
import urllib.error
import urllib.request
from collections.abc import Callable, Mapping
from typing import Any
from urllib.parse import urljoin

from harness.shared.governance.execution_backend import (
    ISOLATION_ENFORCED,
    ISOLATION_UNDETERMINED,
    ISOLATION_UNENFORCED,
    OPEN_SANDBOX_BACKEND_NAME,
    BackendCapabilities,
    ExecutionBackend,
    ExecutionRequest,
    ExecutionResult,
    IsolationState,
)
from harness.shared.governance.process_backend import DEFAULT_MAX_OUTPUT_BYTES, DEFAULT_TIMEOUT_SEC, _cap
from harness.shared.governance.verdict import BROKER_BLOCKED, BROKER_FAILED, BROKER_SUCCESS

logger = logging.getLogger(__name__)

HttpFn = Callable[[str, str, bytes | None, float], tuple[int, dict[str, Any] | str]]


def _default_http(method: str, url: str, body: bytes | None, timeout: float) -> tuple[int, dict[str, Any] | str]:
    request = urllib.request.Request(url, data=body, method=method)
    if body is not None:
        request.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(request, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
            try:
                return int(resp.status), json.loads(raw) if raw else {}
            except json.JSONDecodeError:
                return int(resp.status), raw
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="replace")
        try:
            return int(exc.code), json.loads(raw) if raw else {"error": str(exc)}
        except json.JSONDecodeError:
            return int(exc.code), raw


class OpenSandboxBackend:
    """Additive OpenSandbox execd adapter. Injectable HTTP for tests."""

    name = OPEN_SANDBOX_BACKEND_NAME
    version = "1.0.0"

    def __init__(
        self,
        *,
        base_url: str | None = None,
        use_isolated: bool = True,
        require_enforced: bool = False,
        http: HttpFn | None = None,
        capabilities_payload: Mapping[str, Any] | None = None,
    ) -> None:
        self._base_url = (base_url or "").rstrip("/")
        self._use_isolated = use_isolated
        self._require_enforced = require_enforced
        self._http = http or _default_http
        self._capabilities_payload = dict(capabilities_payload) if capabilities_payload else None
        self._probe_ok: bool | None = None

    def available(self) -> bool:
        if not self._base_url and self._capabilities_payload is None and self._http is _default_http:
            return False
        try:
            self._probe_capabilities()
            return self._probe_ok is True
        except Exception as exc:  # noqa: BLE001
            logger.warning("OpenSandboxBackend unavailable: %s", exc)
            self._probe_ok = False
            return False

    def capabilities(self) -> BackendCapabilities:
        grade = self._grade()
        return BackendCapabilities(
            filesystem_isolation=grade,
            network_isolation=ISOLATION_UNDETERMINED,
            process_isolation=ISOLATION_UNDETERMINED,
            version=self.version,
        )

    def execute(self, request: ExecutionRequest) -> ExecutionResult:
        session_id: str | None = None
        try:
            self._probe_capabilities()
            grade = self._grade()
            if self._require_enforced and grade != ISOLATION_ENFORCED:
                return ExecutionResult(
                    BROKER_BLOCKED,
                    "",
                    "",
                    1,
                    reason=(
                        "BROKER_BLOCKED: opensandbox filesystem_isolation="
                        f"{grade} (enforced required)"
                    ),
                    action=request.action,
                )
            if not self._base_url and self._http is _default_http and self._capabilities_payload is None:
                return ExecutionResult(
                    BROKER_BLOCKED,
                    "",
                    "",
                    1,
                    reason="BLOCKED: opensandbox base_url not configured",
                    action=request.action,
                )
            timeout = float(request.timeout if request.timeout > 0 else DEFAULT_TIMEOUT_SEC)
            max_out = (
                request.max_output_bytes
                if request.max_output_bytes > 0
                else DEFAULT_MAX_OUTPUT_BYTES
            )
            if self._use_isolated and grade == ISOLATION_ENFORCED:
                session_id = self._create_isolated_session(timeout)
                status_code, payload = self._run_isolated(session_id, request.command, timeout)
            else:
                status_code, payload = self._run_non_isolated(request.command, timeout)
            stdout, stderr, exit_code = self._normalize_payload(payload)
            stdout = _cap(stdout, max_out)
            stderr = _cap(stderr, max_out)
            if status_code >= 400 and exit_code == 0:
                exit_code = 1
            status = BROKER_SUCCESS if exit_code == 0 else BROKER_FAILED
            return ExecutionResult(status, stdout, stderr, exit_code, action=request.action)
        except Exception as exc:  # noqa: BLE001
            logger.warning("OpenSandboxBackend execute failed: %s", exc)
            return ExecutionResult(
                BROKER_FAILED,
                "",
                "",
                1,
                reason=f"opensandbox execute failed: {exc}",
                action=request.action,
            )
        finally:
            if session_id:
                self._delete_session(session_id)

    def _grade(self) -> IsolationState:
        if not self._use_isolated:
            return ISOLATION_UNENFORCED
        if self._probe_ok is True:
            return ISOLATION_ENFORCED
        if self._probe_ok is False:
            return ISOLATION_UNDETERMINED
        return ISOLATION_UNDETERMINED

    def _probe_capabilities(self) -> Mapping[str, Any]:
        if self._capabilities_payload is not None:
            payload = self._capabilities_payload
            available = bool(payload.get("available", payload.get("isolation_available", False)))
            self._probe_ok = available
            return payload
        if not self._base_url:
            self._probe_ok = False
            return {}
        code, payload = self._http(
            "GET",
            urljoin(self._base_url + "/", "v1/isolated/capabilities"),
            None,
            5.0,
        )
        if code >= 400 or not isinstance(payload, dict):
            self._probe_ok = False
            return {}
        available = bool(payload.get("available", payload.get("isolation_available", False)))
        self._probe_ok = available
        return payload

    def _create_isolated_session(self, timeout: float) -> str:
        code, payload = self._http(
            "POST",
            urljoin(self._base_url + "/", "v1/isolated/session"),
            b"{}",
            timeout,
        )
        if code >= 400 or not isinstance(payload, dict):
            raise RuntimeError(f"isolated session create failed: HTTP {code}")
        session_id = str(payload.get("id") or payload.get("session_id") or "")
        if not session_id:
            raise RuntimeError("isolated session create returned no id")
        return session_id

    def _run_isolated(self, session_id: str, command: str, timeout: float) -> tuple[int, Any]:
        body = json.dumps({"command": command}).encode("utf-8")
        return self._http(
            "POST",
            urljoin(self._base_url + "/", f"v1/isolated/session/{session_id}/run"),
            body,
            timeout,
        )

    def _run_non_isolated(self, command: str, timeout: float) -> tuple[int, Any]:
        body = json.dumps({"command": command}).encode("utf-8")
        return self._http(
            "POST",
            urljoin(self._base_url + "/", "v1/command"),
            body,
            timeout,
        )

    def _delete_session(self, session_id: str) -> None:
        if not self._base_url:
            return
        try:
            self._http(
                "DELETE",
                urljoin(self._base_url + "/", f"v1/isolated/session/{session_id}"),
                None,
                5.0,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("OpenSandbox session delete failed: %s", exc)

    @staticmethod
    def _normalize_payload(payload: Any) -> tuple[str, str, int]:
        if isinstance(payload, str):
            return payload, "", 0
        if not isinstance(payload, dict):
            return "", str(payload), 1
        stdout = str(payload.get("stdout") or payload.get("output") or "")
        stderr = str(payload.get("stderr") or payload.get("error") or "")
        exit_code = int(payload.get("exit_code", payload.get("returncode", 0)) or 0)
        return stdout, stderr, exit_code


_: ExecutionBackend = OpenSandboxBackend(base_url="http://127.0.0.1:9", use_isolated=False)

__all__ = ["OpenSandboxBackend"]
