"""Regressions for the agent's file-write tool reaching the control surface.

Defects reproduced here (all present on ``main`` before this change):

1. ``_execute_write_file`` confined writes with ``is_relative_to(workspace)`` and
   nothing else. In the deployed path the workspace *is* the repository root
   (``harness/api_server/main.py`` passes ``workspace_dir=PROJECT_ROOT``), so
   "confined to the workspace" granted write access to the guard, the policy
   decision point, the orchestrator's own hooks, the agent personas, both
   policies, and ``.git/``.
2. ``protected_paths`` was consulted only by ``validate_invariants.py`` at CI
   time. Within a single agent task nothing checked it, and on a branch with no
   required checks the CI gate is advisory.
3. A write that escaped the workspace was refused but logged nothing, so the most
   interesting thing this tool can do left no trace.

The chain those compose into: the verifier role receives ``write_file``, writes
``.mango/hooks/post-verifier-run.sh``, and ``_run_hook`` executes it on the host
with the full environment at the end of that same turn.

The contract under test: **a write lands on disk only after the write policy has
allowed it.**

Spec: ``docs/specs/agent-containment.md`` (R-AC-6, R-AC-7).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from harness.shared import mango_mas_orchestrator as orch_module
from harness.shared.mango_mas_orchestrator import MangoMASOrchestrator

#: Each entry is a step in a published escalation path, not a category label.
ESCALATION_TARGETS = [
    (".mango/hooks/pre-nemotron-run.sh", "executed by _run_hook on the host at every agent turn"),
    (".mango/hooks/post-verifier-run.sh", "executed on the host at the end of the verifier's own turn"),
    ("harness/shared/pretooluse_guard.py", "the guard the orchestrator consults"),
    ("harness/control-plane/tool_broker_reference.py", "the policy decision point the broker executes"),
    ("harness/shared/governance-policy.json", "the policy that declares every limit the agent runs under"),
    ("harness/shared/agent-policy.json", "the authority model itself"),
    (".mango/agents/nemotron-reasoner.md", "the agent's own system prompt"),
    (".claude/settings.json", "registers shell that runs on every session"),
    (".git/config", "core.fsmonitor here runs on the host at the next index refresh"),
    (".git/hooks/pre-commit", "runs on the host at the next commit, and git never lists it"),
]


class TestWriteToolCannotReachTheControlSurface:
    @pytest.mark.parametrize(("relpath", "why_it_matters"), ESCALATION_TARGETS)
    def test_target_is_refused_and_nothing_lands_on_disk(
        self, agent_workspace: Path, relpath: str, why_it_matters: str
    ) -> None:
        """The workspace here is a temp directory, so a pre-fix run writes a real
        file into it rather than into the repository. The assertion is on the
        filesystem, not only on the returned string: a refusal message with the
        write already performed would be worse than no gate."""
        orch = MangoMASOrchestrator(workspace_dir=agent_workspace)

        result = orch._execute_write_file(relpath, "PAYLOAD")

        assert result.startswith("Error writing file"), f"{relpath} was writable: {why_it_matters}"
        # Asserted on content rather than existence: the workspace fixture
        # pre-creates the agent personas, so a non-existence assertion would pass
        # for the wrong reason on some targets and fail for the wrong reason on
        # others.
        target = agent_workspace / relpath
        landed = target.read_text(encoding="utf-8") if target.is_file() else ""
        assert "PAYLOAD" not in landed, f"{relpath} was written despite the refusal"

    def test_ordinary_generated_code_still_lands(self, agent_workspace: Path) -> None:
        """The control that keeps the gate honest. Denying everything would pass
        every assertion above while making the harness useless."""
        result = orch_write(agent_workspace, "src/feature.py", "print('hello')")
        assert result.startswith("Success")
        assert (agent_workspace / "src" / "feature.py").read_text(encoding="utf-8") == "print('hello')"

    def test_escape_attempt_is_refused_and_logged(
        self, agent_workspace: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Defect 3: the refusal existed, the record of it did not."""
        with caplog.at_level("WARNING"):
            result = orch_write(agent_workspace, "../../etc/evil.conf", "PAYLOAD")
        assert "path escapes workspace" in result
        assert any("outside the workspace" in r.message for r in caplog.records), "the escape attempt was not logged"


def orch_write(workspace: Path, relpath: str, content: str) -> str:
    return MangoMASOrchestrator(workspace_dir=workspace)._execute_write_file(relpath, content)


class TestVerifierDoesNotReceiveTheWriteTool:
    """Defect: ``execute_agent`` passed no ``tools=`` argument for the reasoner or
    the verifier, so both fell through to ``NEMOTRON_TOOLS`` -- the implementer
    schema. The role that judges the work could edit the work, and could write the
    hook that ``_run_hook`` executes on the host at the end of its own turn.

    Asserted at the orchestrator boundary rather than on the helper, because the
    defect was the *default*, not the derivation.
    """

    def _tools_offered(self, workspace: Path, role: str, mocker) -> set[str]:
        chat = mocker.patch.object(orch_module, "complete_chat")
        chat.return_value = {"choices": [{"message": {"content": "done", "tool_calls": []}}]}
        MangoMASOrchestrator(workspace_dir=workspace).execute_agent(role, "task")
        return {t["function"]["name"] for t in chat.call_args.kwargs["tools"]}

    def test_verifier_is_not_offered_write_file(self, agent_workspace: Path, mocker) -> None:
        assert "write_file" not in self._tools_offered(agent_workspace, "verifier", mocker)

    def test_verifier_is_still_offered_run_command(self, agent_workspace: Path, mocker) -> None:
        assert "run_command" in self._tools_offered(agent_workspace, "verifier", mocker)

    def test_reasoner_keeps_the_implementer_surface(self, agent_workspace: Path, mocker) -> None:
        assert {"write_file", "run_command"} <= self._tools_offered(agent_workspace, "nemotron-reasoner", mocker)
