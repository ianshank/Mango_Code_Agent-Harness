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
    _load_json,
)
from harness.shared.tests.conftest import POSIX_ONLY

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


class TestLoadJsonPreservesItsPreRefactorExceptionTypes:
    """R-DH-5: `_load_json` adopted the shared, non-raising `governance_json`
    classifier, but each caller must keep raising its own existing exception
    type. `execute_command` catches `Exception` broadly either way, so this is
    invisible at the `ExecutionBroker` level -- exactly why it needs its own
    direct coverage rather than relying on the BLOCKED-result tests above.
    """

    def test_a_missing_file_raises_file_not_found_error(self, tmp_path: Path) -> None:
        with pytest.raises(FileNotFoundError):
            _load_json(tmp_path / "absent.json")

    def test_an_unreadable_path_raises_os_error(self, tmp_path: Path) -> None:
        """A directory is a portable non-FileNotFoundError OSError: unlike a
        chmod'd file, IsADirectoryError fires the same way whether or not the
        caller happens to be running as root."""
        target = tmp_path / "a_directory"
        target.mkdir()
        with pytest.raises(OSError):
            _load_json(target)

    def test_malformed_json_raises_value_error(self, tmp_path: Path) -> None:
        target = tmp_path / "broken.json"
        target.write_text("{not json", encoding="utf-8")
        with pytest.raises(ValueError):
            _load_json(target)

    def test_a_non_object_json_document_raises_value_error(self, tmp_path: Path) -> None:
        target = tmp_path / "array.json"
        target.write_text("[1, 2, 3]", encoding="utf-8")
        with pytest.raises(ValueError):
            _load_json(target)

    def test_a_valid_object_loads(self, tmp_path: Path) -> None:
        target = tmp_path / "policy.json"
        target.write_text('{"a": 1}', encoding="utf-8")
        assert _load_json(target) == {"a": 1}


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

    @POSIX_ONLY
    def test_the_working_directory_is_pinned(self, tmp_path: Path) -> None:
        result = ProcessBackend().run("pwd", tmp_path, 10, DEFAULT_MAX_OUTPUT_BYTES)
        assert result.status == "SUCCESS"
        assert str(tmp_path.resolve()) in result.stdout, "the command did not run in the pinned directory"


class TestARedirectAlsoRequiresTheWriteAction:
    """`classify` returns the strictest single action, which is what the PDP
    takes -- but the strictest is not always the write. `pytest -q > x.txt`
    grades `test_execute`, and a role holding `test_execute` without `write`
    would then write a file through the redirect.

    The verifier is exactly that role, and "the role that judges the work cannot
    edit the work" (R-AC-8) is what this protects. A command exercises a *set* of
    actions and every one must be granted.
    """

    def test_the_verifier_cannot_write_under_a_test_execute_grade(self, tmp_path: Path) -> None:
        result = ExecutionBroker().execute_command(
            "pytest -q > out.txt", {"agent_id": "test-eval"}, cwd=tmp_path, timeout=10
        )
        assert result.status == "BLOCKED"
        assert "write" in (result.reason or "")
        assert not (tmp_path / "out.txt").exists()

    def test_the_verifier_may_still_run_tests_without_redirecting(self, tmp_path: Path) -> None:
        """Control: the write requirement must attach to the redirect, not to
        `test_execute`. A gate that denied the verifier every test run would
        pass the assertion above and be useless."""
        result = ExecutionBroker().execute_command(
            "true", {"agent_id": "test-eval"}, cwd=tmp_path, timeout=10
        )
        assert result.status != "BLOCKED", result.reason

    def test_the_implementer_may_still_redirect(self, tmp_path: Path) -> None:
        """Control: the implementer holds `write`, so ordinary redirection is
        unaffected."""
        result = ExecutionBroker().execute_command(
            "echo ok > allowed.txt", {"agent_id": "implementer"}, cwd=tmp_path, timeout=10
        )
        assert result.status == "SUCCESS", result.reason
        assert (tmp_path / "allowed.txt").read_text(encoding="utf-8").strip() == "ok"


class TestFdRedirectsCannotReachTheControlSurface:
    """End-to-end for the reported bypass: the classifier missed `1>`/`2>`, so
    the write policy was handed no target to check."""

    @pytest.mark.parametrize(
        "relpath",
        [
            pytest.param(".git/hooks/pre-commit", id="git-hook"),
            pytest.param("Makefile", id="protected-file"),
            pytest.param(".mango/hooks/post-verifier-run.sh", id="agent-hook"),
        ],
    )
    @pytest.mark.parametrize("op", ["1>", "2>", ">", ">>"])
    def test_the_write_is_refused_and_the_file_is_untouched(
        self, tmp_path: Path, relpath: str, op: str
    ) -> None:
        target = tmp_path / relpath
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("ORIGINAL\n", encoding="utf-8")

        result = ExecutionBroker().execute_command(
            f"echo PWNED {op}{relpath}", {"agent_id": "implementer"}, cwd=tmp_path, timeout=10
        )
        assert result.status == "BLOCKED", f"{op}{relpath} was permitted"
        assert target.read_text(encoding="utf-8") == "ORIGINAL\n", (
            f"{op}{relpath} was refused but the file changed anyway"
        )


