"""Hook execution runner for the Mango MAS orchestrator."""

from __future__ import annotations

import logging
import os
import subprocess
from pathlib import Path
from typing import Any

from harness.shared.agent_prompts import PERMITTED_HOOK_NAMES
from harness.shared.debug_dump import credential_env_names

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
        self.tool_timeout = tool_timeout

    def run_hook(self, hook_name: str, **kwargs: Any) -> None:
        """Executes a pre- or post- hook script if it exists."""
        if hook_name not in PERMITTED_HOOK_NAMES:
            raise ValueError(
                f"refusing to run unrecognised hook {hook_name!r}; "
                f"permitted names are {sorted(PERMITTED_HOOK_NAMES)}"
            )
        hook_path = self.hooks_dir / f"{hook_name}.sh"
        if hook_path.exists():
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
                subprocess.run(
                    ["bash", hook_arg], cwd=self.workspace_dir, env=env, check=True, timeout=self.tool_timeout
                )
            except Exception:
                logger.exception("Hook %s failed", hook_name)
                raise
