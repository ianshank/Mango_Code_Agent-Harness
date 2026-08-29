"""The verdict is earned by the harness, and can only be derived from what it ran.

Spec: ``docs/specs/verdict-propagation.md`` (R-VP-1, R-VP-3 … R-VP-10).

The defect these pin: the loop returned the verifier agent's prose and nothing
read it. Deriving a verdict from the *agent's* command results would not have
fixed it -- a verifier running ``true`` produces SUCCESS/exit 0 -- so the verdict
comes from a check the harness selected, and ``derive_verdict`` will not accept
anything else.
"""
from __future__ import annotations

import typing
from pathlib import Path

import pytest

from harness.shared.governance.broker import ExecutionResult
from harness.shared.governance.verdict import (
    BLOCKED,
    DENIED,
    FAILED,
    FAILED_CHECK,
    HARNESS_FAULT,
    NOT_CONFIGURED,
    REENTRANT,
    UNAVAILABLE,
    UNRECOGNISED,
    VERIFIED,
    HarnessCheck,
    derive_verdict,
    not_configured,
    reentrant,
)
from harness.shared.governance.verification import REENTRANCY_ENV, VerificationRunner

pytestmark = pytest.mark.governance


def _check(**overrides: typing.Any) -> HarnessCheck:
    """A passing check, overridable one field at a time."""
    base = {
        "target": "test-python",
        "command": "make -f Makefile test-python",
        "status": "SUCCESS",
        "exit_code": 0,
        "reason": "",
        "probe_ok": True,
        "latency_ms": 12,
    }
    base.update(overrides)
    return HarnessCheck(**base)  # type: ignore[arg-type]


class TestOnlyAHarnessCheckIsGraded:
    def test_an_execution_result_is_refused(self) -> None:
        """AC-7 / R-VP-8. The agent's own result is the thing that must not grade.

        `ExecutionResult` and `HarnessCheck` carry similar fields, so without a
        type refusal the distinction would be positional -- a property of the call
        site, which a refactor loses silently.
        """
        with pytest.raises(TypeError, match="model authorship at one remove"):
            derive_verdict(ExecutionResult("SUCCESS", "", "", 0))

    @pytest.mark.parametrize("value", [None, "VERIFIED", 0, {"status": "SUCCESS"}])
    def test_nothing_else_grades_either(self, value: typing.Any) -> None:
        with pytest.raises(TypeError):
            derive_verdict(value)


