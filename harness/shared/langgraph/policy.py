"""GraphPolicy: frozen configuration for the LangGraph orchestration graph.

Reads thresholds from ``governance-policy.json`` via the existing
``policy_loader`` module, avoiding hardcoded values per user rule.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class GraphPolicy:
    """Immutable policy configuration for graph compilation.

    Frozen so it cannot be mutated after construction.  All values derive from
    ``governance-policy.json`` or from explicit defaults documented here.
    """

    max_iterations: int = 10
    """Maximum revision loops (quality_gate → implementer → quality_gate)."""

    api_timeout_sec: int = 300
    """Per-node timeout for API-calling nodes (nemotron_bridge)."""

    tool_timeout_sec: int = 30
    """Per-tool-call timeout inside a node."""

    max_command_bytes: int = 8192
    """Ceiling on command length sent to the broker."""

    coverage_floor_lines: int = 90
    """Minimum line coverage for quality gate pass."""

    coverage_floor_branches: int = 80
    """Minimum branch coverage for quality gate pass."""

    recursion_limit: int = 50
    """LangGraph recursion limit. With 12 nodes and revision loops, 50
    accommodates up to ~4 full revision cycles before hitting the limit."""

    max_concurrency: int = 3
    """Maximum parallel node executions for Send fan-out (Phase 5).
    Respects Nemotron API rate limits."""

    max_delegation_depth: int = 2
    """From agent_defaults: maximum subagent delegation depth."""

    max_parallel_subagents: int = 6
    """From agent_defaults: maximum parallel subagents."""

    plan_divergence_threshold: float = 0.35
    """Cosine distance above which plan_gate routes to clarify node."""

    @classmethod
    def from_governance_json(cls) -> GraphPolicy:
        """Construct policy from the live ``governance-policy.json``.

        Falls back to defaults if the policy file is absent or malformed,
        logging a warning rather than raising — the graph must compile even
        on a minimal workspace.
        """
        try:
            from harness.shared.policy_loader import orchestrator_defaults

            orch: dict[str, Any] = orchestrator_defaults()

            # Attempt to load coverage and agent_defaults sections
            from harness.shared.policy_loader import load_policy

            policy = load_policy()
            coverage = policy.get("coverage", {})
            agent_defs = policy.get("agent_defaults", {})

            return cls(
                max_iterations=orch.get("max_iterations", cls.max_iterations),
                api_timeout_sec=orch.get("api_timeout_sec", cls.api_timeout_sec),
                tool_timeout_sec=orch.get("tool_timeout_sec", cls.tool_timeout_sec),
                max_command_bytes=orch.get("max_command_bytes", cls.max_command_bytes),
                coverage_floor_lines=coverage.get("lines", cls.coverage_floor_lines),
                coverage_floor_branches=coverage.get("branches", cls.coverage_floor_branches),
                max_delegation_depth=agent_defs.get("max_delegation_depth", cls.max_delegation_depth),
                max_parallel_subagents=agent_defs.get("max_parallel_subagents", cls.max_parallel_subagents),
            )
        except Exception:  # noqa: BLE001
            logger.warning(
                "GraphPolicy: could not load governance-policy.json; using defaults",
                exc_info=True,
            )
            return cls()


__all__ = ["GraphPolicy"]
