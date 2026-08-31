"""LangGraph orchestration package for the Mango Code Agent Harness.

This package is an **optional** overlay.  When the ``langgraph`` library is
installed (requires Python ≥ 3.10), importing this package makes the
``StateGraph``-based orchestrator available alongside the existing
``MangoMASOrchestrator``.

When ``langgraph`` is *not* installed, the package gracefully degrades:
``LANGGRAPH_AVAILABLE`` is ``False`` and no LangGraph-specific symbols are
exported.  The existing orchestrator continues to work on all Python versions.

Feature detection uses ``try/except ImportError`` (not ``sys.version_info``):
the constraint is whether langgraph is *installed*, not whether the Python
version supports it.  This follows the ``torch.cuda.is_available()`` /
``transformers.is_torch_available()`` pattern.
"""

from __future__ import annotations

# ── Feature detection ────────────────────────────────────────

try:
    from langgraph.graph import StateGraph  # noqa: F401 — probe only

    LANGGRAPH_AVAILABLE = True
except ImportError:
    LANGGRAPH_AVAILABLE = False

# ── Always-available exports (stdlib only) ───────────────────

from harness.shared.langgraph.policy import GraphPolicy
from harness.shared.langgraph.state import (
    ACCUMULATOR_CHANNELS,
    CHANNEL_COUNT,
    DEFAULT_STATE,
    LWW_CHANNELS,
    MangoState,
)

__all__ = [
    "ACCUMULATOR_CHANNELS",
    "CHANNEL_COUNT",
    "DEFAULT_STATE",
    "LANGGRAPH_AVAILABLE",
    "LWW_CHANNELS",
    "GraphPolicy",
    "MangoState",
]

# ── Conditional LangGraph exports ────────────────────────────

if LANGGRAPH_AVAILABLE:
    # These imports are only available when langgraph is installed.
    # They are added to __all__ dynamically.
    try:
        from harness.shared.langgraph.graph import build_graph

        __all__ = [*__all__, "build_graph"]
    except ImportError:
        # graph.py may not exist yet (Phase 1 in progress)
        pass
