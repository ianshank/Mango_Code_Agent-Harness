"""A verdict is refused when the files it would be earned against have changed.

The 2026 standards audit (B4): ``-f Makefile`` pins *which* makefile the check
reads, and nothing pinned *what it said*. A script written with ``write_file``
and run with ``run_command`` rewrote it, and the next ``VerificationRunner.run``
returned ``VERIFIED`` on a failing suite. The runner now records the digest of
every protected file at loop start and refuses to grade if any changed.

Runner, vocabulary and loop are each pinned here with a recording broker; the
end-to-end reproduction through the real dispatcher, broker and process backend
is ``regression/test_verdict_forgery_regression.py``.
"""

from __future__ import annotations

import logging
from pathlib import Path

import pytest

from harness.shared.governance import enforcement_digest
from harness.shared.governance.broker import ExecutionResult
from harness.shared.governance.verdict import (
    BLOCKED,
    TAMPERED,
    UNAVAILABLE,
    VERIFIED,
    HarnessCheck,
    derive_verdict,
)
from harness.shared.governance.verification import REENTRANCY_ENV, VerificationRunner
from harness.shared.tests.test_verdict import RecordingBroker, _ok

pytestmark = pytest.mark.governance


@pytest.fixture(autouse=True)
def _make_on_path(monkeypatch: pytest.MonkeyPatch) -> None:
    from harness.shared.governance import verification as _verification_mod

    monkeypatch.setattr(_verification_mod.shutil, "which", lambda _name: "/usr/bin/make")
    monkeypatch.delenv(REENTRANCY_ENV, raising=False)


@pytest.fixture
def workspace(tmp_path: Path) -> Path:
    (tmp_path / "Makefile").write_text("test-python:\n\tpython -m pytest -q\n", encoding="utf-8")
    (tmp_path / "conftest.py").write_text("# root\n", encoding="utf-8")
    return tmp_path


def _runner(broker: RecordingBroker | None = None) -> VerificationRunner:
    return VerificationRunner(broker or RecordingBroker({"-n": _ok("python -m pytest -q\n")}), "test-eval")


class TestTheRunnerRefusesATamperedWorkspace:
    def test_a_rewritten_makefile_is_refused_before_the_probe(self, workspace: Path) -> None:
        broker = RecordingBroker({"-n": _ok("python -m pytest -q\n")})
        runner = _runner(broker)
        runner.snapshot_enforcement(workspace)

        (workspace / "Makefile").write_text("test-python:\n\ttrue\n", encoding="utf-8")
        check = runner.run(workspace)

        assert check.status == BLOCKED
        assert check.tampered_files == ("Makefile",)
        assert "Makefile" in check.reason
        assert broker.commands == [], "the probe ran against the forged makefile"

    def test_the_verdict_names_the_tampering(self, workspace: Path) -> None:
        runner = _runner()
        runner.snapshot_enforcement(workspace)
        (workspace / "Makefile").write_text("forged", encoding="utf-8")
        verdict = derive_verdict(runner.run(workspace))
        assert (verdict.status, verdict.termination_reason) == (BLOCKED, TAMPERED)
        assert "Makefile" in verdict.reason
        assert verdict.is_pass is False

    @pytest.mark.parametrize("appeared", ["GNUmakefile", "makefile", "pytest.ini", "tox.ini", "setup.cfg"])
    def test_a_protected_file_that_appears_is_tampering(self, workspace: Path, appeared: str) -> None:
        """Nothing at loop start, something at verification: a recipe input no
        review saw. This is what the armed dormant patterns are for."""
        runner = _runner()
        runner.snapshot_enforcement(workspace)
        (workspace / appeared).write_text("x", encoding="utf-8")
        check = runner.run(workspace)
        assert check.status == BLOCKED
        assert check.tampered_files == (appeared,)

    def test_a_protected_file_that_vanishes_is_tampering(self, workspace: Path) -> None:
        runner = _runner()
        runner.snapshot_enforcement(workspace)
        (workspace / "conftest.py").unlink()
        assert runner.run(workspace).tampered_files == ("conftest.py",)

    def test_a_byte_identical_restore_is_not_tampering(self, workspace: Path) -> None:
        """The comparison is on content, not on events: a forgery reverted to
        the exact bytes is the pristine tree, and the check runs."""
        broker = RecordingBroker({"-n": _ok("python -m pytest -q\n")})
        runner = _runner(broker)
        original = (workspace / "Makefile").read_bytes()
        runner.snapshot_enforcement(workspace)
        (workspace / "Makefile").write_text("forged", encoding="utf-8")
        (workspace / "Makefile").write_bytes(original)
        check = runner.run(workspace)
        assert check.tampered_files == ()
        assert check.status == "SUCCESS"
        assert derive_verdict(check).status == VERIFIED

    def test_an_untouched_workspace_runs_the_check(self, workspace: Path) -> None:
        """The control. Refusing everything would satisfy every test above."""
        broker = RecordingBroker({"-n": _ok("python -m pytest -q\n")})
        runner = _runner(broker)
        runner.snapshot_enforcement(workspace)
        check = runner.run(workspace)
        assert check.tampered_files == ()
        assert any(c == runner.command for c in broker.commands)
        assert derive_verdict(check).status == VERIFIED

    def test_the_baseline_is_exposed_as_a_copy(self, workspace: Path) -> None:
        runner = _runner()
        assert runner.baseline is None
        recorded = runner.snapshot_enforcement(workspace)
        assert runner.baseline == recorded
        recorded["Makefile"] = "mutated by the caller"
        assert runner.baseline != recorded, "the runner handed out its own dict"


