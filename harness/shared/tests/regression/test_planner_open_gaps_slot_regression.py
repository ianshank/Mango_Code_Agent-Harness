"""Regression: planner ``{open_gaps}`` and reasoner ``{open_hypotheses}`` slots survive merges.

Merge conflict resolution on ``agent_prompts.py`` once dropped the planner's
``{open_gaps}`` slot while ``ExecutionLoop.execute_loop`` kept calling
``.format(..., open_gaps=...)``. Extra kwargs are silently ignored by
``str.format``, so gaps were computed and never injected — the suite only
caught it via ``TestExecutionLoopPlannerGapPolicyPath``.

This pin fails at import/format time if either slot is removed again.
"""

from __future__ import annotations

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


def test_langgraph_planner_node_passes_open_gaps() -> None:
    """The experimental graph must not call ``.format(task=...)`` alone — KeyError."""
    import inspect

    from harness.shared.langgraph import nodes

    source = inspect.getsource(nodes.planner_node)
    assert "open_gaps=" in source or "open_gaps =" in source
    assert "format_gaps_for_planner" in inspect.getsource(nodes)
