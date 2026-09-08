"""Reason constants and classification helpers for LangGraph quality and plan gates."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from harness.shared.langgraph.state import MangoState

from harness.shared.langgraph.errors import blocking_error

logger = logging.getLogger(__name__)

#: ``gate_status`` keys this module writes beside the per-gate outcomes.
#: ``quality_gate_reason`` tells ``_route_quality_gate`` *why* the gate failed,
#: so a deterministic failure escalates instead of consuming revision budget;
#: ``clarify_count`` bounds the plan_gate/clarify cycle. Both live in the
#: existing dict channel rather than as new channels, so ``CHANNEL_COUNT``
#: (INV-LG-1) is unchanged (C-LGH-2).
QUALITY_GATE_REASON = "quality_gate_reason"
CLARIFY_COUNT = "clarify_count"

#: Why ``quality_gate_node`` withheld a pass.
REASON_ERROR = "error"
REASON_INCONCLUSIVE = "inconclusive"
REASON_TESTS_FAILED = "tests_failed"

#: The only reason a revision can fix, and therefore the only one that may
#: spend revision budget. Stated as the *retryable* set rather than the
#: terminal one so that a new reason is terminal until someone argues
#: otherwise -- the first version listed the terminal reason instead, and
#: ``REASON_INCONCLUSIVE`` fell through to the retry loop by omission.
#:
#: A failing suite is retryable because the implementer is handed the failure
#: message and can act on it. The other two are not: ``errors`` is an
#: ``operator.add`` accumulator no node clears, so the record that failed the
#: gate is still there next pass; and an inconclusive result means the
#: verification path produced no evidence, which nothing inside the loop can
#: change. Retrying either spends a write-capable revision per attempt to
#: reach the same terminal (R-LGH-3, R-LGH-8).
RETRYABLE_REASONS = frozenset({REASON_TESTS_FAILED})


def _nonneg_int_count(value: object) -> int | None:
    """Return ``value`` when it is a non-boolean, non-negative int; else ``None``.

    ``bool`` is a subclass of ``int``, so ``True`` must be rejected explicitly:
    otherwise ``{"passed": True, "failed": 0}`` would look like a green suite.
    """
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    if value < 0:
        return None
    return value


def _conclusive(latest: object) -> bool:
    """Whether a ``test_results`` entry is evidence that a suite actually ran.

    ``passed == failed == 0`` is the shape ``evaluation_node`` returns on its
    no-orchestrator path, and grading it by ``failed > 0`` alone made zero
    executed tests indistinguishable from a green suite. DEC-024 makes an
    absence of evidence a non-pass, so it is graded as one (R-LGH-2).

    Both ``passed`` and ``failed`` MUST be present and MUST be non-boolean,
    non-negative integers before either is summed. A malformed or incomplete
    row (negative counts, strings, booleans, missing keys) is inconclusive,
    never a raise and never a vacuous pass (Copilot review on PR #87).
    """
    if not isinstance(latest, dict):
        return False
    if "passed" not in latest or "failed" not in latest:
        logger.debug(
            "test_results row inconclusive: missing passed/failed keys (keys=%s)",
            sorted(latest.keys()),
        )
        return False
    passed = _nonneg_int_count(latest.get("passed"))
    failed = _nonneg_int_count(latest.get("failed"))
    if passed is None or failed is None:
        logger.debug(
            "test_results row inconclusive: malformed counts passed=%r failed=%r",
            latest.get("passed"),
            latest.get("failed"),
        )
        return False
    return passed + failed > 0


def _quality_gate_reason(state: MangoState) -> str | None:
    """Why the quality gate withholds a pass, or ``None`` when it grants one."""
    if blocking_error(state.get("errors", [])) is not None:
        return REASON_ERROR
    test_results = state.get("test_results", [])
    latest = test_results[-1] if test_results else None
    if not _conclusive(latest):
        return REASON_INCONCLUSIVE
    # ``_conclusive`` already proved ``latest`` is a dict with valid counts;
    # re-read through the same helper so the gate never raises on bad input.
    if not isinstance(latest, dict):
        return REASON_INCONCLUSIVE
    failed = _nonneg_int_count(latest.get("failed"))
    if failed is None:
        return REASON_INCONCLUSIVE
    if failed > 0:
        return REASON_TESTS_FAILED
    return None


__all__ = [
    "CLARIFY_COUNT",
    "QUALITY_GATE_REASON",
    "REASON_ERROR",
    "REASON_INCONCLUSIVE",
    "REASON_TESTS_FAILED",
    "RETRYABLE_REASONS",
    "_conclusive",
    "_nonneg_int_count",
    "_quality_gate_reason",
]
