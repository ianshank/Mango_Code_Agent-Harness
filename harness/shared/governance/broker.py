"""Execution broker enforcing governance constraints.

``ExecutionBroker`` is the approved execution path INV-8 names. Until this change
it had no production caller and ``execute_command`` ended at
``FAILED: Execution engine not fully implemented``, so INV-8 was declared and
unreached.

Three fail-open shapes are removed here:

* ``sandbox_available: bool = True`` -- a caller that forgot to probe was told
  the sandbox was fine, and INV-9's no-fallback branch was never taken;
* ``if _PDP_PATH.exists() and _POLICY_PATH.exists():`` -- a missing file skipped
  the policy verdict rather than denying it; and
* the decision point ran as a host subprocess from a path inside the agent's
  workspace, *before* the command guard, so replacing that file replaced the
  verdict. It is evaluated in process now (``policy_decision``).

**What this backend is.** ``ProcessBackend`` pins the working directory, bounds
the runtime, and caps captured output. That is containment, not isolation: it
does not confine the filesystem or the network, so a command it runs can still
reach both. INV-13's sandbox digest is therefore not yet satisfiable, and no
result produced here claims to be. Isolation is a later capability profile;
splitting it out is deliberate, because the isolation primitive cannot be
exercised on this repository's CI runners and a gate that cannot run is the
defect this programme exists to close.

Spec: ``docs/specs/agent-containment.md`` (R-AC-11, R-AC-12).
"""

from __future__ import annotations

import dataclasses
import logging
from collections.abc import Mapping
from pathlib import Path
from typing import Any, Final

from harness.shared.debug_dump import redact_text
from harness.shared.governance_json import read_json_object
from harness.shared.write_policy import write_denial_reason

from .command_actions import classify, write_targets
from .policy_decision import decide
from .pretooluse_guard import check_command
from .process_backend import (
    DEFAULT_MAX_OUTPUT_BYTES as DEFAULT_MAX_OUTPUT_BYTES,
)
from .process_backend import (
    DEFAULT_TIMEOUT_SEC as DEFAULT_TIMEOUT_SEC,
)
from .process_backend import (
    ExecutionResult as ExecutionResult,
)
from .process_backend import (
    ProcessBackend as ProcessBackend,
)
from .process_backend import (
    _cap as _cap,
)

logger = logging.getLogger(__name__)

#: The authority model, resolved next to this package so it travels with the
#: installed harness rather than being read out of the agent's workspace.
_AGENT_POLICY_PATH: Final[Path] = Path(__file__).resolve().parent.parent / "agent-policy.json"


