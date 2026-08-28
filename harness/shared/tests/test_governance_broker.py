"""Tests for harness/shared/governance/broker.py -- ExecutionBroker.

Rewritten for the in-process decision point. The previous versions patched
``broker.subprocess.run`` module-wide to stand in for the PDP child process; with
a real execution engine behind the same attribute, those patches would have
silently intercepted the *engine* instead, and the tests would have passed while
testing nothing. Three of them also pinned behaviour that has since been
identified as a fail-open and removed -- ``test_pdp_skipped_when_files_absent``
asserted that a missing policy file skipped the verdict.

Spec: ``docs/specs/agent-containment.md`` (R-AC-11, R-AC-12).
"""

from __future__ import annotations

import json
import subprocess
import typing
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from harness.shared.governance.broker import (
    DEFAULT_MAX_OUTPUT_BYTES,
    ExecutionBroker,
    ExecutionResult,
    ProcessBackend,
    _cap,
)

pytestmark = pytest.mark.governance

IMPLEMENTER = {"agent_id": "implementer"}


class RecordingBackend(ProcessBackend):
    """A backend that records instead of spawning.

    The single ``_spawn`` seam is what keeps every branch of the real backend
    reachable without starting a process -- and what makes "did the broker
    execute anything?" a direct assertion rather than an inference.
    """

    def __init__(self, returncode: int = 0, stdout: str = "", stderr: str = "") -> None:
        super().__init__()
        self.calls: list[tuple[str, Path | None, int]] = []
        self._returncode, self._stdout, self._stderr = returncode, stdout, stderr

    def _spawn(self, command: str, cwd: Path | None, timeout: int) -> typing.Any:
        self.calls.append((command, cwd, timeout))
        return subprocess.CompletedProcess(
            args=command, returncode=self._returncode, stdout=self._stdout, stderr=self._stderr
        )


# ---------------------------------------------------------------------------
# verify_sandbox -- the default is now "probe", not "assume healthy"
# ---------------------------------------------------------------------------


def test_default_probes_the_backend_rather_than_assuming() -> None:
    """`sandbox_available: bool = True` meant a caller that never probed was told
    the sandbox was fine, so INV-9's branch was unreachable from the constructor
    most callers would write."""
    assert ExecutionBroker().verify_sandbox() is True  # a process backend is available


def test_explicit_unavailable_is_honoured() -> None:
    assert ExecutionBroker(sandbox_available=False).verify_sandbox() is False


def test_a_probe_that_raises_reads_as_unavailable() -> None:
    class Exploding(ProcessBackend):
        def available(self) -> bool:
            raise RuntimeError("probe failed")

    assert ExecutionBroker(backend=Exploding()).verify_sandbox() is False


# ---------------------------------------------------------------------------
# INV-9: backend unavailable -> BLOCKED, never host fallback
# ---------------------------------------------------------------------------


def test_unavailable_backend_returns_blocked() -> None:
    result = ExecutionBroker(sandbox_available=False).execute_command("git push origin main", IMPLEMENTER)
    assert result.status == "BLOCKED"
    assert result.exit_code == 1
    assert "host-process" in result.stderr.lower() or "sandbox" in result.stderr.lower()


def test_unavailable_backend_executes_nothing() -> None:
    backend = RecordingBackend()
    ExecutionBroker(sandbox_available=False, backend=backend).execute_command("ls", IMPLEMENTER)
    assert backend.calls == [], "a blocked command reached the backend"


# ---------------------------------------------------------------------------
# INV-9/INV-10: the policy verdict, in process
# ---------------------------------------------------------------------------


def test_action_is_derived_from_the_command_not_the_caller() -> None:
    """A caller-supplied action grades `pytest` and `rm -rf /` identically, and
    `human_approval_required_for` is then never reached."""
    backend = RecordingBackend()
    broker = ExecutionBroker(backend=backend)
    blocked = broker.execute_command("rm -rf /", {"agent_id": "implementer", "action": "test_execute"})
    assert blocked.status == "BLOCKED"
    assert blocked.action == "destructive"
    assert backend.calls == []


def test_an_allowed_action_reaches_the_backend() -> None:
    backend = RecordingBackend(stdout="ok")
    result = ExecutionBroker(backend=backend).execute_command("pytest -q", IMPLEMENTER)
    assert result.status == "SUCCESS"
    assert result.stdout == "ok"
    assert backend.calls and backend.calls[0][0] == "pytest -q"


def test_unknown_agent_identity_is_denied() -> None:
    result = ExecutionBroker(backend=RecordingBackend()).execute_command("echo hi", {"agent_id": "nobody"})
    assert result.status == "BLOCKED"
    assert "unknown agent identity" in result.reason


