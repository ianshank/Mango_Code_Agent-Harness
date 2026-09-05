"""Tests for MangoMASOrchestrator lifecycle hook execution, credential containment, and security."""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

import pytest

from harness.shared.agent_authority import ACTIVE_TO_CANONICAL
from harness.shared.mango_mas_orchestrator import (
    PERMITTED_HOOK_NAMES,
    PRE_RUN_HOOK,
    MangoMASOrchestrator,
)
from harness.shared.orchestrator.hook_runner import HookRunner
from harness.shared.tests._orchestrator_helpers import _POSIX, _resp, _tool_call


class TestRunHook:
    def test_hook_missing_is_noop(self, mock_workspace: Path) -> None:
        orch = MangoMASOrchestrator(workspace_dir=mock_workspace)
        # No hook script present -> executes without raising and does nothing.
        orch.hook_runner.run_hook("pre-nemotron-run", task="t", agent="a")
        assert not (mock_workspace / ".mango" / "hooks" / "pre-nemotron-run.sh").exists()

    def test_hook_mocked_execution(self, mock_workspace: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        hooks = mock_workspace / ".mango" / "hooks"
        hooks.mkdir(parents=True, exist_ok=True)
        (hooks / "pre-nemotron-run.sh").write_text("echo ran\n", encoding="utf-8")
        orch = MangoMASOrchestrator(workspace_dir=mock_workspace)
        executed_cmds = []

        def mock_run(cmd, **kwargs):
            executed_cmds.append(cmd)
            return subprocess.CompletedProcess(args=cmd, returncode=0, stdout="done")

        monkeypatch.setattr(subprocess, "run", mock_run)
        orch.hook_runner.run_hook("pre-nemotron-run", task="test-task", agent="nemotron-reasoner")
        assert len(executed_cmds) == 1

    def test_hook_mocked_called_process_error(self, mock_workspace: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        hooks = mock_workspace / ".mango" / "hooks"
        hooks.mkdir(parents=True, exist_ok=True)
        (hooks / "pre-nemotron-run.sh").write_text("exit 1\n", encoding="utf-8")
        orch = MangoMASOrchestrator(workspace_dir=mock_workspace)

        def mock_run(cmd, **kwargs):
            raise subprocess.CalledProcessError(returncode=1, cmd=cmd)

        monkeypatch.setattr(subprocess, "run", mock_run)
        with pytest.raises(subprocess.CalledProcessError):
            orch.hook_runner.run_hook("pre-nemotron-run", task="test-task", agent="nemotron-reasoner")

    def test_hook_mocked_timeout_expired(self, mock_workspace: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        hooks = mock_workspace / ".mango" / "hooks"
        hooks.mkdir(parents=True, exist_ok=True)
        (hooks / "pre-nemotron-run.sh").write_text("sleep 100\n", encoding="utf-8")
        orch = MangoMASOrchestrator(workspace_dir=mock_workspace)

        def mock_run(cmd, **kwargs):
            raise subprocess.TimeoutExpired(cmd=cmd, timeout=5)

        monkeypatch.setattr(subprocess, "run", mock_run)
        with pytest.raises(subprocess.TimeoutExpired):
            orch.hook_runner.run_hook("pre-nemotron-run", task="test-task", agent="nemotron-reasoner")

    def test_invalid_hook_name_raises(self, mock_workspace: Path) -> None:
        orch = MangoMASOrchestrator(workspace_dir=mock_workspace)
        with pytest.raises(ValueError, match="refusing to run unrecognised hook"):
            orch.hook_runner.run_hook("malicious-hook-name", task="t", agent="a")

    def test_hook_exists_and_runs(self, mock_workspace: Path) -> None:
        if not _POSIX:
            pytest.skip("bash hook tests require POSIX platform (DEC-026)")
        hooks = mock_workspace / ".mango" / "hooks"
        hooks.mkdir(parents=True, exist_ok=True)
        (hooks / "pre-nemotron-run.sh").write_text("echo ran > hook_marker.txt\n", encoding="utf-8")
        orch = MangoMASOrchestrator(workspace_dir=mock_workspace)
        orch.hook_runner.run_hook("pre-nemotron-run", task="t", agent="a")
        assert (mock_workspace / "hook_marker.txt").exists()

    def test_hook_raises_propagates(self, mock_workspace: Path) -> None:
        if not _POSIX:
            pytest.skip("bash hook tests require POSIX platform (DEC-026)")
        hooks = mock_workspace / ".mango" / "hooks"
        hooks.mkdir(parents=True, exist_ok=True)
        (hooks / "pre-nemotron-run.sh").write_text("exit 1\n", encoding="utf-8")
        orch = MangoMASOrchestrator(workspace_dir=mock_workspace, tool_timeout=5)
        with pytest.raises(subprocess.CalledProcessError):
            orch.hook_runner.run_hook("pre-nemotron-run", task="t", agent="a")


@pytest.mark.skipif(not _POSIX, reason="bash hooks not available on Windows (DEC-026)")
class TestHookEnvironmentIsStrippedOfCredentials:
    """`agent-policy.json` declares `secrets_may_not_be_propagated_to_subagents`
    and nothing enforced it: `_run_hook` handed every hook `os.environ.copy()`."""

    def _hook(self, workspace: Path) -> Path:
        hooks = workspace / ".mango" / "hooks"
        hooks.mkdir(parents=True, exist_ok=True)
        marker = workspace / "env-marker.txt"
        (hooks / "pre-nemotron-run.sh").write_text(
            f'printf "%s|%s|%s" "${{NVIDIA_API_KEY:-}}" "${{AGENT_EVIDENCE_KEY:-}}" "${{PATH:+set}}" > {marker}\n',
            encoding="utf-8",
        )
        return marker

    def test_credentials_do_not_reach_a_hook(
        self, mock_workspace: Path, monkeypatch: pytest.MonkeyPatch, mock_complete_chat
    ) -> None:
        marker = self._hook(mock_workspace)
        monkeypatch.setenv("NVIDIA_API_KEY", "nvapi-should-not-appear")
        monkeypatch.setenv("AGENT_EVIDENCE_KEY", "evidence-should-not-appear")
        mock_complete_chat.return_value = _resp("done")

        MangoMASOrchestrator(workspace_dir=mock_workspace, tool_timeout=10).execute_agent("planner", "task")

        api_key, evidence, path_set = marker.read_text(encoding="utf-8").split("|")
        assert api_key == "", "NVIDIA_API_KEY reached the hook"
        assert evidence == "", "AGENT_EVIDENCE_KEY reached the hook"
        assert path_set == "set", "the filter stripped the whole environment, not just credentials"

    def test_hook_arguments_still_reach_the_hook(
        self, mock_workspace: Path, monkeypatch: pytest.MonkeyPatch, mock_complete_chat
    ) -> None:
        """The control: filtering must not break the hook contract itself."""
        hooks = mock_workspace / ".mango" / "hooks"
        hooks.mkdir(parents=True, exist_ok=True)
        marker = mock_workspace / "agent-marker.txt"
        (hooks / "pre-nemotron-run.sh").write_text(
            f'printf "%s" "${{MANGO_HOOK_AGENT:-missing}}" > {marker}\n', encoding="utf-8"
        )
        mock_complete_chat.return_value = _resp("done")
        MangoMASOrchestrator(workspace_dir=mock_workspace, tool_timeout=10).execute_agent("planner", "task")
        assert marker.read_text(encoding="utf-8") == "planner"


class TestOnlyKnownHooksExecute:
    """`hooks_dir` sits inside the workspace, and in the deployed configuration
    the workspace *is* the repository -- so "execute whatever `.sh` matches this
    name" is a host-execution primitive."""

    def test_an_unrecognised_hook_name_is_refused(self, mock_workspace: Path) -> None:
        orch = MangoMASOrchestrator(workspace_dir=mock_workspace)
        with pytest.raises(ValueError, match="unrecognised hook"):
            orch.hook_runner.run_hook("post-../../../etc/evil-run")

    def test_a_planted_hook_with_an_unlisted_name_does_not_execute(self, mock_workspace: Path) -> None:
        if not _POSIX:
            pytest.skip("bash hook tests require POSIX platform (DEC-026)")
        hooks = mock_workspace / ".mango" / "hooks"
        hooks.mkdir(parents=True, exist_ok=True)
        (hooks / "post-attacker-run.sh").write_text("echo pwned > planted_marker.txt\n", encoding="utf-8")
        orch = MangoMASOrchestrator(workspace_dir=mock_workspace)
        with pytest.raises(ValueError):
            orch.hook_runner.run_hook("post-attacker-run")
        assert not (mock_workspace / "planted_marker.txt").exists(), (
            "an unlisted hook executed; the allowlist is not reached before the spawn"
        )

    @pytest.mark.parametrize("name", sorted(PERMITTED_HOOK_NAMES))
    def test_every_permitted_hook_still_runs(self, name: str, mock_workspace: Path) -> None:
        if not _POSIX:
            pytest.skip("bash hook tests require POSIX platform (DEC-026)")
        hooks = mock_workspace / ".mango" / "hooks"
        hooks.mkdir(parents=True, exist_ok=True)
        (hooks / f"{name}.sh").write_text(f"echo ran > {name}_marker.txt\n", encoding="utf-8")
        orch = MangoMASOrchestrator(workspace_dir=mock_workspace)
        orch.hook_runner.run_hook(name)
        assert (mock_workspace / f"{name}_marker.txt").exists()

    def test_the_allowlist_covers_every_name_the_orchestrator_constructs(self) -> None:
        """Call sites live on ExecutionLoop (R-TDH-18); parse loop.py, not the facade."""
        import harness.shared.orchestrator.loop as loop_module

        source = Path(loop_module.__file__).read_text(encoding="utf-8")
        literal = set(re.findall(r'\.run_hook\(\s*"([a-z0-9-]+)"', source))
        interpolated = {
            template.replace("{agent_name}", role)
            for template in re.findall(r'\.run_hook\(\s*f"([^"]+)"', source)
            for role in ACTIVE_TO_CANONICAL
        }
        constructed = set(literal) | interpolated
        if re.search(r"\.run_hook\(\s*PRE_RUN_HOOK\b", source):
            constructed.add(PRE_RUN_HOOK)
        assert constructed, "found no run_hook call sites in loop.py; this parser needs updating"
        post_names = {f"post-{role}-run" for role in ACTIVE_TO_CANONICAL}
        assert post_names <= constructed, (
            f"loop.py no longer constructs every post-*-run name: "
            f"{sorted(post_names - constructed)}. Removing a post-run call site "
            "silently drops the NS-21 observation point."
        )
        assert constructed <= PERMITTED_HOOK_NAMES, (
            f"the orchestrator constructs hook names the allowlist refuses: "
            f"{sorted(constructed - PERMITTED_HOOK_NAMES)}"
        )


class TestHookPathRelativeToWorkspace:
    """hook_runner.py lines 45-48: the hook is handed to bash as a workspace-relative
    path when it lives inside the workspace, and as its absolute path when
    ``hooks_dir`` is elsewhere (an installed harness supplying hooks for a separate
    checkout). ``Path.relative_to`` raises ValueError in the second case; without
    the fallback every such deployment would fail before the hook ran."""

    def _spawn_recorder(self, monkeypatch: pytest.MonkeyPatch) -> list[tuple[list[str], dict]]:
        seen: list[tuple[list[str], dict]] = []

        def record(cmd, **kwargs):
            seen.append((cmd, kwargs))
            return subprocess.CompletedProcess(args=cmd, returncode=0)

        monkeypatch.setattr(subprocess, "run", record)
        return seen

    def test_a_hook_outside_the_workspace_is_invoked_by_absolute_path(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        workspace = tmp_path / "workspace"
        workspace.mkdir()
        hooks = tmp_path / "installed-hooks"
        hooks.mkdir()
        hook = hooks / "pre-nemotron-run.sh"
        hook.write_text("echo ran\n", encoding="utf-8")
        seen = self._spawn_recorder(monkeypatch)

        HookRunner(workspace_dir=workspace, hooks_dir=hooks, tool_timeout=5).run_hook("pre-nemotron-run", task="t")

        ((cmd, kwargs),) = seen
        assert cmd == ["bash", hook.as_posix()]
        assert Path(cmd[1]).is_absolute()
        assert kwargs["cwd"] == workspace, "the hook still runs with the workspace as its cwd"

    def test_a_hook_inside_the_workspace_is_invoked_by_relative_path(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The control: the relative form is what the fallback is falling back from."""
        hooks = tmp_path / ".mango" / "hooks"
        hooks.mkdir(parents=True)
        (hooks / "pre-nemotron-run.sh").write_text("echo ran\n", encoding="utf-8")
        seen = self._spawn_recorder(monkeypatch)

        HookRunner(workspace_dir=tmp_path, hooks_dir=hooks, tool_timeout=5).run_hook("pre-nemotron-run", task="t")

        ((cmd, _),) = seen
        assert cmd == ["bash", ".mango/hooks/pre-nemotron-run.sh"]


class TestHookExecutionIsAlwaysBounded:
    """A hook runs agent-adjacent shell on the host, and it must not run forever.

    `tool_timeout` defaulted to `None` and was stored as given, then handed to
    `subprocess.run(timeout=...)`, where `None` means *no timeout at all*. The
    facade resolved the value from policy before constructing a `HookRunner`, so
    the unbounded path was reachable only by constructing one directly -- the
    shape `write_policy` names as "a helper that only holds when its caller
    already checked". A hook that never returns hung the agent loop, and through
    `run_in_threadpool` an API worker with it (code-quality-tech-debt-plan
    R-CQ-7).
    """

    def _spawn_recorder(self, monkeypatch: pytest.MonkeyPatch) -> list[dict]:
        seen: list[dict] = []

        def record(cmd, **kwargs):
            seen.append(kwargs)
            return subprocess.CompletedProcess(args=cmd, returncode=0)

        monkeypatch.setattr(subprocess, "run", record)
        return seen

    def test_a_runner_built_with_no_timeout_resolves_one_from_policy(self, tmp_path: Path) -> None:
        from harness.shared.policy_loader import orchestrator_defaults

        runner = HookRunner(workspace_dir=tmp_path, hooks_dir=tmp_path)
        assert runner.tool_timeout is not None
        assert runner.tool_timeout == orchestrator_defaults()["tool_timeout_sec"]

    def test_the_resolved_timeout_reaches_the_subprocess(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """The attribute is not the control; what `subprocess.run` receives is."""
        hooks = tmp_path / ".mango" / "hooks"
        hooks.mkdir(parents=True)
        (hooks / "pre-nemotron-run.sh").write_text("echo ran\n", encoding="utf-8")
        seen = self._spawn_recorder(monkeypatch)

        HookRunner(workspace_dir=tmp_path, hooks_dir=hooks).run_hook("pre-nemotron-run", task="t")

        (kwargs,) = seen
        assert kwargs["timeout"] is not None, "the hook ran with no timeout at all"
        assert kwargs["timeout"] > 0

    def test_an_explicit_timeout_still_wins(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Control: resolving a default must not override a caller that chose one."""
        hooks = tmp_path / ".mango" / "hooks"
        hooks.mkdir(parents=True)
        (hooks / "pre-nemotron-run.sh").write_text("echo ran\n", encoding="utf-8")
        seen = self._spawn_recorder(monkeypatch)

        HookRunner(workspace_dir=tmp_path, hooks_dir=hooks, tool_timeout=7).run_hook("pre-nemotron-run", task="t")

        (kwargs,) = seen
        assert kwargs["timeout"] == 7

    def test_the_timeout_follows_the_policy_rather_than_a_literal(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A literal default would pass every assertion above while ignoring the
        policy key it claims to read."""
        import harness.shared.orchestrator.hook_runner as hook_module

        monkeypatch.setattr(hook_module, "orchestrator_defaults", lambda: {"tool_timeout_sec": 41})
        assert HookRunner(workspace_dir=tmp_path, hooks_dir=tmp_path).tool_timeout == 41


class TestPermittedHookMissingLogsDebug:
    """A permitted name with no script on disk stays a no-op, but logs at DEBUG."""

    def test_missing_permitted_hook_logs_debug(self, mock_workspace: Path, caplog: pytest.LogCaptureFixture) -> None:
        import logging

        orch = MangoMASOrchestrator(workspace_dir=mock_workspace)
        with caplog.at_level(logging.DEBUG, logger="harness.shared.orchestrator.hook_runner"):
            orch.hook_runner.run_hook("post-planner-run", status="success")
        assert any(
            "missing on disk" in rec.getMessage() and "post-planner-run" in rec.getMessage() for rec in caplog.records
        ), "expected DEBUG when a permitted post-run script is absent"

    def test_directory_named_like_hook_is_skipped_not_executed(self, mock_workspace, caplog):
        """A directory at the hook path must not be treated as an executable script."""
        import logging

        from harness.shared.agent_prompts import PRE_RUN_HOOK
        from harness.shared.orchestrator.hook_runner import HookRunner

        hooks = mock_workspace / ".mango" / "hooks"
        hooks.mkdir(parents=True, exist_ok=True)
        decoy = hooks / f"{PRE_RUN_HOOK}.sh"
        decoy.mkdir()  # directory, not a file
        runner = HookRunner(workspace_dir=mock_workspace, hooks_dir=hooks, tool_timeout=5)
        with caplog.at_level(logging.DEBUG):
            runner.run_hook(PRE_RUN_HOOK, status="success")
        assert "not a file" in caplog.text or "skipping" in caplog.text
        # Must not have attempted to plant side effects via bash on a directory
        assert not (mock_workspace / "planted_marker.txt").exists()


def _repo_hooks_dir() -> Path:
    # harness/shared/tests/this_file.py -> repo root
    return Path(__file__).resolve().parents[3] / ".mango" / "hooks"


def _install_repo_post_run_hooks(workspace: Path) -> None:
    """Copy the tracked post-run entrypoints + shared recorder into a temp workspace."""
    import shutil

    src = _repo_hooks_dir()
    dest = workspace / ".mango" / "hooks"
    dest.mkdir(parents=True, exist_ok=True)
    (dest / "lib").mkdir(parents=True, exist_ok=True)
    for name in (
        "post-planner-run.sh",
        "post-nemotron-reasoner-run.sh",
        "post-verifier-run.sh",
    ):
        shutil.copy2(src / name, dest / name)
    shutil.copy2(src / "lib" / "record_post_run.sh", dest / "lib" / "record_post_run.sh")


def _read_post_run_records(workspace: Path) -> list[dict]:
    import json

    path = workspace / ".mango" / ".state" / "post-run.jsonl"
    assert path.is_file(), f"expected post-run JSONL at {path}"
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


@pytest.mark.skipif(not _POSIX, reason="bash hooks not available on Windows (DEC-026)")
class TestPostRunHookRecordContract:
    """NS-21: post-*-run scripts record turn status + tool-call spend, or tests fail."""

    def test_success_path_records_zero_tool_calls(self, mock_workspace: Path, mock_complete_chat) -> None:
        _install_repo_post_run_hooks(mock_workspace)
        mock_complete_chat.return_value = _resp("done")
        orch = MangoMASOrchestrator(workspace_dir=mock_workspace, tool_timeout=10)
        assert orch.execute_agent("planner", "task") == "done"
        records = _read_post_run_records(mock_workspace)
        assert len(records) == 1
        rec = records[0]
        assert rec["status"] == "success"
        assert rec["agent"] == "planner"
        assert rec["run_id"]
        assert rec["run_id"] == orch.run_id
        assert rec["tool_calls_used"] == 0
        assert rec["tool_calls_limit"] == orch.execution_loop.max_tool_calls_per_task

    def test_budget_exceeded_path_records_spend(self, mock_workspace: Path, mock_complete_chat) -> None:
        _install_repo_post_run_hooks(mock_workspace)
        tc = _tool_call("write_file", {"filepath": "loop.txt", "content": "x"})
        # Two calls in one round against a limit of 1: consume records the
        # overspend and the post-run hook still fires with budget_exceeded.
        mock_complete_chat.return_value = _resp(None, tool_calls=[tc, tc])
        orch = MangoMASOrchestrator(workspace_dir=mock_workspace, max_iterations=50, tool_timeout=10)
        orch.execution_loop.max_tool_calls_per_task = 1
        with pytest.raises(RuntimeError, match="tool-call budget"):
            orch.execute_agent("nemotron-reasoner", "budget")
        records = _read_post_run_records(mock_workspace)
        assert len(records) == 1
        rec = records[0]
        assert rec["status"] == "budget_exceeded"
        assert rec["agent"] == "nemotron-reasoner"
        assert rec["run_id"] == orch.run_id
        assert rec["tool_calls_used"] == 2
        assert rec["tool_calls_limit"] == 1

    def test_timeout_path_records_status(self, mock_workspace: Path, mock_complete_chat) -> None:
        _install_repo_post_run_hooks(mock_workspace)
        tc = _tool_call("write_file", {"filepath": "loop.txt", "content": "x"})
        mock_complete_chat.return_value = _resp(None, tool_calls=[tc])
        orch = MangoMASOrchestrator(workspace_dir=mock_workspace, max_iterations=2, tool_timeout=10)
        # Raise the budget so the timeout path wins before budget_exceeded.
        orch.execution_loop.max_tool_calls_per_task = 100
        with pytest.raises(RuntimeError, match="exceeded maximum tool iterations"):
            orch.execute_agent("verifier", "loop")
        records = _read_post_run_records(mock_workspace)
        assert len(records) == 1
        rec = records[0]
        assert rec["status"] == "timeout"
        assert rec["agent"] == "verifier"
        assert rec["run_id"] == orch.run_id
        assert rec["tool_calls_used"] == 2
        assert rec["tool_calls_limit"] == 100

    def test_removing_the_call_site_would_leave_no_record(
        self, mock_workspace: Path, mock_complete_chat, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Integration pin: if execute_agent stops firing post-run, this fails."""
        _install_repo_post_run_hooks(mock_workspace)
        mock_complete_chat.return_value = _resp("done")
        orch = MangoMASOrchestrator(workspace_dir=mock_workspace, tool_timeout=10)

        original = orch.hook_runner.run_hook

        def _silent_run_hook(name: str, **kwargs):
            if name.startswith("post-") and name.endswith("-run"):
                return None
            return original(name, **kwargs)

        monkeypatch.setattr(orch.hook_runner, "run_hook", _silent_run_hook)
        assert orch.execute_agent("planner", "task") == "done"
        path = mock_workspace / ".mango" / ".state" / "post-run.jsonl"
        assert not path.exists(), "post-run JSONL appeared without a post-run hook call; the negative pin is miswired"