class ExecutionBroker:
    """The central execution broker for governed execution."""

    def __init__(
        self,
        sandbox_available: bool | None = None,
        backend: ProcessBackend | None = None,
        agent_policy_path: Path | None = None,
        max_output_bytes: int = DEFAULT_MAX_OUTPUT_BYTES,
    ) -> None:
        """``sandbox_available`` defaults to ``None``, meaning *probe the backend*.

        It used to default to ``True``: a caller that never probed was told the
        sandbox was healthy, so INV-9's no-fallback branch was unreachable from
        the constructor most callers would write. An explicit bool is still
        honoured, which is what lets a test drive the unavailable path.
        """
        self._sandbox_available = sandbox_available
        self._backend = backend or ProcessBackend()
        self._agent_policy_path = agent_policy_path or _AGENT_POLICY_PATH
        self._max_output_bytes = max_output_bytes

    def verify_sandbox(self) -> bool:
        """Verify the execution backend is available and healthy."""
        if self._sandbox_available is not None:
            return self._sandbox_available
        try:
            return bool(self._backend.available())
        except Exception:  # noqa: BLE001 - a probe that raises has not proved the
            # backend healthy, and "unproven" must read as unavailable.
            logger.warning("Backend availability probe failed; treating the backend as unavailable")
            return False

    def _policy_decision(self, command: str, context: Mapping[str, Any]) -> ExecutionResult | None:
        """Return a BLOCKED result when policy denies, else ``None``."""
        agent_id = context.get("agent_id", "unknown")
        # Identity, not truthiness. `bool("false")` is True, so a caller passing a
        # string -- from a config file, a query parameter, an environment variable
        # -- would grant approval for an action whose whole point is that a human
        # signs first. Only a real boolean True approves.
        human_approved = context.get("human_approved", False) is True

        # The action is derived from the command, never taken from the caller.
        # A caller-supplied constant grades `pytest` and `rm -rf /` identically,
        # and `human_approval_required_for` is then never reached.
        classification = classify(command)
        action = classification.action

        # A command exercises a *set* of actions, and every one must be granted.
        # `classify` returns the strictest single action, which is what the PDP
        # takes -- but the strictest is not always the write: `pytest -q > x.txt`
        # grades `test_execute`, and a role holding `test_execute` without `write`
        # would then write a file through the redirect. The verifier is exactly
        # that role, and "the role that judges the work cannot edit the work" is
        # the property R-AC-8 exists for.
        extra_actions = ["write"] if write_targets(command) else []

        try:
            policy = _load_json(self._agent_policy_path)
        except Exception as exc:  # noqa: BLE001 - an unreadable authority model
            # denies. Skipping the verdict, which the previous `exists()` guard
            # did, is the fail-open this change removes.
            reason = f"BLOCKED: the authority model could not be read: {exc}"
            return ExecutionResult(
                "BLOCKED", "", reason, 1,
                reason=reason,
                action=action,
            )

        for required in [action, *extra_actions]:
            verdict = decide(agent_id, required, policy, human_approved=human_approved)
            if not verdict.allowed:
                logger.warning("Policy denied execution: agent=%s action=%s", agent_id, required)
                why = (
                    classification.reason if required == action
                    else "the command writes to a file, which requires the write action"
                )
                reason = f"BLOCKED: {verdict.reason} (classified as {required}: {why})"
                return ExecutionResult(
                    "BLOCKED", "", reason, 1,
                    reason=reason,
                    action=action,
                )
        return None

    def execute_command(
        self,
        command: str,
        context: Mapping[str, Any] | None = None,
        cwd: Path | None = None,
        timeout: int = DEFAULT_TIMEOUT_SEC,
    ) -> ExecutionResult:
        """Execute a command through the approved path.

        Enforces INV-8 (the guard is on the path), INV-9 (no host fallback when
        the backend is unavailable) and INV-10 (a denial is terminal: this method
        never retries or downgrades a DENY).

        ``cwd`` and ``timeout`` are parameters rather than backend defaults
        because the orchestrator's contract is a pinned working directory and a
        policy-declared ``tool_timeout_sec``; a broker that dropped them would
        silently discard a governed budget.
        """
        context = context or {}
        action = classify(command).action

        # INV-9: no host-process fallback when the backend cannot be used.
        if not self.verify_sandbox():
            # Redacted: a denial is precisely when the command is most likely to carry a
            # credential -- `git push https://user:TOKEN@host`, `curl -H "Authorization: ..."`.
            logger.warning("Backend unavailable; blocking execution of: %s", redact_text(command))
            return ExecutionResult(
                "BLOCKED", "",
                "BLOCKED: Sandbox unavailable; host-process execution fallback is strictly prohibited.",
                1,
                reason="BLOCKED: the execution backend is unavailable",
                action=action,
            )

        denial = self._policy_decision(command, context)
        if denial is not None:
            return denial

        # The write policy is a property of the broker, not of one tool handler.
        # Enforcing it only in `write_file` left `run_command` as an unguarded
        # second door to the same paths: `echo x > .git/hooks/pre-commit` is
        # `echo` by argv[0] and a host-executed hook installation by effect.
        # `write_denial` is deliberately not named `denial`: that name already holds
        # the PDP's `ExecutionResult | None` above, and reusing it silently widens
        # the type. mypy caught it; the reader would not have.
        for target in write_targets(command):
            write_denial = write_denial_reason(target)
            if write_denial is not None:
                logger.warning("Denied a command writing to a governed path: %s", target)
                return ExecutionResult(
                    "BLOCKED", "", f"BLOCKED: {write_denial}", 1,
                    reason=f"BLOCKED: the command writes to {target}, which is denied: {write_denial}",
                    action=action,
                )

        # INV-8: every execution request passes the command guard.
        # `timeout=timeout` bounds the guard's own destination-check subprocess by
        # the caller's budget; `redact_text` because a blocked command is exactly
        # when it is most likely to carry a credential -- `git push https://user:TOKEN@host`.
        if check_command(command, timeout=timeout) != 0:
            logger.warning("PreToolUse guard blocked command: %s", redact_text(command))
            return ExecutionResult(
                "BLOCKED", "", "BLOCKED: Command failed pretooluse_guard policy evaluation.", 2,
                reason="BLOCKED: the command guard denied this command", action=action,
            )

        result = self._backend.run(command, cwd, timeout, self._max_output_bytes)
        if result.action != action:
            result = dataclasses.replace(result, action=action)
        return result


def _load_json(path: Path) -> dict[str, Any]:
    result = read_json_object(path)
    if result.error is not None:
        raise ValueError(f"{path}: {result.detail}")
    assert result.value is not None
    return result.value


__all__ = [
    "DEFAULT_MAX_OUTPUT_BYTES",
    "DEFAULT_TIMEOUT_SEC",
    "ExecutionBroker",
    "ExecutionResult",
    "ProcessBackend",
    "_cap",
]
