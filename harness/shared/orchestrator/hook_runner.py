"""Hook execution runner for the Mango MAS orchestrator."""

from __future__ import annotations

import logging
import os
import subprocess
from pathlib import Path
from typing import Any

from harness.shared.agent_prompts import PERMITTED_HOOK_NAMES
from harness.shared.debug_dump import credential_env_names
from harness.shared.policy_loader import orchestrator_defaults

logger = logging.getLogger(__name__)


class HookRunner:
    """Runs pre and post execution hooks."""

    def __init__(
        self,
        workspace_dir: Path,
        hooks_dir: Path,
        tool_timeout: int | None = None,
    ) -> None:
        self.workspace_dir = workspace_dir
        self.hooks_dir = hooks_dir
        # `None` used to be stored and handed to `subprocess.run(timeout=...)`,
        # where it means *no timeout at all*: a hook script that never returns
        # hung the agent loop with nothing to interrupt it, and through
        # `run_in_threadpool` it hung an API worker with it. The facade resolved
        # the value from policy before constructing this, so the unbounded path
        # was reachable only by constructing a `HookRunner` directly -- which is
        # exactly the shape `write_policy` documents as "a helper that only holds
        # when its caller already checked". Resolved here instead, from
        # `orchestrator.tool_timeout_sec`, so there is no unbounded construction
        # (code-quality-tech-debt-plan R-CQ-7).
        self.tool_timeout: int = (
            tool_timeout if tool_timeout is not None else orchestrator_defaults()["tool_timeout_sec"]
        )

    def run_hook(self, hook_name: str, **kwargs: Any) -> None:
        """Executes a pre- or post- hook script if it exists."""
        if hook_name not in PERMITTED_HOOK_NAMES:
            raise ValueError(
                f"refusing to run unrecognised hook {hook_name!r}; permitted names are {sorted(PERMITTED_HOOK_NAMES)}"
            )
        hook_path = self.hooks_dir / f"{hook_name}.sh"
        if not hook_path.exists():
            # Presence remains the enablement switch; DEBUG makes a missing
            # permitted script visible in CI logs without changing the no-op.
            logger.debug("permitted hook %s missing on disk at %s; skipping", hook_name, hook_path)
            return
        logger.info("Executing hook: %s", hook_name)
        try:
            denied = set(credential_env_names())
            env = {k: v for k, v in os.environ.items() if k not in denied}
            for k, v in kwargs.items():
                env[f"MANGO_HOOK_{k.upper()}"] = str(v)
            try:
                hook_arg = hook_path.relative_to(self.workspace_dir).as_posix()
            except ValueError:
                hook_arg = hook_path.as_posix()
            subprocess.run(["bash", hook_arg], cwd=self.workspace_dir, env=env, check=True, timeout=self.tool_timeout)
        except Exception:
            logger.exception("Hook %s failed", hook_name)
            raise