class TestDerivation:
    def test_a_clean_run_verifies(self) -> None:
        """Positive control. A derivation that returned BLOCKED unconditionally
        would satisfy every other assertion in this class."""
        verdict = derive_verdict(_check())
        assert verdict.status == VERIFIED
        assert verdict.is_pass is True
        assert verdict.termination_reason == ""

    def test_a_failed_probe_blocks_rather_than_fails(self) -> None:
        """AC-4 / R-VP-9. A toolchain condition is not a failure of the change."""
        verdict = derive_verdict(_check(probe_ok=False, status="BLOCKED", exit_code=-1))
        assert (verdict.status, verdict.termination_reason) == (BLOCKED, UNAVAILABLE)

    def test_a_non_zero_exit_under_a_failed_probe_is_not_a_failure(self) -> None:
        """The ordering matters: probe_ok is checked before the exit code, so a
        missing build target cannot be reported as a failing suite."""
        verdict = derive_verdict(_check(probe_ok=False, status="FAILED", exit_code=2))
        assert verdict.status == BLOCKED

    def test_a_broker_denial_blocks(self) -> None:
        verdict = derive_verdict(_check(status="BLOCKED", exit_code=1, reason="denied by policy"))
        assert (verdict.status, verdict.termination_reason) == (BLOCKED, DENIED)

    def test_a_denial_without_a_reason_still_blocks_with_one(self) -> None:
        verdict = derive_verdict(_check(status="BLOCKED", exit_code=1, reason=""))
        assert verdict.status == BLOCKED
        assert "denied by policy" in verdict.reason

    def test_a_timeout_is_a_harness_fault_not_a_failure(self) -> None:
        """A reason on a FAILED result is set only for a timeout or a spawn
        failure; an ordinary non-zero exit leaves it empty."""
        verdict = derive_verdict(_check(status="FAILED", exit_code=1, reason="command timed out after 300s"))
        assert (verdict.status, verdict.termination_reason) == (BLOCKED, HARNESS_FAULT)

    def test_an_ordinary_non_zero_exit_fails(self) -> None:
        verdict = derive_verdict(_check(status="FAILED", exit_code=1, reason=""))
        assert (verdict.status, verdict.termination_reason) == (FAILED, FAILED_CHECK)
        assert verdict.is_pass is False

    def test_success_reported_with_a_non_zero_exit_does_not_pass(self) -> None:
        """AC-8 / R-VP-10. Synthetic: `ProcessBackend` cannot produce this shape.

        The broker takes an injected backend, so a verdict trusting a single field
        a foreign backend fills in is the `sandbox_available = True` fail-open
        shape this repository has been removing. A mutant deleting either half of
        the test survives every end-to-end case; only this pair catches it.
        """
        assert derive_verdict(_check(status="SUCCESS", exit_code=1)).status == FAILED

    def test_failed_reported_with_a_zero_exit_does_not_pass(self) -> None:
        """The other half of the same pair."""
        assert derive_verdict(_check(status="FAILED", exit_code=0)).status == FAILED

    def test_an_unrecognised_status_blocks(self) -> None:
        verdict = derive_verdict(_check(status="WEIRD"))
        assert (verdict.status, verdict.termination_reason) == (BLOCKED, UNRECOGNISED)

    def test_the_verdict_carries_the_command_and_exit_code(self) -> None:
        """AC-11 / R-VP-13. The verdict word alone overstates what was checked."""
        verdict = derive_verdict(_check(status="FAILED", exit_code=3, reason=""))
        assert verdict.command == "make -f Makefile test-python"
        assert verdict.exit_code == 3

    def test_the_verdict_command_carries_the_dash_f_makefile_pin_not_just_the_target(self) -> None:
        """R-VP-3. `HarnessCheck.target` is the bare Make target; `Verdict.command`
        must be the full invocation, or the `-f Makefile` provenance that defeats
        the `GNUmakefile` shadow attack is lost between the runner and the reader.
        """
        verdict = derive_verdict(_check(target="test-python", command="make -f Makefile test-python"))
        assert verdict.command != verdict.command.split()[-1]  # more than the bare target
        assert verdict.command.startswith("make -f Makefile")


class TestUnrunnableStates:
    def test_not_configured_is_blocked_never_failed(self) -> None:
        """AC-3 / R-VP-4. An adopter that configures nothing is told so."""
        verdict = not_configured()
        assert (verdict.status, verdict.termination_reason) == (BLOCKED, NOT_CONFIGURED)
        assert verdict.is_pass is False

    def test_reentrant_is_blocked(self) -> None:
        verdict = reentrant("test-python")
        assert (verdict.status, verdict.termination_reason) == (BLOCKED, REENTRANT)