class TestBrokeredCommandsDoNotInheritCredentials:
    """`_run_hook` filtered the environment; `_spawn` did not — and `_spawn` is
    the path the model actually controls.

    `agent-policy.json` declares `secrets_may_not_be_propagated_to_subagents`.
    `env` and `printenv` are graded `secret_access` and denied, but the action
    model cannot enumerate every spelling: `cat /proc/self/environ` is `cat`,
    which grades `read`, an action every role holds.
    """

    CANARIES = {
        "NVIDIA_API_KEY": "nvapi-CANARY-0123456789abcdef",
        "AGENT_EVIDENCE_KEY": "EVIDENCE-CANARY-0123456789",
        "API_SERVER_KEY": "SERVER-CANARY-0123456789",
    }

    @pytest.mark.parametrize("agent_id", ["implementer", "test-eval"])
    def test_credentials_do_not_reach_a_brokered_command(
        self, agent_id: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        for name, value in self.CANARIES.items():
            monkeypatch.setenv(name, value)
        result = ExecutionBroker().execute_command(
            "cat /proc/self/environ", {"agent_id": agent_id}, cwd=tmp_path, timeout=10
        )
        blob = (result.stdout or "") + (result.stderr or "")
        leaked = [name for name, value in self.CANARIES.items() if value in blob]
        assert not leaked, (
            f"{leaked} reached an agent-authored command's environment. AGENT_EVIDENCE_KEY "
            "is the HMAC key evidence manifests are signed with, so this is forgery, not "
            "only disclosure."
        )

    @POSIX_ONLY
    def test_the_command_still_runs_and_still_sees_ordinary_variables(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Control: a filter that emptied the environment would satisfy the test
        above and break every build command the agent runs."""
        monkeypatch.setenv("MANGO_ORDINARY_VARIABLE", "kept")
        result = ExecutionBroker().execute_command(
            "printf '%s' \"$MANGO_ORDINARY_VARIABLE\"",
            {"agent_id": "implementer"}, cwd=tmp_path, timeout=10,
        )
        assert result.status == "SUCCESS", result.reason
        assert "kept" in (result.stdout or "")


class TestTheAvailabilityProbeIsAProbe:
    """`test_default_probes_the_backend_rather_than_assuming` asserts
    `ExecutionBroker().verify_sandbox() is True`, and a backend hardcoding
    `available() -> True` satisfies it exactly as well as one that checks. The
    test's *name* was the only thing separating the defect from the fix, so
    INV-9's no-fallback branch was unreachable in production either way.

    These distinguish them: a backend whose shell does not exist must read as
    unavailable, and execution must then be BLOCKED rather than fall back.
    """

    def test_a_backend_whose_shell_is_missing_is_unavailable(self) -> None:
        class NoShell(ProcessBackend):
            shell = "definitely-not-a-real-shell-b7f3a1"

        assert NoShell().available() is False

    def test_a_backend_whose_shell_fails_is_unavailable(self) -> None:
        """Present and runnable is not enough: `exit 0` must actually succeed."""
        class BrokenShell(ProcessBackend):
            shell = "false"

        assert BrokenShell().available() is False

    def test_a_real_shell_is_available(self) -> None:
        """Positive control. Both assertions above are satisfied by a probe that
        returns False unconditionally, which would block every command."""
        assert ProcessBackend().available() is True

    def test_an_unavailable_backend_blocks_rather_than_falling_back(self, tmp_path: Path) -> None:
        """INV-9 end to end, through the branch that was unreachable."""
        class NoShell(ProcessBackend):
            shell = "definitely-not-a-real-shell-b7f3a1"

        result = ExecutionBroker(backend=NoShell()).execute_command(
            "echo hi", {"agent_id": "implementer"}, cwd=tmp_path, timeout=10
        )
        assert result.status == "BLOCKED"
        assert "unavailable" in (result.reason or "").lower()

    def test_the_probe_runs_once_per_backend(self) -> None:
        """Cached: `verify_sandbox` is consulted on every `execute_command`, and
        an uncached probe would spawn a process per tool call to answer a
        question whose answer cannot change within a run."""
        backend = ProcessBackend()
        calls = {"n": 0}
        real = backend._probe

        def counting() -> bool:
            calls["n"] += 1
            return real()

        backend._probe = counting  # type: ignore[method-assign]
        assert backend.available() is True
        assert backend.available() is True
        assert calls["n"] == 1
