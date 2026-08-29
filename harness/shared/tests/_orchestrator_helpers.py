"""Shared fixtures and mock utilities for Mango MAS orchestrator test suites."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import pytest

from harness.shared import mango_mas_orchestrator as orch_module

# Bash hook tests require a POSIX shell; skip on Windows where `bash` cannot
# interpret Windows absolute paths without WSL.
_POSIX = sys.platform != "win32"


def _mk_agent_dirs(workspace: Path, names: list[str]) -> None:
    """Create ``.mango/agents/<name>.md`` prompt files inside *workspace*."""
    agents = workspace / ".mango" / "agents"
    agents.mkdir(parents=True, exist_ok=True)
    for name in names:
        (agents / f"{name}.md").write_text(f"# {name}\nYou are the {name} agent.", encoding="utf-8")


@pytest.fixture
def mock_workspace(tmp_path: Path) -> Path:
    """A temp workspace pre-populated with the agents the MAS loop expects."""
    _mk_agent_dirs(tmp_path, ["planner", "nemotron-reasoner", "verifier"])
    return tmp_path


def _resp(content: str | None = None, tool_calls: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    """Build an OpenAI-style chat completion response for the mocked bridge."""
    message: dict[str, Any] = {"role": "assistant", "content": content}
    if tool_calls:
        message["tool_calls"] = tool_calls
    return {"choices": [{"message": message}]}


def _tool_call(
    name: str,
    arguments: dict[str, Any] | str | None = None,
    call_id: str = "call_1",
) -> dict[str, Any]:
    """Build a single ``tool_calls`` entry."""
    if arguments is None:
        args_str = "{}"
    elif isinstance(arguments, str):
        args_str = arguments
    else:
        args_str = json.dumps(arguments)
    return {
        "id": call_id,
        "function": {"name": name, "arguments": args_str},
    }


@pytest.fixture
def mock_complete_chat(mocker):
    """Patch the Nemotron bridge inside the orchestrator; return the mock."""
    return mocker.patch.object(orch_module, "complete_chat")


__all__ = [
    "_POSIX",
    "_mk_agent_dirs",
    "_resp",
    "_tool_call",
    "mock_complete_chat",
    "mock_workspace",
]
