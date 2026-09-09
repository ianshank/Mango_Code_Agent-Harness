"""Regression: planner ``{open_gaps}`` and reasoner ``{open_hypotheses}`` slots survive merges.

Merge conflict resolution on ``agent_prompts.py`` once dropped the planner's
``{open_gaps}`` slot while ``ExecutionLoop.execute_loop`` kept calling
``.format(..., open_gaps=...)``. Extra kwargs are silently ignored by
``str.format``, so gaps were computed and never injected — the suite only
caught it via ``TestExecutionLoopPlannerGapPolicyPath``.

This pin fails at import/format time if either slot is removed again.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from harness.shared.agent_prompts import PLANNER_PROMPT_TEMPLATE, REASONER_PROMPT_TEMPLATE

pytestmark = pytest.mark.governance


def test_planner_prompt_template_keeps_open_gaps_slot() -> None:
    assert "{open_gaps}" in PLANNER_PROMPT_TEMPLATE
    assert "{task}" in PLANNER_PROMPT_TEMPLATE
    rendered = PLANNER_PROMPT_TEMPLATE.format(task="t", open_gaps="- Q: newest-gap")
    assert "newest-gap" in rendered
    # Empty injection must not raise and must leave the governance body intact.
    empty = PLANNER_PROMPT_TEMPLATE.format(task="t", open_gaps="")
    assert "CRITICAL GOVERNANCE RULES" in empty


def test_reasoner_prompt_template_keeps_open_hypotheses_slot() -> None:
    assert "{open_hypotheses}" in REASONER_PROMPT_TEMPLATE
    assert REASONER_PROMPT_TEMPLATE.endswith("Plan:\n{plan}{open_hypotheses}")
    rendered = REASONER_PROMPT_TEMPLATE.format(plan="p", open_hypotheses="\n- [provisional] id=x: c")
    assert "provisional" in rendered


def test_langgraph_planner_node_injects_open_gaps(tmp_path: Path) -> None:
    """A gap in the store must reach the prompt the orchestrator is handed.

    The defect this pins is the one in the module docstring: `.format(task=...)`
    without `open_gaps=` silently drops the kwarg, so gaps are computed and never
    injected. That is a fact about the *rendered prompt*, and this asserts it
    end to end — seed a gap, run the node, read what the orchestrator received.

    The previous version asserted `"format_gaps_for_planner" in
    inspect.getsource(nodes)`. That is a proxy for the property, not the
    property: it went red when `nodes.py` became a facade over
    `node_executors.py` with no behavioural change whatsoever, and it would
    equally have stayed green if the helper were imported and its result thrown
    away. A source-text check answers "does this name appear in this module",
    which is a narrower question than the one the caller is asking.
    """
    from harness.shared.langgraph import nodes

    memory = tmp_path / ".mango" / "memory"
    memory.mkdir(parents=True)
    (memory / "gaps.json").write_text(
        json.dumps([{"question": "GAP-SENTINEL-Q", "what_needed": "GAP-SENTINEL-NEED", "status": "open"}]),
        encoding="utf-8",
    )

    captured: dict[str, str] = {}

    class _CapturingOrchestrator:
        """Minimal stand-in: the node needs a workspace and somewhere to send the prompt."""

        workspace_dir = tmp_path

        def execute_agent(self, role: str, prompt: str, tools: list | None = None) -> str:
            captured[role] = prompt
            return "[PLAN] stub"

    result = nodes.planner_node(
        {"task": "ship the thing"},
        {"configurable": {"orchestrator": _CapturingOrchestrator()}},
    )

    assert "errors" not in result, f"planner_node raised rather than planning: {result}"
    prompt = captured.get("planner", "")
    assert prompt, "the orchestrator was never handed a planner prompt"
    assert "GAP-SENTINEL-Q" in prompt, f"the open gap never reached the prompt:\n{prompt}"
    assert "GAP-SENTINEL-NEED" in prompt
