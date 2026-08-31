"""GraphPolicy: frozen configuration for the LangGraph orchestration graph.

Reads thresholds from ``governance-policy.json`` via the existing
``policy_loader`` module, avoiding hardcoded values per user rule.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


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

        Fails closed (raises ``policy_loader.PolicyError``) when the policy
        file is *present but malformed* — matching ``policy_loader.py``'s
        documented contract, since silently falling back would let a
        corrupted policy weaken a gate or a runtime limit. Only a genuinely
        *absent* policy file is the adopter path, and that is already
        handled gracefully by ``policy_loader`` itself (``load_policy``
        returns ``{}``, and every ``*_defaults()`` accessor fills in its
        own built-in default from an empty section) — so this method does
        not need, and must not add, a second fallback layer on top of it.
        A prior version wrapped this whole method in a blanket
        ``except Exception: return cls()``, which silently swallowed a
        malformed-policy failure along with the (already-handled) absent
        case; see docs/specs/langgraph-policy-wiring.md.
        """
        from harness.shared.policy_loader import langgraph_defaults, load_policy, orchestrator_defaults

        orch: dict[str, Any] = orchestrator_defaults()
        lg: dict[str, Any] = langgraph_defaults()
        policy = load_policy()
        coverage = policy.get("coverage", {})
        agent_defs = policy.get("agent_defaults", {})

        return cls(
            max_iterations=orch["max_iterations"],
            api_timeout_sec=orch["api_timeout_sec"],
            tool_timeout_sec=orch["tool_timeout_sec"],
            max_command_bytes=orch["max_command_bytes"],
            coverage_floor_lines=coverage.get("lines", cls.coverage_floor_lines),
            coverage_floor_branches=coverage.get("branches", cls.coverage_floor_branches),
            recursion_limit=lg["recursion_limit"],
            max_concurrency=lg["max_concurrency"],
            plan_divergence_threshold=lg["plan_divergence_threshold"],
            max_delegation_depth=agent_defs.get("max_delegation_depth", cls.max_delegation_depth),
            max_parallel_subagents=agent_defs.get("max_parallel_subagents", cls.max_parallel_subagents),
        )


__all__ = ["GraphPolicy"]