class TestEveryVerdictIsLogged:
    """The outcome distribution must be observable, not just derivable.

    `_emit` is the one choke point all three constructors share -- these tests
    exercise all three, not just `derive_verdict`, since a gap in
    `not_configured`/`reentrant` alone would still leave the tally blind to
    every `BLOCKED` run that never reaches a check at all.
    """

    def test_a_pass_is_logged_with_its_status(self, caplog: pytest.LogCaptureFixture) -> None:
        with caplog.at_level("INFO"):
            derive_verdict(_check())
        assert "status=VERIFIED" in caplog.text

    def test_a_failure_logs_its_termination_reason(self, caplog: pytest.LogCaptureFixture) -> None:
        with caplog.at_level("INFO"):
            derive_verdict(_check(status="FAILED", exit_code=1, reason=""))
        assert "status=FAILED" in caplog.text
        assert "termination_reason=verification_failed" in caplog.text

    def test_not_configured_is_logged(self, caplog: pytest.LogCaptureFixture) -> None:
        with caplog.at_level("INFO"):
            not_configured("test-python")
        assert "termination_reason=verification_not_configured" in caplog.text

    def test_reentrant_is_logged(self, caplog: pytest.LogCaptureFixture) -> None:
        with caplog.at_level("INFO"):
            reentrant("test-python")
        assert "termination_reason=verification_reentrant" in caplog.text

    def test_the_logger_is_named_after_this_module(self, caplog: pytest.LogCaptureFixture) -> None:
        """The plan's own documented operator query (``grep '"logger":
        "harness.shared.governance.verdict"'``) only works if every record is
        emitted under this module's own name, not the root logger."""
        with caplog.at_level("INFO"):
            derive_verdict(_check())
        assert caplog.records[-1].name == "harness.shared.governance.verdict"

    def test_command_and_exit_code_both_reach_the_log(self, caplog: pytest.LogCaptureFixture) -> None:
        """An operator tallying `FAILED` without `command` cannot tell which
        configured target failed if more than one target is ever added."""
        with caplog.at_level("INFO"):
            derive_verdict(_check(status="FAILED", exit_code=3, reason=""))
        assert "command='make -f Makefile test-python'" in caplog.text
        assert "exit_code=3" in caplog.text


class RecordingBroker:
    """Records every command it is asked to run, and answers from a script.

    A seam rather than a monkeypatch of `subprocess`: patching module-wide would
    intercept the engine instead, and the tests would pass while testing nothing.
    """

    def __init__(self, answers: dict[str, ExecutionResult] | None = None) -> None:
        self.commands: list[str] = []
        self._answers = answers or {}

    def execute_command(
        self, command: str, _ctx: dict, cwd: Path | None = None, timeout: int = 0
    ) -> ExecutionResult:
        self.commands.append(command)
        for fragment, answer in self._answers.items():
            if fragment in command:
                return answer
        return ExecutionResult("SUCCESS", "", "", 0)


def _ok(stdout: str = "") -> ExecutionResult:
    return ExecutionResult("SUCCESS", stdout, "", 0)


