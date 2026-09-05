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
import warnings


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

        Returns a bool rather than raising when the limit is exceeded, so the
        caller keeps ownership of the refusal: the orchestrator has a post-run
        hook to fire and a message that names the policy key, and splitting
        those across two modules would put the diagnostic somewhere the reader
        is not. A negative ``count`` is a different kind of wrong -- it would
        decrease the running total rather than spend from it, minting budget
        instead of consuming it -- and is rejected outright rather than folded
        into that return value.

        The spend is recorded even when it exceeds the limit, so a caller that
        chooses to continue cannot silently regain the overspend.
        """
        if count < 0:
            raise ValueError(f"cannot consume a negative count: {count}")
        self.used += count
        return self.used <= self.limit

    @property
    def remaining(self) -> int:
        """Calls left before the limit is reached; never negative.

        Deprecated: no first-party caller reads it (the loop decides on the
        boolean ``consume`` returns). Warns for one minor release and is then
        removed (tech-debt-hardening-plan R-TDH-17, C-TDH-2).
        """
        warnings.warn(
            "ToolBudget.remaining is deprecated; use the return value of consume()",
            DeprecationWarning,
            stacklevel=2,
        )
        return max(0, self.limit - self.used)
