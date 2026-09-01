# Specification: LATS Optimization

**Version:** 2.2.0

**Status:** Draft

## 1. Overview

The `lats-optimization` module implements Language Agent Tree Search (LATS) to enhance the reasoning capabilities of the planner agent.

## Requirements

- Implement Monte Carlo Tree Search (MCTS) for planning.
- Ensure StateGraph immutability during simulation rollouts.
- Adhere to the `AblationChannel` isolation requirements to prevent state leakage.

## Acceptance criteria

- `lats_optimizer.py` implements UCB1 and node expansion, verified by `make test`.
- `ablation.py` provides an `AblationChannel` that applies diffs without mutating the base `MangoState`, verified by `pytest -k test_ablation_channel_isolated_diff`.
- State leakage during ablation is denied by deep-copy isolation, verifiable by `pytest -k test_ablation_leak_denial`.
- `vitest` and `pytest` CI gates remain green.

## 2. Architecture

LATS is delivered as standalone scaffolding in this release; end-to-end wiring into the `StateGraph` is tracked as a follow-up.

- **Standalone Modules**: `lats_optimizer.py` and `ablation.py` implement the full MCTS algorithm and isolated rollout channel. `planner_node` integration is deferred.
- **State Immutability**: All hypothetical trajectories are tracked in an `AblationChannel` without altering the primary execution state via deep-copy isolation (INV-LG-5).

## 3. Deployment

Requires updating the `governance-policy.json` to enable LATS features for the reasoning agent.