class TestTheRunner:
    def test_the_command_names_the_makefile(self, tmp_path: Path) -> None:
        """AC-2 / R-VP-3. GNU Make searches GNUmakefile, then makefile, then
        Makefile. Only `Makefile` is a protected path, so an agent holding `write`
        can add a `GNUmakefile` whose target is a no-op. `-f Makefile` removes the
        search; without it the check is defeated in one tool call.
        """
        runner = VerificationRunner(RecordingBroker(), "test-eval")
        assert "-f Makefile" in runner.command
        assert runner.command.endswith("test-python")

    def test_the_probe_is_a_dry_run(self, tmp_path: Path) -> None:
        """AC-6 / R-VP-7. A probe that ran the target would recurse: the target
        runs the suite that contains this module."""
        broker = RecordingBroker()
        runner = VerificationRunner(broker, "test-eval")
        runner.probe(tmp_path)
        assert any("-n" in c for c in broker.commands)
        assert not any(c == runner.command for c in broker.commands)

    def test_a_missing_target_is_not_runnable(self, tmp_path: Path) -> None:
        """AC-4. Exit 2 with no broker reason is otherwise a failing suite."""
        broker = RecordingBroker({"-n": ExecutionResult("FAILED", "", "No rule to make target", 2)})
        ok, detail = VerificationRunner(broker, "test-eval").probe(tmp_path)
        assert ok is False
        assert "not a target" in detail

    def test_a_missing_program_is_not_runnable(self, tmp_path: Path) -> None:
        """A recipe naming an absent program also exits non-zero with no reason."""
        broker = RecordingBroker(
            {
                "-n": _ok("pnpm exec vitest run\n"),
                "command -v pnpm": ExecutionResult("FAILED", "", "", 1),
            }
        )
        ok, detail = VerificationRunner(broker, "test-eval").probe(tmp_path)
        assert ok is False
        assert "pnpm" in detail

    def test_a_present_program_is_runnable(self, tmp_path: Path) -> None:
        """Positive control: a census that reported everything missing would
        satisfy the two assertions above and make the feature unreachable."""
        broker = RecordingBroker({"-n": _ok("python -m pytest -q\n")})
        ok, detail = VerificationRunner(broker, "test-eval").probe(tmp_path)
        assert (ok, detail) == (True, "")

    def test_recipe_lines_that_are_comments_or_assignments_are_not_programs(
        self, tmp_path: Path
    ) -> None:
        broker = RecordingBroker({"-n": _ok("# a comment\nFOO=bar\n/usr/bin/env true\n")})
        ok, _ = VerificationRunner(broker, "test-eval").probe(tmp_path)
        assert ok is True
        assert not any("command -v" in c for c in broker.commands)

    def test_an_unbalanced_quote_in_a_recipe_is_skipped(self, tmp_path: Path) -> None:
        broker = RecordingBroker({"-n": _ok('echo "unterminated\n')})
        ok, _ = VerificationRunner(broker, "test-eval").probe(tmp_path)
        assert ok is True

    def test_running_reports_the_broker_result(self, tmp_path: Path) -> None:
        broker = RecordingBroker({"-n": _ok(), "-f Makefile test-python": ExecutionResult("FAILED", "", "", 1)})
        check = VerificationRunner(broker, "test-eval").run(tmp_path)
        assert (check.status, check.exit_code, check.probe_ok) == ("FAILED", 1, True)
        assert derive_verdict(check).status == FAILED

    def test_the_check_carries_the_full_invocation_not_just_the_target(self, tmp_path: Path) -> None:
        """R-VP-3. `check.target` is the bare Make target; `check.command` (and
        therefore `Verdict.command`) must be what was actually run, or the
        `-f Makefile` pin that defeats the GNUmakefile shadow attack is present
        in the runner and lost by the time a reader sees it.
        """
        broker = RecordingBroker({"-n": _ok()})
        runner = VerificationRunner(broker, "test-eval")
        check = runner.run(tmp_path)
        assert check.command == runner.command == "make -f Makefile test-python"
        assert derive_verdict(check).command == "make -f Makefile test-python"

    def test_a_blocked_probe_also_carries_the_full_invocation(self, tmp_path: Path) -> None:
        """The same field, on the short-circuit path a passing run never takes."""
        broker = RecordingBroker({"-n": ExecutionResult("FAILED", "", "No rule to make target", 2)})
        check = VerificationRunner(broker, "test-eval").run(tmp_path)
        assert check.command == "make -f Makefile test-python"

    def test_a_failed_probe_short_circuits_the_run(self, tmp_path: Path) -> None:
        broker = RecordingBroker({"-n": ExecutionResult("FAILED", "", "", 2)})
        check = VerificationRunner(broker, "test-eval").run(tmp_path)
        assert check.probe_ok is False
        assert not any(c.endswith("test-python") and "-n" not in c for c in broker.commands)

    def test_the_sentinel_is_set_while_running_and_restored_after(self, tmp_path: Path) -> None:
        """AC-5 / R-VP-6. The check runs the suite that contains this module, and
        production runs it against the repository root."""
        seen: list[str | None] = []

        class SentinelWatchingBroker(RecordingBroker):
            def execute_command(self, command: str, _ctx: dict, cwd=None, timeout: int = 0):
                import os

                if "-n" not in command:
                    seen.append(os.environ.get(REENTRANCY_ENV))
                return super().execute_command(command, _ctx, cwd, timeout)

        runner = VerificationRunner(SentinelWatchingBroker(), "test-eval")
        runner.run(tmp_path)
        assert seen and seen[-1] == "1"
        import os

        assert REENTRANCY_ENV not in os.environ

    def test_reentrancy_is_detected_from_the_environment(self) -> None:
        runner = VerificationRunner(RecordingBroker(), "test-eval")
        assert runner.is_reentrant({REENTRANCY_ENV: "1"}) is True
        assert runner.is_reentrant({}) is False

    def test_a_runner_with_no_target_reports_none(self) -> None:
        assert VerificationRunner(RecordingBroker(), "test-eval", target=None).target is None