def test_a_role_without_the_action_is_denied() -> None:
    """`peer-reviewer` holds read and review_write; it may not write files."""
    result = ExecutionBroker(backend=RecordingBackend()).execute_command("mkdir out", {"agent_id": "peer-reviewer"})
    assert result.status == "BLOCKED"
    assert "not granted" in result.reason


def test_approval_gated_action_is_denied_without_approval() -> None:
    ctx = {"agent_id": "release-auditor"}
    result = ExecutionBroker(backend=RecordingBackend()).execute_command("curl https://example.test", ctx)
    assert result.status == "BLOCKED"
    assert "human approval" in result.reason


def test_approval_gated_action_is_allowed_with_approval() -> None:
    ctx = {"agent_id": "release-auditor", "human_approved": True}
    backend = RecordingBackend()
    result = ExecutionBroker(backend=backend).execute_command("curl https://example.test", ctx)
    assert result.status == "SUCCESS"
    assert backend.calls


def test_an_unreadable_authority_model_denies(tmp_path: Path) -> None:
    """The previous guard was `if _PDP_PATH.exists() and _POLICY_PATH.exists():`,
    so a missing file skipped the verdict rather than denying it."""
    backend = RecordingBackend()
    broker = ExecutionBroker(backend=backend, agent_policy_path=tmp_path / "absent.json")
    result = broker.execute_command("echo hi", IMPLEMENTER)
    assert result.status == "BLOCKED"
    assert "authority model could not be read" in result.reason
    assert backend.calls == []


def test_a_non_object_authority_model_denies(tmp_path: Path) -> None:
    bad = tmp_path / "agent-policy.json"
    bad.write_text("[]", encoding="utf-8")
    result = ExecutionBroker(backend=RecordingBackend(), agent_policy_path=bad).execute_command("echo hi", IMPLEMENTER)
    assert result.status == "BLOCKED"


def test_a_policy_declaring_no_agents_denies(tmp_path: Path) -> None:
    thin = tmp_path / "agent-policy.json"
    thin.write_text(json.dumps({"schema_version": "2.0.0"}), encoding="utf-8")
    result = ExecutionBroker(backend=RecordingBackend(), agent_policy_path=thin).execute_command("echo hi", IMPLEMENTER)
    assert result.status == "BLOCKED"
    assert "declares no agents" in result.reason


# ---------------------------------------------------------------------------
# INV-8: the command guard is on the path
# ---------------------------------------------------------------------------


def test_guard_denial_blocks_even_when_policy_allows(monkeypatch: pytest.MonkeyPatch) -> None:
    import harness.shared.governance.broker as broker_mod

    backend = RecordingBackend()
    monkeypatch.setattr(broker_mod, "check_command", MagicMock(return_value=2))
    result = ExecutionBroker(backend=backend).execute_command("pytest -q", IMPLEMENTER)
    assert result.status == "BLOCKED"
    assert "guard" in result.stderr.lower()
    assert backend.calls == []


# ---------------------------------------------------------------------------
# The engine: cwd, timeout and output cap are governed budgets, not defaults
# ---------------------------------------------------------------------------


def test_cwd_and_timeout_reach_the_backend(tmp_path: Path) -> None:
    """`execute_command` took neither. The orchestrator's whole contract is a
    pinned working directory and a policy-declared timeout, so a broker that
    dropped them would silently discard a governed budget."""
    backend = RecordingBackend()
    ExecutionBroker(backend=backend).execute_command("pytest -q", IMPLEMENTER, cwd=tmp_path, timeout=7)
    assert backend.calls == [("pytest -q", tmp_path, 7)]


def test_output_is_capped() -> None:
    backend = RecordingBackend(stdout="x" * 5000)
    result = ExecutionBroker(backend=backend, max_output_bytes=100).execute_command("pytest -q", IMPLEMENTER)
    assert len(result.stdout) < 5000
    assert "truncated" in result.stdout


def test_a_timeout_is_a_failure_not_a_block() -> None:
    class Slow(ProcessBackend):
        def _spawn(self, command: str, cwd: Path | None, timeout: int) -> typing.Any:
            raise subprocess.TimeoutExpired(cmd=command, timeout=timeout)

    result = ExecutionBroker(backend=Slow()).execute_command("pytest -q", IMPLEMENTER)
    assert result.status == "FAILED"
    assert "timed out" in result.reason


def test_a_backend_that_cannot_start_answers_rather_than_raising() -> None:
    class Broken(ProcessBackend):
        def _spawn(self, command: str, cwd: Path | None, timeout: int) -> typing.Any:
            raise OSError("no such interpreter")

    result = ExecutionBroker(backend=Broken()).execute_command("pytest -q", IMPLEMENTER)
    assert result.status == "FAILED"
    assert "could not be started" in result.reason


