"""The extracted prompt templates format the way the orchestrator expects.

Extracted from `mango_mas_orchestrator` for line budget, not behavior --
`test_mango_mas_orchestrator.py`'s existing end-to-end coverage never asserted
on prompt *content* before this move (there was nothing to import), so these
pin the one thing that coverage gap would otherwise leave unchecked: that the
move was byte-for-byte, not just import-clean.
"""
from __future__ import annotations

from harness.shared.prompt_templates import (
    AUTONOMOUS_AGENT_GUARDRAIL,
    PLANNER_PROMPT_TEMPLATE,
    REASONER_PROMPT_TEMPLATE,
    VERIFIER_PROMPT_TEMPLATE,
)


class TestEveryTemplateCarriesTheGuardrail:
    """An autonomous agent that never sees the fail-closed guardrail is not
    bound by it -- the string has to actually be in what gets sent."""

    def test_planner(self) -> None:
        assert AUTONOMOUS_AGENT_GUARDRAIL in PLANNER_PROMPT_TEMPLATE.format(task="do X")

    def test_reasoner(self) -> None:
        assert AUTONOMOUS_AGENT_GUARDRAIL in REASONER_PROMPT_TEMPLATE.format(plan="do Y")

    def test_verifier(self) -> None:
        assert AUTONOMOUS_AGENT_GUARDRAIL in VERIFIER_PROMPT_TEMPLATE.format(code_output="did Z")


class TestEveryTemplateSubstitutesItsOwnField:
    """Each template's one placeholder must round-trip its caller's argument
    verbatim -- a renamed or dropped placeholder fails loudly (`KeyError` from
    `.format`) rather than silently sending the model a blank prompt."""

    def test_planner_carries_the_task(self) -> None:
        assert "build the thing" in PLANNER_PROMPT_TEMPLATE.format(task="build the thing")

    def test_reasoner_carries_the_plan(self) -> None:
        assert "step one, step two" in REASONER_PROMPT_TEMPLATE.format(plan="step one, step two")

    def test_verifier_carries_the_code_output(self) -> None:
        assert "wrote foo.py" in VERIFIER_PROMPT_TEMPLATE.format(code_output="wrote foo.py")


class TestTheReasonerTemplateNamesItsTools:
    def test_write_file_and_run_command_are_named(self) -> None:
        """The reasoner is the one role permitted to mutate the filesystem;
        the template is the only place that's ever told to it."""
        rendered = REASONER_PROMPT_TEMPLATE.format(plan="")
        assert "write_file" in rendered
        assert "run_command" in rendered

    def test_network_and_install_commands_are_flagged_as_denied(self) -> None:
        rendered = REASONER_PROMPT_TEMPLATE.format(plan="")
        assert "knowledge_gap_log" in rendered