class TestTheLoopReportsIt:
    """The unit tests above are worthless if `execute_loop` does not consult them."""

    @staticmethod
    def _orch(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, exit_code: int):
        import harness.shared.mango_mas_orchestrator as orch_module
        from harness.shared.mango_mas_orchestrator import MangoMASOrchestrator
        from harness.shared.tests._helpers import chat_response

        agents = tmp_path / ".mango" / "agents"
        agents.mkdir(parents=True)
        for role in ("planner", "nemotron-reasoner", "verifier"):
            (agents / f"{role}.md").write_text(f"# {role}\n", encoding="utf-8")

        # The verifier's prose says PASS in both cases. If it reached the verdict,
        # both runs would agree -- which is the defect.
        monkeypatch.setattr(orch_module, "complete_chat", lambda **_kw: chat_response(content="VERIFY: PASS"))
        status = "SUCCESS" if exit_code == 0 else "FAILED"
        broker = RecordingBroker({"-n": _ok(), "-f Makefile": ExecutionResult(status, "", "", exit_code)})
        runner = VerificationRunner(broker, "test-eval")
        return MangoMASOrchestrator(workspace_dir=tmp_path, tool_timeout=5, verification=runner)

    def test_a_failing_check_and_a_passing_check_differ(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """AC-10 / SC-1. The two runs differ in a field no model wrote.

        Before this change a FAIL and a PASS were byte-identical to every
        consumer: the loop returned prose and the API hardcoded success.
        """
        passing = self._orch(tmp_path / "a", monkeypatch, exit_code=0).execute_loop("t")
        failing = self._orch(tmp_path / "b", monkeypatch, exit_code=1).execute_loop("t")

        assert passing.verdict.status == VERIFIED
        assert failing.verdict.status == FAILED
        assert passing.verdict.status != failing.verdict.status
        # ...while the model's own words are identical in both.
        assert passing.verifier_message == failing.verifier_message == "VERIFY: PASS"

    def test_the_frozen_method_still_returns_the_verifier_message(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """AC-9 / R-VP-11. R-ORCH-4 keeps this byte-compatible for callers."""
        orch = self._orch(tmp_path, monkeypatch, exit_code=1)
        assert orch.execute_sequential_thinking_loop("t") == "VERIFY: PASS"

    def test_an_unconfigured_runner_blocks_without_calling_the_broker(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """AC-3. The broker must not be reached at all."""
        orch = self._orch(tmp_path, monkeypatch, exit_code=0)
        broker = RecordingBroker()
        orch._verification = VerificationRunner(broker, "test-eval", target=None)
        outcome = orch.execute_loop("t")
        assert outcome.verdict.termination_reason == NOT_CONFIGURED
        assert broker.commands == []

    def test_a_reentrant_run_blocks_without_calling_the_broker(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """AC-5."""
        orch = self._orch(tmp_path, monkeypatch, exit_code=0)
        broker = RecordingBroker()
        orch._verification = VerificationRunner(broker, "test-eval")
        monkeypatch.setenv(REENTRANCY_ENV, "1")
        outcome = orch.execute_loop("t")
        assert outcome.verdict.termination_reason == REENTRANT
        assert broker.commands == []
