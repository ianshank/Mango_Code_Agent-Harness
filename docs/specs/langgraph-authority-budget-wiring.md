# Spec: LangGraph Authority and Budget Decorator Wiring

## Problem statement

The LangGraph decorators `@with_authority` and `@budgeted` in `harness/shared/langgraph/decorators.py` were discovered during a tech-debt audit (2026-08-31) to fail open on lookup errors (e.g., missing policy or role configurations). Furthermore, despite being unit-tested in isolation, they are currently not applied to any of the 10 real LangGraph nodes in `harness/shared/langgraph/nodes.py`. This violates the fail-closed security posture (INV-10) and leaves the actual node execution boundaries devoid of authority and budget enforcement (`INV-LG-4`).

## Requirements

- R-DECOR-1: The `@with_authority` decorator MUST fail closed by denying execution and returning an error update when policy config or role definitions are missing or malformed.
- R-DECOR-2: The `@budgeted` decorator MUST fail closed by denying execution and returning an error update when the budget limit is exhausted or cannot be sourced from configuration.
- R-DECOR-3: The decorators MUST be applied to the appropriate state nodes in `harness/shared/langgraph/nodes.py` (e.g., `implementer_node`, `evaluation_node`).
- C-DECOR-1: The change MUST NOT violate `INV-LG-3` (Fail-Open Error Channel Routing). The decorators must fail closed by halting wrapped logic and recording structured denial messages to the `errors` state channel to prevent uncaught runtime crashes.

## Acceptance criteria

- [ ] AC-1: When `@with_authority` is invoked with a configuration lacking the required role policy, the node wrapper catches the error and records it in the `errors` channel, completely skipping the wrapped node logic. — verified by `pytest -k test_langgraph_decorators_fail_closed`
      · stage: `make test-langgraph` (R-DECOR-1, C-DECOR-1)
- [ ] AC-2: When `@budgeted` is invoked and the tool budget is exhausted, the node rejects execution and fails closed. — verified by `pytest -k test_langgraph_budget_exhaustion`
      · stage: `make test-langgraph` (R-DECOR-2)
- [ ] AC-3: `nodes.py` actively employs both decorators on the `implementer_node`. — verified by static source inspection and `pytest -k test_langgraph_nodes_authority_active`
      · stage: `make test-langgraph` (R-DECOR-3)

## Steps

1. Modify `harness/shared/langgraph/decorators.py` — produces fail-closed exception paths instead of passing execution through on error.
2. Modify `harness/shared/langgraph/nodes.py` — consumes the hardened decorators; produces live authority enforcement on nodes.
3. Modify `harness/shared/tests/test_langgraph_decorators.py` — produces regression tests pinning the fail-closed behavior.

## Files touched

- `harness/shared/langgraph/decorators.py`
- `harness/shared/langgraph/nodes.py`
- `harness/shared/tests/test_langgraph_decorators.py`

## Invariants touched

- INV-10: Preserved by ensuring missing policy/authority results in immediate execution denial (failing closed).
- INV-LG-3: Preserved by routing the decorator-raised exceptions into the `errors` state channel.
- INV-LG-4: Activated. The decorators will now actively enforce role and budget constraints on the topology nodes.

## Validation matrix

- `make test-langgraph`
- `make ci`
- coverage target: >90% from `governance-policy.json → coverage.lines`

## Backward compatibility

This is an internal architectural tightening. Since the orchestrator currently executes these nodes without restrictions, this introduces new failure paths (policy denial). The `errors` channel routing ensures backwards compatibility with the StateGraph execution loop.

## Open questions

- None.
