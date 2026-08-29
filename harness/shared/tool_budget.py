"""The cumulative tool-call budget for one orchestration task.

``agent_defaults.max_tool_calls_per_task`` is named "per task" and its own
diagnostic text says "per task", but it was enforced by a counter initialised
inside ``execute_agent`` -- so it was a *per-turn* budget, and a three-turn task
could spend three times the declared value. The count is the same class of drift
``test_policy_consistency`` exists to catch, one layer down: the policy value and
the enforced value agreed on the number and disagreed on the unit.

The budget is a value the caller owns and threads through the turns it wants
accounted together, rather than state on the orchestrator. That is deliberate:
an accumulator on ``self`` needs a reset, a reset needs a correct call site, and
a missing reset is invisible to every test that builds a fresh orchestrator --
which is every test in this repository. Passing the budget in makes the mistake
unrepresentable instead of merely tested.

``execute_agent(..., budget=None)`` creates a fresh budget per call, which is
byte-for-byte the behaviour every existing caller had.
"""
from __future__ import annotations

import dataclasses


@dataclasses.dataclass
class ToolBudget:
    """A spend-down counter for tool calls, shared across the turns of one task.

    Mutable by design: it is threaded through several turns and each one spends
    from the same allowance. The frozen-value-object idiom used elsewhere in this
    package is for things that cross a trust boundary; this crosses none.
    """

    limit: int
    used: int = 0

    def consume(self, count: int) -> bool:
        """Spend ``count`` calls; return whether the budget still holds.

        Returns a bool rather than raising so the caller keeps ownership of the
        refusal: the orchestrator has a post-run hook to fire and a message that
        names the policy key, and splitting those across two modules would put
        the diagnostic somewhere the reader is not.

        The spend is recorded even when it exceeds the limit, so a caller that
        chooses to continue cannot silently regain the overspend.
        """
        self.used += count
        return self.used <= self.limit

    @property
    def remaining(self) -> int:
        """Calls left before the limit is reached; never negative."""
        return max(0, self.limit - self.used)
