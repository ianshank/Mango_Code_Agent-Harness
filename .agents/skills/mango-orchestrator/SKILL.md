---
name: mango-orchestrator
description: Guidelines and patterns for the MangoMAS Orchestrator, detailing LLM invocation safety guardrails, policy constraints, and prompt injection mitigation.
---

# MangoMAS Orchestrator Guidelines

This skill provides the required patterns when modifying or interacting with the `mango_mas_orchestrator.py` module in the MangoMAS ecosystem. The orchestrator is the primary layer responsible for invoking LLM endpoints (via `nemotron_bridge`) and wrapping those interactions in strict safety, policy, and cognitive guardrails.

## Safety Guardrails & Policy Constraints

When adding new prompts or modifying existing orchestrator logic, ensure the following invariants:

1. **Guardrail Injection**: All agent prompts MUST be prefixed with `AUTONOMOUS_AGENT_GUARDRAIL` to prevent prompt injection and unauthorized shell access.
2. **Hypothesis Confidence Logging**: All responses from the LLM MUST be parsed for hypothesis confidence (using `_extract_confidence`), defaulting to `DEFAULT_HYPOTHESIS_CONFIDENCE` if parsing fails.
3. **Lineage Preservation**: When sending a `CognitiveSignal`, always attach `run_id`, `producer_id="mango_mas_orchestrator"`, and appropriate `signal_type`.

## Shadow Planner Subsystem

The orchestrator supports a transparent `shadow_planner` subsystem which intercepts LLM invocations and routes them to a parallel planner implementation (when `SHADOW_PLANNER_ENV` is set to true).

- **Rule**: Do not hardcode conditionals bypassing the shadow planner. Always use `run_shadow_comparison` from `shadow_planner.py`.
- **Constraint**: The shadow planner path MUST be byte-for-byte idempotent if not enabled.

## Tool Hook Integration

The orchestrator permits explicit tool hooks mapped through `PERMITTED_HOOK_NAMES`. Any new tool added must be explicitly registered in this list to ensure proper governance and isolation.

Use this skill whenever working on LLM routing, LLM safety constraints, or modifying prompt generation inside `harness/shared/`.
