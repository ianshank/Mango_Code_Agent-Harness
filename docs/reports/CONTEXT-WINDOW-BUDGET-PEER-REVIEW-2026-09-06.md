# Peer review: context-window budget (H4) — 2026-09-06

**Spec:** `docs/specs/context-window-budget.md`
**Plan:** ensemble report `PLAYLIST-ASTRA-CONTEXT-BUDGET-PLAN-2026-09-06.md`
**Method:** `openspec-peer-review` personas (Architect, SDLC/CI, QA, Product) plus
Security/Governance notes from the ensemble plan.

## Sign-off

| Persona | Decision | One-line rationale |
|---|---|---|
| Architect | **Approve** | Plane-B eviction on `ExecutionLoop`; DEC-003 / DEC-053 untouched. |
| SDLC / CI Lead | **Approve** | Policy SoT + attestation + digest regen; no CI threshold invention. |
| QA Director | **Approve** | Group-atomicity and dormancy pins are falsifiable. |
| Product Manager | **Approve** | Ships as reliability (H4), not a new skill/persona/KPI surface. |
| Security / Governance | **Approve** | No hook mirroring; no scratch files; no broker/write_policy weaken. |

## Rejects retained

Wake `.mango` hooks, GoalCard, GBrain/Qdrant runtime deps, ARC % gates,
LangGraph HITL in this train — all rejected per plan Phase 4.

## Implementation gate

Approved to implement in the same PR train as the spec, provided ACs
AC-CW-1…AC-CW-6 collect and pass.
