"""Subprocess execution backend and stream capture containment."""

from __future__ import annotations

import logging
import os
import subprocess
from dataclasses import dataclass
from pathlib import Path

from harness.shared.debug_dump import credential_env_names

logger = logging.getLogger(__name__)

#: Captured output ceiling. An unbounded capture becomes a prompt, a signal sink
#: entry and an HTTP response body, so the cap is a containment control rather
#: than an ergonomic one.
DEFAULT_MAX_OUTPUT_BYTES = 64 * 1024

#: Wall-clock ceiling used when a caller supplies none.
DEFAULT_TIMEOUT_SEC = 30


@dataclass
class ExecutionResult:
    """The outcome of an execution attempt."""

    status: str  # "SUCCESS", "FAILED", "BLOCKED"
    stdout: str
    stderr: str
    exit_code: int
    #: Why the broker reached this status. Empty for a plain command failure,
    #: where the command's own stderr is the explanation.
    reason: str = ""
    #: The action the command was classified as, recorded so an evidence entry
    #: can state what was decided rather than only what was run.
    action: str = ""


def _cap(text: str, limit: int) -> str:
    """Truncate ``text`` to ``limit`` **bytes**, not characters.

    ``len(text)`` counts code points, so a character cap named in bytes lets
    multibyte output exceed its own limit several times over -- and this cap is a
    containment control, because captured output becomes a prompt, a signal-sink
    entry and an HTTP response body. Slicing encoded bytes can split a character,
    so the tail is decoded with ``errors="ignore"`` to drop a partial one.
    """
    encoded = text.encode("utf-8")
    if len(encoded) <= limit:
        return text
    return encoded[:limit].decode("utf-8", errors="ignore") + f"\n[truncated at {limit} bytes]"


class ProcessBackend:
    """Runs a command as a child process with a pinned cwd, a timeout and an
    output cap. Available wherever the interpreter is.

    The single ``_spawn`` indirection is the seam every test uses: everything
    else in this class is argument assembly and result normalisation, which is
    what keeps the module coverable without spawning anything.
    """

    name = "process"
    version = "1.0.0"

    #: The interpreter commands are handed to. Named once so the availability
    #: probe and the spawn cannot disagree about what "available" refers to.
    shell = "bash"

    #: Seconds the probe may take. It runs `exit 0`, so anything approaching this
    #: means the shell is wedged rather than slow, which is itself unavailable.
    probe_timeout_sec = 5

    def __init__(self) -> None:
        self._probed: bool | None = None

    def available(self) -> bool:
        """Whether this backend can actually start a process."""
        if self._probed is None:
            self._probed = self._probe()
        return self._probed

    def _probe(self) -> bool:
        try:
            completed = subprocess.run(
                [self.shell, "-c", "exit 0"],
                capture_output=True,
                timeout=self.probe_timeout_sec,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            logger.warning("Backend probe failed to run %s: %s", self.shell, exc)
            return False
        return completed.returncode == 0

    def _spawn(
        self, command: str, cwd: Path | None, timeout: int
    ) -> subprocess.CompletedProcess[str]:
        # Filter credentials from environment for security invariants
        denied = set(credential_env_names())
        env = {k: v for k, v in os.environ.items() if k not in denied}
        return subprocess.run(
            [self.shell, "-c", command],
            cwd=str(cwd) if cwd else None,
            capture_output=True,
            encoding="utf-8",
            timeout=timeout,
            env=env,
        )

    def run(self, command: str, cwd: Path | None, timeout: int, max_output_bytes: int) -> ExecutionResult:
        try:
            completed = self._spawn(command, cwd, timeout)
        except subprocess.TimeoutExpired:
            return ExecutionResult("FAILED", "", "", 1, reason=f"command timed out after {timeout}s")
        except Exception as exc:  # noqa: BLE001 - the backend must answer every call
            return ExecutionResult("FAILED", "", "", 1, reason=f"command could not be started: {exc}")

        stdout = _cap(completed.stdout or "", max_output_bytes)
        stderr = _cap(completed.stderr or "", max_output_bytes)
        status = "SUCCESS" if completed.returncode == 0 else "FAILED"
        return ExecutionResult(status, stdout, stderr, completed.returncode)


__all__ = [
    "DEFAULT_MAX_OUTPUT_BYTES",
    "DEFAULT_TIMEOUT_SEC",
    "ExecutionResult",
    "ProcessBackend",
    "_cap",
]
