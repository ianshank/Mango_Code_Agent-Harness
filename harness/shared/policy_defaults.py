"""Typed accessors for blocks in governance-policy.json.

Split from ``policy_loader`` so a routing accessor cannot breach
``limits.size_budget_lines``. Callers keep importing ``harness.shared.policy_loader``.
"""

from __future__ import annotations

from pathlib import Path

try:
    from harness.shared.policy_io import (
        AgentMemoryLimits,
        CoverageThresholds,
        GateFloors,
        LangGraphDefaults,
        NemotronDefaults,
        OrchestratorLimits,
        PolicyError,
        _log_resolution,
        _section,
        resolve_policy_path,
    )
except ImportError:  # sibling import when this dir is sys.path[0]
    from policy_io import (  # type: ignore[no-redef]
        AgentMemoryLimits,
        CoverageThresholds,
        GateFloors,
        LangGraphDefaults,
        NemotronDefaults,
        OrchestratorLimits,
        PolicyError,
        _log_resolution,
        _section,
        resolve_policy_path,
    )


def orchestrator_defaults(policy_path: Path | None = None) -> OrchestratorLimits:
    """Operational limits for MangoMASOrchestrator; policy `orchestrator` block."""
    section = _section("orchestrator", policy_path)
    resolved: OrchestratorLimits = {
        "max_iterations": section.int("max_iterations", 10),
        "api_timeout_sec": section.int("api_timeout_sec", 300),
        # The ceiling on the harness's own verification run (`make test-python`
        # through `VerificationRunner`), which is a test suite and not a model
        # round-trip: it used to borrow `api_timeout_sec`, so a runner about
        # four times slower than the 4-core container that finishes the suite
        # in 70-85 s turned a passing change into BLOCKED/harness_fault
        # (2026 standards audit H16). 900 s is roughly ten times the measured
        # duration: enough for a cold cache, a shared runner and a suite that
        # has doubled, while still bounding a hung subprocess (R-VP-5).
        "verification_timeout_sec": section.int("verification_timeout_sec", 900),
        "tool_timeout_sec": section.int("tool_timeout_sec", 30),
        "max_command_bytes": section.int("max_command_bytes", 8192),
        "max_healing_retries": section.int("max_healing_retries", 3),
        # Captured-output ceiling for the process backend (a containment control:
        # an unbounded capture becomes a prompt, a signal-sink entry and an HTTP
        # body). Was an unlinked 64 KiB literal in process_backend.py
        # (tech-debt-hardening-plan R-TDH-16).
        "max_output_bytes": section.int("max_output_bytes", 65536),
        # Context-window budget for model-facing history (audit H4). Generous
        # default so short runs / existing unit tests do not evict.
        # apply_context_policy always estimates the *current* list with
        # context_chars_per_token; measure_tokens prefers same-list
        # usage.prompt_tokens when present, else falls back to this coefficient.
        "context_budget_tokens": section.int("context_budget_tokens", 128000),
        "context_chars_per_token": section.float("context_chars_per_token", 4.0),
    }
    if resolved["context_chars_per_token"] <= 0:
        # `estimate_tokens` refuses a non-positive coefficient with ValueError.
        # Left to it, a bad policy value surfaced mid-run inside `execute_loop`
        # -- after the planner had spent a model call -- as a RuntimeError that
        # named no policy. Every other malformed value fails here, at load, with
        # the key and the file; this one now does too (DEC-058 review).
        path = resolve_policy_path(policy_path)
        raise PolicyError(
            f"policy orchestrator.context_chars_per_token must be positive, got "
            f"{resolved['context_chars_per_token']!r} (policy at {path})"
        )
    _log_resolution("orchestrator", resolved, policy_path)
    return resolved


def nemotron_defaults(policy_path: Path | None = None) -> NemotronDefaults:
    """Request defaults for the Nemotron bridge; policy `nemotron` block."""
    section = _section("nemotron", policy_path)
    resolved: NemotronDefaults = {
        "temperature": section.float("temperature", 0.2),
        # Was a literal 0.7 in the Node client and absent from the Python
        # payload entirely -- the two stacks sampled differently against the
        # same endpoint. One key, both readers (NEXT_STEPS.md NS-16).
        "top_p": section.float("top_p", 0.7),
        "max_tokens": section.int("max_tokens", 4096),
        "timeout_ms": section.int("timeout_ms", 30000),
        "max_retries": section.int("max_retries", 0),
    }
    _log_resolution("nemotron", resolved, policy_path)
    return resolved