def test_a_failing_command_is_failed_not_blocked() -> None:
    """A non-zero exit is the command's verdict on itself, not the broker's."""
    result = ExecutionBroker(backend=RecordingBackend(returncode=1, stderr="boom")).execute_command(
        "pytest -q", IMPLEMENTER
    )
    assert result.status == "FAILED"
    assert result.stderr == "boom"
    assert result.reason == ""


def test_the_real_backend_runs_a_command(tmp_path: Path) -> None:
    """One test really spawns, so the seam cannot drift from the thing it stands
    in for. Deliberately trivial and fast."""
    result = ProcessBackend().run("echo hello", tmp_path, 10, DEFAULT_MAX_OUTPUT_BYTES)
    assert result.status == "SUCCESS"
    assert "hello" in result.stdout


def test_execution_result_fields() -> None:
    r = ExecutionResult(status="SUCCESS", stdout="o", stderr="e", exit_code=0)
    assert (r.status, r.stdout, r.stderr, r.exit_code, r.reason, r.action) == ("SUCCESS", "o", "e", 0, "", "")


class TestApprovalIsIdentityNotTruthiness:
    """`bool("false")` is True. A caller passing a string -- from a config file, a
    query parameter, an environment variable -- would otherwise grant approval for
    an action whose whole point is that a human signs first."""

    @pytest.mark.parametrize("value", ["yes", "false", "true", 1, "0", [1], object()])
    def test_a_truthy_non_boolean_does_not_approve(self, value: typing.Any) -> None:
        ctx = {"agent_id": "release-auditor", "human_approved": value}
        result = ExecutionBroker(backend=RecordingBackend()).execute_command("curl https://example.test", ctx)
        assert result.status == "BLOCKED", f"{value!r} was accepted as human approval"
        assert "human approval" in result.reason

    def test_only_the_boolean_approves(self) -> None:
        ctx = {"agent_id": "release-auditor", "human_approved": True}
        backend = RecordingBackend()
        assert ExecutionBroker(backend=backend).execute_command("curl https://example.test", ctx).status == "SUCCESS"
        assert backend.calls


class TestOutputCapIsMeasuredInBytes:
    """The cap is a containment control: captured output becomes a prompt, a
    signal-sink entry and an HTTP response body. `len(text)` counts code points,
    so a character cap named in bytes lets multibyte output exceed its own limit
    several times over."""

    @pytest.mark.parametrize("limit", [10, 100, 1000])
    def test_multibyte_output_respects_the_byte_limit(self, limit: int) -> None:
        capped = _cap("é" * 5000, limit)
        payload = capped.split("\n[truncated")[0]
        assert len(payload.encode("utf-8")) <= limit, "the cap counted characters, not bytes"

    def test_a_partial_character_is_dropped_not_mangled(self) -> None:
        """Slicing encoded bytes can split a character; the tail must not become
        a replacement char or raise."""
        capped = _cap("é" * 100, 5)
        assert capped.split("\n[truncated")[0] == "éé"

    def test_output_under_the_limit_is_untouched(self) -> None:
        assert _cap("short", DEFAULT_MAX_OUTPUT_BYTES) == "short"

    def test_the_truncation_marker_names_the_limit(self) -> None:
        assert "[truncated at 10 bytes]" in _cap("x" * 500, 10)


class TestExecutionEdgeCases:
    def test_a_missing_working_directory_is_a_failure_with_a_reason(self, tmp_path: Path) -> None:
        result = ExecutionBroker().execute_command("echo hi", IMPLEMENTER, cwd=tmp_path / "absent", timeout=5)
        assert result.status == "FAILED"
        assert "could not be started" in result.reason

    def test_a_missing_context_denies_rather_than_defaulting(self) -> None:
        """No caller context means no identity, and an unknown identity denies."""
        result = ExecutionBroker(backend=RecordingBackend()).execute_command("echo hi")
        assert result.status == "BLOCKED"
        assert "unknown agent identity" in result.reason


class TestTheBackendReallyEnforcesItsBudgets:
    """Every other backend test overrides `_spawn`, so `timeout=timeout` and
    `cwd=cwd` could both be deleted from `ProcessBackend._spawn` with the suite
    green. The branch also deleted the one real timeout test that existed
    (`sleep 5` under `tool_timeout=1`). These spawn for real."""

    @pytest.mark.slow
    def test_the_runtime_bound_is_enforced(self, tmp_path: Path) -> None:
        result = ProcessBackend().run("sleep 5", tmp_path, 1, DEFAULT_MAX_OUTPUT_BYTES)
        assert result.status == "FAILED"
        assert "timed out" in result.reason

    def test_the_working_directory_is_pinned(self, tmp_path: Path) -> None:
        result = ProcessBackend().run("pwd", tmp_path, 10, DEFAULT_MAX_OUTPUT_BYTES)
        assert result.status == "SUCCESS"
        assert str(tmp_path.resolve()) in result.stdout, "the command did not run in the pinned directory"
