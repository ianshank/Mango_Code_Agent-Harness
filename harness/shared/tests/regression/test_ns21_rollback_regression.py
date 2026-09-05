"""Regression tests that pin the NS-21 rollback state.

NS-21 (post-turn hooks recording turn outcome / spend to `.mango/.state/post-run.jsonl`)
was partially reverted on this branch:

- `lib/record_post_run.sh` **deleted**
- `post-planner-run.sh` **deleted**
- `post-nemotron-reasoner-run.sh` **deleted**
- `post-verifier-run.sh` **deleted**

The *invocation infrastructure* (`loop.py` calling `hook_runner.run_hook`,
`PERMITTED_HOOK_NAMES` deriving post-hook names, `HookRunner.run_hook`
no-oping when the script is absent) is intentionally **left intact** so that
re-enabling NS-21 only requires adding scripts back to `.mango/hooks/`.

These tests pin the observed state so that:

1. A reviewer can see exactly what was rolled back vs. what was retained.
2. If NS-21 is re-implemented, the changed assertions document the delta.
3. If the invocation code is accidentally removed, a test fails.

These tests do NOT require GNU Make or POSIX shell; they run on every platform.
"""

from __future__ import annotations

import inspect

import pytest

from harness.shared.tests._helpers import REPO

pytestmark = pytest.mark.governance

MANGO_HOOKS = REPO / ".mango" / "hooks"
HOOK_LIB = MANGO_HOOKS / "lib"


class TestNS21HookScriptsAreRolledBack:
    """The four NS-21 shell scripts are absent from disk (rollback complete)."""

    @pytest.mark.parametrize(
        "script_name",
        [
            "post-planner-run.sh",
            "post-nemotron-reasoner-run.sh",
            "post-verifier-run.sh",
        ],
    )
    def test_post_run_hook_scripts_do_not_exist(self, script_name: str) -> None:
        """NS-21 post-*-run scripts must not exist until NS-21 is re-implemented.

        Their presence on disk is the enablement switch. Absence keeps the
        observation point silent without removing the call site in loop.py.
        """
        script = MANGO_HOOKS / script_name
        assert not script.exists(), (
            f"{script.relative_to(REPO)} exists -- NS-21 post-run hook scripts "
            "were rolled back. If re-enabling NS-21, remove this guard and add "
            "JSONL-record contract tests at the same time."
        )

    def test_record_post_run_library_does_not_exist(self) -> None:
        """The shared recorder body `lib/record_post_run.sh` must not exist."""
        recorder = HOOK_LIB / "record_post_run.sh"
        assert not recorder.exists(), (
            f"{recorder.relative_to(REPO)} exists -- the NS-21 shared recorder "
            "was rolled back. Restore the JSONL-contract tests when re-enabling."
        )


class TestNS21InvocationInfrastructureIsRetained:
    """`loop.py` retains post-hook call sites so re-enabling only needs scripts."""

    def test_loop_fires_post_success_hook(self) -> None:
        from harness.shared.orchestrator import loop as loop_mod

        src = inspect.getsource(loop_mod.ExecutionLoop.execute_agent)
        assert "run_hook" in src and "success" in src, (
            "execute_agent no longer fires a post-*-run hook on success. "
            "Restore the call so re-enabling NS-21 only requires adding scripts."
        )

    def test_loop_fires_post_budget_exceeded_hook(self) -> None:
        from harness.shared.orchestrator import loop as loop_mod

        src = inspect.getsource(loop_mod.ExecutionLoop.execute_agent)
        assert "budget_exceeded" in src, "execute_agent no longer fires a post-*-run hook on budget_exceeded."

    def test_loop_fires_post_timeout_hook(self) -> None:
        from harness.shared.orchestrator import loop as loop_mod

        src = inspect.getsource(loop_mod.ExecutionLoop.execute_agent)
        assert "timeout" in src and "run_hook" in src, "execute_agent no longer fires a post-*-run hook on timeout."

    def test_hook_runner_does_not_hard_code_jsonl_path(self) -> None:
        """HookRunner must not hard-code the JSONL path -- that lives in the shell script."""
        from harness.shared.orchestrator import hook_runner as hr_mod

        src = inspect.getsource(hr_mod)
        assert "post-run.jsonl" not in src, "HookRunner hard-codes the JSONL path -- this belongs in the shell script."


class TestPermittedHookNamesIncludesPostRunNames:
    """PERMITTED_HOOK_NAMES includes post-*-run so HookRunner allows them when scripts return."""

    def test_post_run_names_derived_from_active_roles(self) -> None:
        from harness.shared.agent_authority import ACTIVE_TO_CANONICAL
        from harness.shared.agent_prompts import PERMITTED_HOOK_NAMES

        expected = {f"post-{role}-run" for role in ACTIVE_TO_CANONICAL}
        missing = expected - PERMITTED_HOOK_NAMES
        assert not missing, (
            f"Post-hook names missing from PERMITTED_HOOK_NAMES: {sorted(missing)}. "
            "PERMITTED_HOOK_NAMES must be derived from ACTIVE_TO_CANONICAL."
        )

    @pytest.mark.parametrize("name", ["post-planner-run", "post-nemotron-reasoner-run", "post-verifier-run"])
    def test_specific_post_run_name_permitted(self, name: str) -> None:
        from harness.shared.agent_prompts import PERMITTED_HOOK_NAMES

        assert name in PERMITTED_HOOK_NAMES, (
            f"{name} removed from PERMITTED_HOOK_NAMES -- HookRunner would silently "
            "skip the script even after NS-21 is re-enabled."
        )


class TestNoLivePostRunStateOnDisk:
    """While NS-21 is dormant, no JSONL records should accumulate."""

    def test_post_run_jsonl_is_empty_or_absent(self) -> None:
        state_file = REPO / ".mango" / ".state" / "post-run.jsonl"
        if state_file.exists():
            content = state_file.read_text(encoding="utf-8").strip()
            assert not content, (
                f"{state_file.relative_to(REPO)} contains JSONL records while NS-21 "
                "is rolled back. Either fully re-enable NS-21 with tests or delete the file."
            )