class TestWithoutABaselineTheRunnerRecordsOneAndSaysSo:
    """Backward compatibility for direct callers, made visible rather than
    silent: a run with no baseline can only compare the tree to itself."""

    def test_a_run_with_no_baseline_warns_and_proceeds(
        self, workspace: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        runner = _runner()
        with caplog.at_level(logging.WARNING):
            check = runner.run(workspace)
        assert check.tampered_files == ()
        assert check.status == "SUCCESS"
        assert any("no enforcement baseline" in r.message for r in caplog.records)
        assert runner.baseline is not None, "the run did not record the baseline it warned about"

    def test_a_baseline_for_another_workspace_does_not_count(
        self, workspace: Path, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        other = tmp_path / "other"
        other.mkdir()
        (other / "Makefile").write_text("x:\n\ttrue\n", encoding="utf-8")
        runner = _runner()
        runner.snapshot_enforcement(other)
        with caplog.at_level(logging.WARNING):
            runner.run(workspace)
        assert any("no enforcement baseline" in r.message for r in caplog.records)

    def test_the_second_run_is_then_protected(self, workspace: Path) -> None:
        runner = _runner()
        runner.run(workspace)
        (workspace / "Makefile").write_text("forged", encoding="utf-8")
        assert runner.run(workspace).tampered_files == ("Makefile",)


class TestAnUnreadableEnforcementSetIsBlockedNotIgnored:
    def test_run_blocks_as_unavailable(
        self, workspace: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        broken = tmp_path / "broken.json"
        broken.write_text("{", encoding="utf-8")
        monkeypatch.setattr(enforcement_digest, "DEFAULT_POLICY_PATH", broken)
        broker = RecordingBroker()
        check = _runner(broker).run(workspace)
        assert check.status == BLOCKED
        assert check.probe_ok is False
        assert "enforcement set could not be established" in check.reason
        assert broker.commands == []
        assert derive_verdict(check).termination_reason == UNAVAILABLE

    def test_snapshot_raises_rather_than_recording_a_partial_baseline(
        self, workspace: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        broken = tmp_path / "broken.json"
        broken.write_text("{", encoding="utf-8")
        monkeypatch.setattr(enforcement_digest, "DEFAULT_POLICY_PATH", broken)
        runner = _runner()
        with pytest.raises(enforcement_digest.EnforcementDigestError):
            runner.snapshot_enforcement(workspace)
        assert runner.baseline is None


class TestTheVocabulary:
    def test_tampered_files_outrank_every_other_field(self) -> None:
        """A SUCCESS/exit-0 check with tampered files is still BLOCKED: the
        evidence is typed into the check, so no combination of the other
        fields can grade past it."""
        check = HarnessCheck(
            target="test-python", command="make -f Makefile test-python", status="SUCCESS",
            exit_code=0, reason="", probe_ok=True, latency_ms=1, tampered_files=("Makefile",),
        )
        verdict = derive_verdict(check)
        assert (verdict.status, verdict.termination_reason) == (BLOCKED, TAMPERED)
        assert "Makefile" in verdict.reason

    def test_tampering_outranks_a_failed_probe(self) -> None:
        check = HarnessCheck("t", "c", BLOCKED, -1, "", False, 1, ("Makefile",))
        assert derive_verdict(check).termination_reason == TAMPERED

    def test_the_seven_field_constructor_still_works(self) -> None:
        """Every existing constructor call omits the field; it defaults to empty."""
        check = HarnessCheck("t", "c", "SUCCESS", 0, "", True, 1)
        assert check.tampered_files == ()
        assert derive_verdict(check).status == VERIFIED

    def test_the_termination_reason_is_distinct(self) -> None:
        from harness.shared.governance import verdict

        reasons = {
            verdict.NOT_CONFIGURED, verdict.REENTRANT, verdict.UNAVAILABLE, verdict.HARNESS_FAULT,
            verdict.DENIED, verdict.FAILED_CHECK, verdict.UNRECOGNISED, verdict.TAMPERED,
        }
        assert len(reasons) == 8
        assert TAMPERED == "enforcement_tampered"


class TestTheLoopRecordsTheBaselineBeforeTheFirstAgentTurn:
    """The runner's check is only as good as when the baseline was taken: one
    recorded after the reasoner's turn records the forgery as the reference."""

    class SpyRunner(VerificationRunner):
        def __init__(self, events: list[str], **kwargs: object) -> None:
            super().__init__(RecordingBroker({"-n": _ok()}), "test-eval", **kwargs)  # type: ignore[arg-type]
            self.events = events

        def snapshot_enforcement(self, cwd: Path) -> dict[str, str]:
            self.events.append("snapshot")
            return super().snapshot_enforcement(cwd)

    @staticmethod
    def _orch(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, events: list[str], **runner_kwargs: object):
        import harness.shared.mango_mas_orchestrator as orch_module
        from harness.shared.mango_mas_orchestrator import MangoMASOrchestrator
        from harness.shared.tests._helpers import chat_response

        agents = tmp_path / ".mango" / "agents"
        agents.mkdir(parents=True)
        for role in ("planner", "nemotron-reasoner", "verifier"):
            (agents / f"{role}.md").write_text(f"# {role}\n", encoding="utf-8")

        def _chat(**_kw: object) -> dict:
            events.append("chat")
            return chat_response(content="done")

        monkeypatch.setattr(orch_module, "complete_chat", _chat)
        runner = TestTheLoopRecordsTheBaselineBeforeTheFirstAgentTurn.SpyRunner(events, **runner_kwargs)
        return MangoMASOrchestrator(workspace_dir=tmp_path, tool_timeout=5, verification=runner)

    def test_snapshot_precedes_every_model_call(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        events: list[str] = []
        outcome = self._orch(tmp_path, monkeypatch, events).execute_loop("t")
        assert events[0] == "snapshot"
        assert events.count("snapshot") == 1
        assert events.count("chat") == 3
        assert outcome.verdict.status == VERIFIED

    def test_no_snapshot_when_verification_is_not_configured(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        events: list[str] = []
        self._orch(tmp_path, monkeypatch, events, target=None).execute_loop("t")
        assert "snapshot" not in events

    def test_no_snapshot_when_reentrant(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        events: list[str] = []
        orch = self._orch(tmp_path, monkeypatch, events)
        monkeypatch.setenv(REENTRANCY_ENV, "1")
        orch.execute_loop("t")
        assert "snapshot" not in events

    def test_a_failed_snapshot_does_not_abort_the_agents_but_refuses_the_verdict(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
    ) -> None:
        events: list[str] = []
        orch = self._orch(tmp_path, monkeypatch, events)
        broken = tmp_path / "broken.json"
        broken.write_text("{", encoding="utf-8")
        monkeypatch.setattr(enforcement_digest, "DEFAULT_POLICY_PATH", broken)
        with caplog.at_level(logging.ERROR):
            outcome = orch.execute_loop("t")
        assert events.count("chat") == 3, "the agents' work was lost to a baseline fault"
        assert outcome.verdict.status == BLOCKED
        assert outcome.verdict.termination_reason == UNAVAILABLE
        assert any("baseline could not be recorded" in r.message for r in caplog.records)

    def test_a_loop_level_forgery_is_refused(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """The reasoner's turn rewrites the makefile (here: directly, in place of
        the tool calls the regression tier drives), and the verdict refuses."""
        from harness.shared.tests._helpers import chat_response

        events: list[str] = []
        orch = self._orch(tmp_path, monkeypatch, events)
        (tmp_path / "Makefile").write_text("test-python:\n\tfalse\n", encoding="utf-8")

        def _forging_chat(**_kw: object) -> dict:
            (tmp_path / "Makefile").write_text("test-python:\n\ttrue\n", encoding="utf-8")
            return chat_response(content="done")

        # The facade captured the module's `complete_chat` at construction, so
        # the loop's own attribute is what a later substitution has to target.
        orch.execution_loop.complete_chat_fn = _forging_chat
        outcome = orch.execute_loop("t")
        assert outcome.verdict.termination_reason == TAMPERED
        assert "Makefile" in outcome.verdict.reason

    def test_the_result_type_is_unchanged(self) -> None:
        result = ExecutionResult("SUCCESS", "", "", 0)
        assert result.action == ""


class TestTheBaselineFailureIsRemembered:
    """A snapshot that fails at loop start must not be replaced by a fresh
    baseline taken after the agents ran (Copilot review on PR #86)."""

    def test_a_failed_loop_start_snapshot_refuses_the_verdict(
        self, workspace: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from harness.shared.governance import verification as verification_mod

        real = verification_mod.enforcement_digests
        calls = {"n": 0}

        def _flaky(cwd: Path, policy_path: Path | None = None) -> dict[str, str]:
            calls["n"] += 1
            if calls["n"] == 1:
                raise enforcement_digest.EnforcementDigestError("protected file conftest.py could not be read")
            return real(cwd, policy_path)

        monkeypatch.setattr(verification_mod, "enforcement_digests", _flaky)
        runner = _runner()
        with pytest.raises(enforcement_digest.EnforcementDigestError):
            runner.snapshot_enforcement(workspace)

        check = runner.run(workspace)  # the tree is readable again; that must not help
        assert check.status == BLOCKED
        assert "could not be recorded at loop start" in check.reason
        assert check.probe_ok is False

    def test_a_later_successful_snapshot_clears_the_sentinel(
        self, workspace: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from harness.shared.governance import verification as verification_mod

        real = verification_mod.enforcement_digests
        monkeypatch.setattr(
            verification_mod, "enforcement_digests",
            lambda cwd, policy_path=None: (_ for _ in ()).throw(enforcement_digest.EnforcementDigestError("x")),
        )
        runner = _runner()
        with pytest.raises(enforcement_digest.EnforcementDigestError):
            runner.snapshot_enforcement(workspace)
        monkeypatch.setattr(verification_mod, "enforcement_digests", real)
        runner.snapshot_enforcement(workspace)
        assert runner.run(workspace).status != BLOCKED


class TestTamperingDuringTheRunIsCaught:
    def test_a_makefile_rewritten_while_make_runs_is_refused(self, workspace: Path) -> None:
        """A persistent rewrite between the pre-probe check and the recipe
        finishing is caught by the post-run re-check. A swap-and-restore inside
        that window is not; that needs OS isolation (plan Phase F)."""

        class RewritingBroker(RecordingBroker):
            def execute_command(self, command: str, _ctx: dict, cwd: Path | None = None, timeout: int = 0):
                if "test-python" in command and " -n " not in command and cwd is not None:
                    (cwd / "Makefile").write_text("test-python:\n\ttrue\n", encoding="utf-8")
                return super().execute_command(command, _ctx, cwd=cwd, timeout=timeout)

        runner = _runner(RewritingBroker({"-n": _ok("python -m pytest -q\n")}))
        runner.snapshot_enforcement(workspace)
        check = runner.run(workspace)
        assert check.status == BLOCKED
        assert "while the verdict was being earned" in check.reason
        assert "Makefile" in check.tampered_files
