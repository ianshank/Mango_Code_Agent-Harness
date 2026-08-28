"""Fixtures local to the regression tier.

The parent ``harness/shared/tests/conftest.py`` still applies (pytest walks
the whole conftest chain), so the hermetic-environment autouse fixture is
inherited rather than repeated.
"""

from __future__ import annotations

from pathlib import Path

import pytest


@pytest.fixture
def agent_workspace(tmp_path: Path) -> Path:
    """A workspace with the ``.mango/agents`` prompts the orchestrator loads.

    Active roles only: `_run_hook` refuses a hook name the orchestrator could
    not have constructed, and `post-<fictional role>-run` is one of those.
    """
    agents = tmp_path / ".mango" / "agents"
    agents.mkdir(parents=True, exist_ok=True)
    for name in ("planner", "nemotron-reasoner", "verifier"):
        (agents / f"{name}.md").write_text(f"# {name}\nYou are the {name} agent.", encoding="utf-8")
    return tmp_path


@pytest.fixture
def no_ambient_credentials(monkeypatch: pytest.MonkeyPatch) -> None:
    """Remove provider credentials so redaction tests control every input."""
    for var in ("NVIDIA_API_KEY", "NEMOTRON_DEFAULT_MODEL", "NEMOTRON_MAX_RETRIES", "NEMOTRON_TIMEOUT_MS"):
        monkeypatch.delenv(var, raising=False)
