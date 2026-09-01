# Specification: Autonomous Healing Integration

**Version:** 2.2.0

**Status:** Draft

## 1. Overview

The Autonomous Healing module empowers the `nemotron-reasoner` agent to automatically detect, diagnose, and remediate systemic errors during test suite execution (`vitest` / `pytest`). This capability turns reactive test failures into self-correcting feedback loops.

## Requirements

- Test failures trigger an automated healing sequence.
- The raw output and tracebacks are passed to the reasoning agent.
- Healing attempts must be strictly bounded by a maximum retry budget.
- The changes proposed by the healing loop must pass standard governance guardrails.

## Acceptance criteria

- `TestHealer` class correctly runs the test suite and captures output, proven by `pytest -k test_run_test_suite_success`.
- Non-zero exits successfully formulate a remediation prompt, proven by `pytest -k test_heal_until_green_recovers_after_remediation`.
- The LangGraph MAS orchestrator is invoked with the localized `healing_state`, proven by `pytest -k test_heal_until_green_langgraph_branch`.
- Max retries gracefully terminate the loop, proven by `pytest -k test_heal_until_green_exhausted`.
- `max_retries` above the governance policy limit is rejected at construction, proven by `pytest -k test_healer_max_retries_clamped_to_policy`.
- Test execution routes through the injected ExecutionBroker (INV-8), proven by `pytest -k test_healer_broker_routes_test_execution`.

## 2. Architecture

The module will utilize a specific test-driven trigger architecture:

- **Watcher Hook**: A post-test runner script identifies test failures with a non-zero exit code.
- **Auto-Triage**: Passes the raw error outputs and tracebacks to the agent via a `heal_target` node.
- **Budgeting**: Autonomous healing loops are bounded by a fixed retry budget (e.g., max 3 attempts) to prevent infinite regression cycles.

## 3. Governance Policy Enforcement

Healing processes are subject to the same `governance-policy.json` invariants as human-directed agent loops.

- `max_healing_retries`: Must be explicitly declared in the policy to limit runaway iterations.
- Code generated during healing must pass standard `pretooluse_guard.py` checks.
