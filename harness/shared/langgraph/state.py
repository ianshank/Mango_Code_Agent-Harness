"""MangoState: the 12-channel typed state for the LangGraph orchestration graph.

This module defines the shared state schema that flows through all nodes in the
LangGraph migration of the MangoMAS orchestrator.  It uses stdlib-only types
with ``Annotated`` reducers so that parallel fan-out branches (Phase 5) merge
correctly.

Channel design decisions (docs/architecture/langgraph_architecture.md):

* **LWW (last-write-wins):** ``plan``, ``shadow_plan``, ``plan_divergence``,
  ``revision_count``, ``gate_status``, ``verdict``, ``tool_budget_used``, ``task``.
  These represent "the latest truth" and have no reducer annotation.

* **Accumulators (``operator.add``):** ``patches``, ``findings``, ``test_results``,
  ``errors``.  These grow as nodes append; concurrent writes from parallel
  reviewers merge by list concatenation.

``revision_count`` is deliberately LWW rather than ``operator.add``.  In a
quality-gate retry loop (quality_gate → implementer → quality_gate), the
implementer sets it to N+1; ``operator.add`` would accumulate across the loop
iterations, producing 1, 3, 6, 10, … instead of 1, 2, 3, 4, ….

All values must be JSON-serializable for PostgresSaver compatibility.
``Path`` objects are serialized to ``str`` at node boundaries.
"""

from __future__ import annotations

import operator
from typing import Annotated, TypedDict


class MangoState(TypedDict, total=False):
    """Graph state flowing through all LangGraph nodes.

    ``total=False`` lets nodes return partial updates (only the channels they
    touch) without TypedDict complaining about missing keys.  The graph
    initialiser supplies defaults for all channels.
    """

    # ── LWW (last-write-wins, no reducer) ────────────────────
    task: str
    """The initial user task / prompt."""

    plan: str
    """The planner agent's output."""

    shadow_plan: str
    """The shadow planner's output (observation-only comparison)."""

    plan_divergence: float
    """Cosine distance between incumbent and shadow plans."""

    revision_count: int
    """Current revision iteration (LWW — see module docstring)."""

    gate_status: dict
    """Per-gate outcomes: ``{"plan_gate": "pass"|"fail", "quality_gate": ...}``."""

    verdict: str
    """Final harness verdict: ``VERIFIED`` | ``FAILED`` | ``BLOCKED``."""

    tool_budget_used: int
    """Cumulative tool calls spent across all nodes."""

    # ── Accumulators (operator.add reducer) ──────────────────
    patches: Annotated[list[dict], operator.add]
    """File patches applied: ``[{"file": str, "old_text": str, "new_text": str, "agent": str}]``."""

    findings: Annotated[list[dict], operator.add]
    """Review findings: ``[{"severity": str, "message": str, "agent": str, "file": str, "line": int}]``."""

    test_results: Annotated[list[dict], operator.add]
    """Test suite outcomes: ``[{"suite": str, "passed": int, "failed": int, "skipped": int, "coverage": float}]``."""

    errors: Annotated[list[dict], operator.add]
    """Error channel for partial-success fan-out: ``[{"node": str, "error": str, "traceback": str}]``."""


# ── Defaults for graph initialisation ────────────────────────

DEFAULT_STATE: MangoState = {
    "task": "",
    "plan": "",
    "shadow_plan": "",
    "plan_divergence": 0.0,
    "revision_count": 0,
    "gate_status": {},
    "verdict": "",
    "tool_budget_used": 0,
    "patches": [],
    "findings": [],
    "test_results": [],
    "errors": [],
}


#: Channels that use ``operator.add`` for parallel merge safety.
ACCUMULATOR_CHANNELS = frozenset({"patches", "findings", "test_results", "errors"})

#: Channels that are last-write-wins (no reducer).
LWW_CHANNELS = frozenset({"task", "plan", "shadow_plan", "plan_divergence",
                           "revision_count", "gate_status", "verdict",
                           "tool_budget_used"})

#: Total number of channels — pinned by ``test_langgraph_state.py``.
CHANNEL_COUNT = 12


__all__ = [
    "ACCUMULATOR_CHANNELS",
    "CHANNEL_COUNT",
    "DEFAULT_STATE",
    "LWW_CHANNELS",
    "MangoState",
]