def max_tool_calls_per_task(policy_path: Path | None = None) -> int:
    """Cumulative tool-call budget per agent task; policy `agent_defaults` block."""
    resolved = _section("agent_defaults", policy_path).int("max_tool_calls_per_task", 100)
    _log_resolution("agent_defaults", {"max_tool_calls_per_task": resolved}, policy_path)
    return resolved


def langgraph_defaults(policy_path: Path | None = None) -> LangGraphDefaults:
    """LangGraph orchestration-graph tuning; policy `langgraph` block."""
    section = _section("langgraph", policy_path)
    resolved: LangGraphDefaults = {
        "recursion_limit": section.int("recursion_limit", 50),
        "max_concurrency": section.int("max_concurrency", 3),
        "plan_divergence_threshold": section.float("plan_divergence_threshold", 0.35),
    }
    _log_resolution("langgraph", resolved, policy_path)
    return resolved


def coverage_defaults(policy_path: Path | None = None) -> CoverageThresholds:
    """Coverage gate thresholds consumed outside coverage_gate.py; policy `coverage` block.

    coverage_gate.py itself deliberately does not import this (policy-single-source.md's
    standalone-stdlib decision); this accessor is for other callers, such as GraphPolicy,
    that already depend on harness.shared and would otherwise read the section unvalidated.
    """
    section = _section("coverage", policy_path)
    resolved: CoverageThresholds = {
        "lines": section.int("lines", 90),
        "branches": section.int("branches", 80),
    }
    _log_resolution("coverage", resolved, policy_path)
    return resolved


def coverage_optional_extras(policy_path: Path | None = None) -> dict[str, dict]:
    """Optional extras whose tests a CI leg may deselect; policy `coverage.optional_extras`.

    Each entry maps an extra's name to ``import_name`` (what a leg lacking the
    extra cannot import), ``deselect_env`` (the variable that leg sets to "1";
    conftest.py deselects the extra's marked tests on it and coverage_gate.py
    waives the per-file floor for the extra's modules on it) and
    ``path_prefixes`` (those modules). One key, three readers (DEC-028).
    Absent block: {}. Malformed block: PolicyError.
    """
    extras = _section("coverage", policy_path).optional("optional_extras", {})
    if not isinstance(extras, dict):
        raise PolicyError("policy coverage.optional_extras must be an object keyed by extra name")
    result: dict[str, dict] = {}
    for name, spec in extras.items():
        if not isinstance(spec, dict):
            raise PolicyError(f"policy coverage.optional_extras[{name!r}] must be an object")
        import_name, deselect_env, prefixes = (
            spec.get("import_name"),
            spec.get("deselect_env"),
            spec.get("path_prefixes"),
        )
        if not isinstance(import_name, str) or not import_name or not isinstance(deselect_env, str) or not deselect_env:
            raise PolicyError(
                f"policy coverage.optional_extras[{name!r}] import_name and deselect_env must be non-empty strings"
            )
        if not isinstance(prefixes, list) or not prefixes or any(not isinstance(p, str) or not p for p in prefixes):
            raise PolicyError(
                f"policy coverage.optional_extras[{name!r}].path_prefixes must be a non-empty list of strings"
            )
        result[name] = {"import_name": import_name, "deselect_env": deselect_env, "path_prefixes": tuple(prefixes)}
    return result


def agent_defaults(policy_path: Path | None = None) -> dict:
    """Agent delegation/parallelism limits; policy `agent_defaults` block.

    Returns only the integer tuning values other modules construct from; the
    non-numeric keys in this section (approval/evidence lists, the
    deny_unclassified_side_effects flag) are read directly by validate_policy.py
    and test_policy_consistency.py and have no numeric-default shape for
    ``_Section.int``/``.float`` to validate.
    """
    section = _section("agent_defaults", policy_path)
    return {
        "max_delegation_depth": section.int("max_delegation_depth", 2),
        "max_parallel_subagents": section.int("max_parallel_subagents", 6),
    }


def lats_defaults(policy_path: Path | None = None) -> dict:
    """LATS/MCTS search tuning; policy `lats` block."""
    section = _section("lats", policy_path)
    return {
        "max_budget": section.int("max_budget", 10),
        "exploration_weight": section.float("exploration_weight", 1.414),
    }


