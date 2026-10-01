# MG-E1 Experiment Plan: Explicit No-Model

> **Package:** Mango soft-P1 / MG-E1
> **Ticket:** SWE-ReX + OpenSandbox adapter pack
> **Architecture:** `docs/architecture/mg-e1-swe-rex-opensandbox.md` (PR #142)
> **Status:** NO_MODEL (Critic-binding)
> **Author:** Experimenter (Delivery Board)

## Decision

**No model.** MG-E1 is adapter infrastructure only: additive `ExecutionBackend`
implementations (`SweRexBackend`, `OpenSandboxBackend`) and additive
`BackendCapabilities.filesystem_isolation` behind a preserved `ExecutionBroker`.
There is no training run, fine-tune, prompt-model experiment, or offline ML
metric target in this milestone.

## Required fields (N/A)

| Field | Value |
|---|---|
| Target (product / model metric) | N/A — software packaging; not an ML change |
| Baseline | N/A — no model scoreboard; ProcessBackend default behaviour is the engineering baseline (see architecture section 10 tests) |
| Leakage | N/A — no train/eval split, no labeled dataset, no feature store |
| Kill-criteria | **N/A by design.** Explicit NO_MODEL so Critic must not HOLD for missing kill-criteria on this ticket |
| Dataset / Data Steward | No new datasets expected; no schema drift from adapter packaging (Data Steward to confirm) |
| Model IDs | None. Config remains env-injected; adapters must not hardcode model identifiers |

## Why this is not an ML ticket

1. Scope is optional runtime adapters and fail-closed isolation evidence (R-AEI-10).
2. Default execution path stays `ProcessBackend` (containment, not a learned policy).
3. Soft-P1 constraints forbid Distilled / Neuroharness / FORGE and any model train in MG-E1.
4. Success is Critic design SHIP + Implementer tests (capability mapping, fail-closed enforced claims), not a model lift.

## Critic gate note

Treat this file as the shared-state `experiment_plan.md` artifact for MG-E1.
Missing kill-criteria is **not** a hold when `decision == NO_MODEL` and the
architecture non-goals exclude ML. Escalate only if scope creeps into training,
benchmarks that require a model, or Distilled/Neuroharness packs (MG-E4).

## Handoff

- Remain idle on ML Eval / experiment iteration until a later milestone names a
  real model target.
- Data Steward: confirm no schema or dataset contract change from this PR train.
- ML Eval: no `eval_decision.json` product-metric scoring required for MG-E1
  beyond software Critic / Tester gates.
