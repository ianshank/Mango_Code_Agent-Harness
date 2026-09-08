"""Reasoner/bridge tool parity (R-RBT-1, R-RBT-2, R-RBT-3, R-RBT-4, R-RBT-5, C-RBT-3)."""

from __future__ import annotations

import hashlib
import logging
import re
from pathlib import Path

import pytest

from harness.shared.agent_authority import tools_for_role
from harness.shared.agent_prompts import (
    PLANNER_PROMPT_TEMPLATE,
    REASONER_PROMPT_TEMPLATE,
    VERIFIER_PROMPT_TEMPLATE,
    compose_system_prompt,
    strip_yaml_frontmatter,
)
from harness.shared.orchestrator.loop import ExecutionLoop
from harness.shared.tests._helpers import REPO
from harness.shared.tool_schemas import NEMOTRON_TOOLS, format_tools_paragraph

pytestmark = pytest.mark.governance

AGENTS = REPO / ".mango" / "agents"
BRIDGE_NAMES = {
    spec["function"]["name"]
    for spec in NEMOTRON_TOOLS
    if isinstance(spec, dict) and isinstance(spec.get("function"), dict)
}
IDE_ONLY = frozenset({"Bash", "Read", "Grep", "Glob", "Write", "Edit"})
_IDENT = re.compile(r"`([A-Za-z_][A-Za-z0-9_]*)`")


def _reasoner_prompt(loop: ExecutionLoop) -> str:
    tools = tools_for_role("nemotron-reasoner", NEMOTRON_TOOLS)
    return compose_system_prompt(loop.load_agent_prompt("nemotron-reasoner"), tools)


def test_reasoner_system_prompt_tools_match_bridge(mock_workspace: Path) -> None:
    """AC-1: composed prompt names exactly the role-filtered bridge tools."""
    from harness.shared.mango_mas_orchestrator import MangoMASOrchestrator

    orch = MangoMASOrchestrator(workspace_dir=mock_workspace)
    prompt = _reasoner_prompt(orch.execution_loop)
    expected = [spec["function"]["name"] for spec in tools_for_role("nemotron-reasoner", NEMOTRON_TOOLS)]
    paragraph = format_tools_paragraph(tools_for_role("nemotron-reasoner", NEMOTRON_TOOLS))
    assert paragraph in prompt
    for name in expected:
        assert f"`{name}`" in paragraph
    for banned in ("Bash", "Read", "Grep", "Glob"):
        assert banned not in paragraph
        assert f"tools: {banned}" not in prompt


def test_persona_tools_subset_of_nemotron_tools(tmp_path: Path) -> None:
    """AC-2: a non-registry tool name in a persona body fails; registry names pass."""

    def scan(body: str) -> set[str]:
        names = set(_IDENT.findall(body)) & (IDE_ONLY | BRIDGE_NAMES)
        return names - BRIDGE_NAMES

    for path in AGENTS.glob("*.md"):
        stray = scan(strip_yaml_frontmatter(path.read_text(encoding="utf-8")))
        assert not stray, f"{path.name} names non-bridge tools in the body: {sorted(stray)}"

    bad = tmp_path / "bad.md"
    bad.write_text("# x\nUse `Bash` please.\n", encoding="utf-8")
    assert scan(bad.read_text(encoding="utf-8")) == {"Bash"}
    good = tmp_path / "good.md"
    good.write_text("# x\nPrefer `generate_code` for new Python.\n", encoding="utf-8")
    assert scan(good.read_text(encoding="utf-8")) == set()


def test_model_call_logs_prompt_sha(mock_workspace: Path, mock_complete_chat, caplog: pytest.LogCaptureFixture) -> None:
    """AC-3: model_call extra carries prompt_sha of the exact system prompt, never the body."""
    mock_complete_chat.return_value = {"choices": [{"message": {"content": "ok", "tool_calls": []}}], "usage": {}}
    from harness.shared.mango_mas_orchestrator import MangoMASOrchestrator

    orch = MangoMASOrchestrator(workspace_dir=mock_workspace)
    with caplog.at_level(logging.DEBUG, logger="harness.shared.orchestrator.loop"):
        orch.execute_agent("nemotron-reasoner", "say hi")
    events = [r for r in caplog.records if getattr(r, "event", None) == "model_call"]
    assert events, "no model_call log event"
    extra = events[0]
    tools = tools_for_role("nemotron-reasoner", NEMOTRON_TOOLS)
    expected = hashlib.sha256(
        compose_system_prompt(orch.execution_loop.load_agent_prompt("nemotron-reasoner"), tools).encode("utf-8")
    ).hexdigest()
    assert extra.prompt_sha == expected
    assert extra.prompt_sha not in extra.getMessage()
    logged = " ".join(str(getattr(extra, field, "")) for field in extra.__dict__)
    assert "You are a specialized reasoning subagent" not in logged


def test_load_agent_prompt_strips_frontmatter(tmp_path: Path) -> None:
    """AC-4: YAML frontmatter never reaches the composed Nemotron system prompt."""
    from harness.shared.governance.broker import ExecutionBroker
    from harness.shared.governance.verification import VerificationRunner
    from harness.shared.orchestrator.dispatcher import ToolDispatcher
    from harness.shared.orchestrator.hook_runner import HookRunner

    agents = tmp_path / ".mango" / "agents"
    agents.mkdir(parents=True)
    (agents / "nemotron-reasoner.md").write_text(
        "---\nname: x\ntools: Bash, Read\n---\nBody only.\n",
        encoding="utf-8",
    )
    loop = ExecutionLoop(
        workspace_dir=tmp_path,
        agents_dir=agents,
        dispatcher=ToolDispatcher(workspace_dir=tmp_path, broker=ExecutionBroker()),
        hook_runner=HookRunner(workspace_dir=tmp_path, hooks_dir=tmp_path / "hooks"),
        verification=VerificationRunner(ExecutionBroker(), "test-eval", target=None),
        verification_cwd=tmp_path,
    )
    loaded = loop.load_agent_prompt("nemotron-reasoner")
    assert loaded.startswith("Body only")
    assert "Bash" not in loaded
    composed = compose_system_prompt("---\ntools: Bash\n---\nKeep me.\n", [])
    assert "Bash" not in composed
    assert "Keep me." in composed


def test_agent_prompt_templates_have_no_hardcoded_tool_inventory() -> None:
    """AC-5: templates must not embed a hand-maintained bridge tool list."""
    joined = PLANNER_PROMPT_TEMPLATE + REASONER_PROMPT_TEMPLATE + VERIFIER_PROMPT_TEMPLATE
    for name in ("read_file", "apply_patch", "write_file", "run_command", "generate_code"):
        assert name not in joined, f"template still names {name}"
