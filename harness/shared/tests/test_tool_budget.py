"""The tool-call budget is per task, and a caller that does not ask for one is
unaffected.

Spec: ``docs/specs/verdict-propagation.md`` (C-VP-3, AC-12).

The defect these pin: ``agent_defaults.max_tool_calls_per_task`` was enforced by a
counter initialised inside ``execute_agent``, so a three-turn task could spend
three times the declared allowance while the policy value and the enforced value
agreed on the number. Every test in this repository builds a fresh orchestrator,
so nothing could see it.
"""
from __future__ import annotations

import typing

import pytest

from harness.shared.mango_mas_orchestrator import MangoMASOrchestrator
from harness.shared.tests._helpers import chat_response, tool_call
from harness.shared.tool_budget import ToolBudget

pytestmark = pytest.mark.governance


class TestSpendDown:
    def test_a_spend_within_the_limit_holds(self) -> None:
        assert ToolBudget(limit=10).consume(4) is True

    def test_a_spend_that_reaches_the_limit_exactly_holds(self) -> None:
        """The boundary, pinned on its own: `<=` and `<` differ only here."""
        assert ToolBudget(limit=3).consume(3) is True

    def test_a_spend_past_the_limit_does_not_hold(self) -> None:
        assert ToolBudget(limit=3).consume(4) is False

    def test_spending_accumulates_across_calls(self) -> None:
        budget = ToolBudget(limit=5)
        assert budget.consume(3) is True
        assert budget.consume(3) is False
        assert budget.used == 6

    def test_an_overspend_is_recorded_and_not_forgiven(self) -> None:
        """A caller that continues past a refusal must not regain the overspend."""
        budget = ToolBudget(limit=2)
        budget.consume(5)
        assert budget.used == 5
        assert budget.consume(0) is False

    def test_a_zero_limit_refuses_the_first_call(self) -> None:
        assert ToolBudget(limit=0).consume(1) is False

    def test_remaining_counts_down_and_floors_at_zero(self) -> None:
        budget = ToolBudget(limit=4)
        assert budget.remaining == 4
        budget.consume(3)
        assert budget.remaining == 1
        budget.consume(9)
        assert budget.remaining == 0


@pytest.fixture
def workspace(tmp_path):
    """A workspace holding only the three active roles.

    Active roles only: `_run_hook` refuses a hook name the orchestrator could not
    have constructed, and `post-<fictional role>-run` is one of those.
    """
    agents = tmp_path / ".mango" / "agents"
    agents.mkdir(parents=True)
    for role in ("planner", "nemotron-reasoner", "verifier"):
        (agents / f"{role}.md").write_text(f"# {role}\n", encoding="utf-8")
    return tmp_path


def _tool_turn(name: str = "knowledge_gap_log") -> dict[str, typing.Any]:
    """One model response requesting a single tool call."""
    return chat_response(tool_calls=[tool_call(name, {"question": "q", "what_needed": "w", "proposed_approach": "p"})])


class TestBudgetReachesTheOrchestrator:
    """The unit above is worthless if `execute_agent` does not consult it."""

    @staticmethod
    def _one_tool_then_answer(monkeypatch: pytest.MonkeyPatch) -> None:
        """Each turn requests exactly one tool call, then answers.

        Two turns therefore spend exactly two calls -- which is what makes a
        shared budget of 1 refuse the second turn and a fresh budget of 1 allow
        both. Without the "then answers" half, a turn spends its whole allowance
        against `max_iterations` and the two cases become indistinguishable.
        """
        import harness.shared.mango_mas_orchestrator as orch_module

        state = {"used_tool": False}

        def _fake(**_kw: typing.Any) -> dict[str, typing.Any]:
            if state["used_tool"]:
                state["used_tool"] = False
                return chat_response(content="done")
            state["used_tool"] = True
            return _tool_turn()

        monkeypatch.setattr(orch_module, "complete_chat", _fake)

    def test_a_shared_budget_is_consumed_across_turns(
        self, workspace, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """AC-12: two turns spend from one allowance, so the second is refused.

        Before this change the counter reset every turn and both turns passed --
        which is the whole defect: the policy says 100 per task and the code
        enforced 100 per turn.
        """
        self._one_tool_then_answer(monkeypatch)
        orch = MangoMASOrchestrator(workspace_dir=workspace, tool_timeout=5)
        budget = ToolBudget(limit=1)

        assert orch.execute_agent("nemotron-reasoner", "task one", budget=budget) == "done"
        with pytest.raises(RuntimeError, match="tool-call budget"):
            orch.execute_agent("nemotron-reasoner", "task two", budget=budget)

    def test_a_caller_that_passes_no_budget_gets_a_fresh_one(
        self, workspace, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Positive control, and the backward-compatibility guarantee.

        Without it, a budget that refused everything would satisfy the assertion
        above while breaking every existing caller.
        """
        self._one_tool_then_answer(monkeypatch)
        orch = MangoMASOrchestrator(workspace_dir=workspace, tool_timeout=5)
        orch.max_tool_calls_per_task = 1

        for task in ("task one", "task two"):
            assert orch.execute_agent("nemotron-reasoner", task) == "done"

    def test_the_refusal_names_the_budget_that_refused(
        self, workspace, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The message must report the limit applied, not the policy default."""
        self._one_tool_then_answer(monkeypatch)
        orch = MangoMASOrchestrator(workspace_dir=workspace, tool_timeout=5)

        with pytest.raises(RuntimeError, match=r"\(0 per task; policy agent_defaults"):
            orch.execute_agent("nemotron-reasoner", "t", budget=ToolBudget(limit=0))


class TestConsumeRejectsMisuse:
    """A negative count would decrease `used` and mint budget instead of
    spending it. `len(tool_calls)` can never be negative at the one production
    call site, but the class is meant to be reusable (CLAUDE.md: no ad hoc,
    single-purpose types), and a defensive check here is cheaper than a second
    caller rediscovering the gap.
    """

    def test_a_negative_count_is_refused(self) -> None:
        with pytest.raises(ValueError, match="negative"):
            ToolBudget(limit=10).consume(-1)

    def test_a_refused_negative_count_does_not_mutate_the_budget(self) -> None:
        budget = ToolBudget(limit=10)
        with pytest.raises(ValueError):
            budget.consume(-3)
        assert budget.used == 0

    def test_zero_is_still_a_valid_count(self) -> None:
        """Positive control: the boundary is `< 0`, not `<= 0`."""
        assert ToolBudget(limit=10).consume(0) is True
