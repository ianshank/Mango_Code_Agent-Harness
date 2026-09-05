"""Tests for harness/shared/agent_prompts.py.

Previously untested directly (only touched incidentally via
test_orchestrator_hooks.py's hook-name checks) — a coverage-gap-closure
finding, not a padding exercise: these prompts encode real,
security-relevant instructions (no chained shell commands, no `python -c`,
route unmet needs through knowledge_gap_log instead of retrying denied
actions) that nothing currently pins, so a future edit could silently
weaken one without any test noticing.
"""

from __future__ import annotations

from harness.shared.agent_authority import ACTIVE_TO_CANONICAL
from harness.shared.agent_prompts import (
    AUTONOMOUS_AGENT_GUARDRAIL,
    PERMITTED_HOOK_NAMES,
    PLANNER_PROMPT_TEMPLATE,
    PRE_RUN_HOOK,
    REASONER_PROMPT_TEMPLATE,
    TASK_LOG_PREVIEW_CHARS,
    VERIFIER_PROMPT_TEMPLATE,
)


class TestPromptTemplatesFormatCleanly:
    """Each template must actually render with its documented placeholder,
    not raise on a real value (a stray literal `{` or a renamed placeholder
    would break this at call time, not at import time)."""

    def test_planner_template_formats(self) -> None:
        rendered = PLANNER_PROMPT_TEMPLATE.format(task="add a login form", open_gaps="")
        assert "add a login form" in rendered

    def test_planner_template_surfaces_open_gaps(self) -> None:
        rendered = PLANNER_PROMPT_TEMPLATE.format(
            task="add a login form",
            open_gaps="Open knowledge gaps (most recent first):\n- Q: how?; need: docs\n",
        )
        assert "Open knowledge gaps" in rendered
        assert "how?" in rendered

    def test_planner_template_open_gaps_default_empty_is_ok(self) -> None:
        """Callers may pass an empty string when the store has nothing to surface."""
        rendered = PLANNER_PROMPT_TEMPLATE.format(task="t", open_gaps="")
        assert "Open knowledge gaps" not in rendered

    def test_reasoner_template_formats(self) -> None:
        rendered = REASONER_PROMPT_TEMPLATE.format(plan="1. write the handler")
        assert "1. write the handler" in rendered

    def test_verifier_template_formats(self) -> None:
        rendered = VERIFIER_PROMPT_TEMPLATE.format(code_output="def f(): pass")
        assert "def f(): pass" in rendered


class TestGovernanceInstructionsArePresent:
    """Regression guard for the specific safety instructions these prompts
    carry -- an edit that shortens or drops one of these would otherwise be
    invisible to every existing test, since none of them import this module."""

    def test_guardrail_appears_in_all_three_templates(self) -> None:
        for template in (PLANNER_PROMPT_TEMPLATE, REASONER_PROMPT_TEMPLATE, VERIFIER_PROMPT_TEMPLATE):
            assert AUTONOMOUS_AGENT_GUARDRAIL in template

    def test_planner_forbids_chained_commands(self) -> None:
        assert "NEVER suggest chained commands" in PLANNER_PROMPT_TEMPLATE
        assert "python -c" in PLANNER_PROMPT_TEMPLATE

    def test_reasoner_forbids_chained_commands(self) -> None:
        assert "do not chain with" in REASONER_PROMPT_TEMPLATE

    def test_reasoner_directs_unmet_needs_to_knowledge_gap_log(self) -> None:
        """The reasoner must not be told to retry a denied external action --
        it should be pointed at the declared escape hatch instead (DEC-011)."""
        assert "knowledge_gap_log" in REASONER_PROMPT_TEMPLATE

    def test_verifier_requires_an_explicit_verdict(self) -> None:
        assert "VERDICT: PASS" in VERIFIER_PROMPT_TEMPLATE
        assert "VERDICT: FAIL" in VERIFIER_PROMPT_TEMPLATE


class TestPermittedHookNames:
    """PERMITTED_HOOK_NAMES is derived from ACTIVE_TO_CANONICAL rather than
    hand-listed specifically so it cannot drift from the active-role set --
    this pins the derivation itself, not just its current membership."""

    def test_contains_the_pre_run_hook(self) -> None:
        assert PRE_RUN_HOOK in PERMITTED_HOOK_NAMES

    def test_contains_exactly_one_post_hook_per_active_role(self) -> None:
        expected = {PRE_RUN_HOOK} | {f"post-{role}-run" for role in ACTIVE_TO_CANONICAL}
        assert PERMITTED_HOOK_NAMES == expected

    def test_is_a_frozenset(self) -> None:
        """Immutable by construction -- a caller cannot widen the allowlist
        by mutating what it was handed."""
        assert isinstance(PERMITTED_HOOK_NAMES, frozenset)


class TestTaskLogPreviewChars:
    def test_is_a_positive_int(self) -> None:
        assert isinstance(TASK_LOG_PREVIEW_CHARS, int)
        assert TASK_LOG_PREVIEW_CHARS > 0
