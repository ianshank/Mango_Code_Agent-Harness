"""Content-free lifecycle tracing for governed orchestration runs.

The trace intentionally carries only fixed phase/state values and elapsed time.
It must never become a transport for prompts, model output, tool arguments, or
tool results.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from typing import Any

logger = logging.getLogger(__name__)

TRACE_PHASES = frozenset(("planner", "reasoner", "verifier", "harness_verification"))
TRACE_STATES = frozenset(("started", "completed", "failed"))
TraceSink = Callable[[dict[str, Any]], None]
Clock = Callable[[], float]


class RunTrace:
    """Emit request-local, allowlisted phase lifecycle events."""

    def __init__(self, sink: TraceSink | None = None, clock: Clock = time.monotonic) -> None:
        self._sink = sink
        self._clock = clock
        self._started = clock()
        self._sequence = 0

    def emit(self, phase: str, state: str) -> None:
        if self._sink is None:
            return
        if phase not in TRACE_PHASES or state not in TRACE_STATES:
            raise ValueError("invalid governed run trace phase or state")
        self._sequence += 1
        event = {
            "sequence": self._sequence,
            "phase": phase,
            "state": state,
            "elapsed_ms": int((self._clock() - self._started) * 1000),
        }
        try:
            self._sink(event)
        except Exception:  # noqa: BLE001
            # Observability must not alter the governed operation. The sink
            # exception itself is omitted because third-party sinks may attach
            # unsafe data to exception messages.
            logger.warning("Run trace sink failed phase=%s state=%s", phase, state)

    def run(self, phase: str, action: Callable[[], Any]) -> Any:
        logger.info("Run phase started phase=%s", phase)
        self.emit(phase, "started")
        try:
            value = action()
        except Exception:
            logger.info("Run phase failed phase=%s", phase)
            self.emit(phase, "failed")
            raise
        logger.info("Run phase completed phase=%s", phase)
        self.emit(phase, "completed")
        return value
