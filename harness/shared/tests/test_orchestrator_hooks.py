"""Tests for MangoMASOrchestrator lifecycle hook execution, credential containment, and security."""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

import pytest

from harness.shared import mango_mas_orchestrator as orch_module
from harness.shared.agent_authority import ACTIVE_TO_CANONICAL
from harness.shared.mango_mas_orchestrator import (
    PERMITTED_HOOK_NAMES,
    PRE_RUN_HOOK,
    MangoMASOrchestrator,
)
from harness.shared.orchestrator.hook_runner import HookRunner
from harness.shared.tests._orchestrator_helpers import _POSIX, _resp


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
        source = Path(orch_module.__file__).read_text(encoding="utf-8")
        literal = set(re.findall(r'_run_hook\(\s*"([a-z0-9-]+)"', source))
        interpolated = {
            template.replace("{agent_name}", role)
            for template in re.findall(r'_run_hook\(\s*f"([^"]+)"', source)
            for role in ACTIVE_TO_CANONICAL
        }
        constructed = literal | interpolated | {PRE_RUN_HOOK}
        assert constructed, "found no _run_hook call sites; this parser needs updating"
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