def agent_memory_defaults(policy_path: Path | None = None) -> AgentMemoryLimits:
    """Retention / planner-surface limits for agent memory; policy `agent_memory` block."""
    section = _section("agent_memory", policy_path)
    resolved: AgentMemoryLimits = {
        "max_gaps": section.int("max_gaps", 100),
        "max_hypotheses": section.int("max_hypotheses", 100),
        "planner_gap_limit": section.int("planner_gap_limit", 10),
        # Phase 2 of DEC-057 (DEC-058, `docs/specs/hypothesis-surfacing.md`):
        # how many *open* hypotheses the reasoner prompt may carry, and the
        # estimated-token ceiling on the whole rendered block, measured with
        # `orchestrator.context_chars_per_token`. A limit of 0 renders nothing
        # and is the operator's kill switch. The block is a non-group message,
        # so `context_policy` never evicts it: these two keys are the only bound
        # on what it costs every model call after the reasoner's first.
        "reasoner_hypothesis_limit": section.int("reasoner_hypothesis_limit", 10),
        "reasoner_hypothesis_budget_tokens": section.int("reasoner_hypothesis_budget_tokens", 1500),
    }
    _log_resolution("agent_memory", resolved, policy_path)
    return resolved


def gate_floors(policy_path: Path | None = None) -> GateFloors:
    """Anti-vacuity population floors for the drift gates; policy `gates` block.

    A gate that examined nothing prints the same ``[PASS]`` as one that examined
    everything: ``check_dedup`` and ``check_py_compat`` both exited 0 on an empty
    tree, reporting ``0 per-stack script(s)`` and ``0 file(s)`` (R-AEI-3). Each
    floor is the population a run must reach before its pass carries information,
    and is a ratchet: raise it as the population grows, never lower it to make a
    shrinking one pass.

    The built-in default is 0 -- *this deployment declares no floor* -- rather
    than this repository's own population, which no adopter shares and which
    would fail a smaller tree for having less code. An absent policy file is the
    adopter path and leaves the gates exactly as they behave today; a policy that
    carries the block and drops a key raises PolicyError, as every other accessor
    here does. A **new** top-level block rather than a key in `dedup`/`py_compat`
    for the DEC-043 reason recorded at R-AEI-11: a key added to an adopted block
    is a PolicyError for every adopter policy that predates it.
    """
    section = _section("gates", policy_path)
    if not section.declared():
        # A policy file that predates this block declares no floor. Refusing
        # here would break every adopter policy written before the block
        # existed -- the DEC-043 hazard a new top-level block was chosen to
        # avoid, which `_section` alone does not avoid because it marks any
        # present *file* as backed (Copilot review on PR #122).
        resolved: GateFloors = {"dedup_min_scripts": 0, "py_compat_min_files": 0}
        _log_resolution("gates", resolved, policy_path)
        return resolved
    resolved = {
        "dedup_min_scripts": section.int("dedup_min_scripts", 0),
        "py_compat_min_files": section.int("py_compat_min_files", 0),
    }
    _log_resolution("gates", resolved, policy_path)
    return resolved


def evidence_defaults(policy_path: Path | None = None) -> int | None:
    """Cap on broker evidence entries; policy ``evidence`` block (R-AEI-4, C-AEI-2).

    ``None`` when the block is undeclared (adopter path). A present block still
    owes ``max_entries``.
    """
    section = _section("evidence", policy_path)
    if not section.declared():
        _log_resolution("evidence", {"max_entries": None}, policy_path)
        return None
    resolved = section.int("max_entries", 256)
    _log_resolution("evidence", {"max_entries": resolved}, policy_path)
    return resolved


#: Legal values of ``execution.routing``. A third value is a PolicyError (AC-11).
EXECUTION_ROUTING_STATES = ("brokered", "refuse")


def execution_routing(policy_path: Path | None = None) -> str:
    """Two-state execution selector; policy ``execution`` block (R-AEI-11).

    An absent block (a policy that predates it) is ``brokered`` — DEC-043 is why
    this is a new top-level block rather than a key inside an adopted one.
    A present block with ``routing`` missing, or a third value, is PolicyError.
    """
    section = _section("execution", policy_path)
    if not section.declared():
        resolved = "brokered"
        _log_resolution("execution", {"routing": resolved}, policy_path)
        return resolved
    raw = section._value("routing", "brokered")
    if raw not in EXECUTION_ROUTING_STATES:
        raise PolicyError(f"policy execution.routing must be one of {EXECUTION_ROUTING_STATES}, got {raw!r}")
    resolved = str(raw)
    _log_resolution("execution", {"routing": resolved}, policy_path)
    return resolved
