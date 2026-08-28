# Mango agent roles

This directory holds the **active** agent definitions invoked by
`mango_mas_orchestrator.execute_agent()` in the planner → reasoner → verifier loop.
They are the executed three-role loop; the canonical role taxonomy lives in
`harness/shared/agents/` (mirroring `shared/agent-policy.json`) and is the
authoritative reference for responsibilities and evidence obligations.

These two sets are reconciled by the mapping below — no role is silently
re-defined. When a canonical contract changes, update the mapped active role
here (and its test) in the same change.

## Authoritative mapping

| Active Mango role | Canonical contract(s) | Responsibility in the loop |
|---|---|---|
| `planner` | `spec-analyst.md`, `orchestrator.md` | Requirements + acceptance criteria; plans and delegates only, never edits code. |
| `nemotron-reasoner` | `implementer.md` | Scoped code/config edits and local tests via the tool bridge; uses `knowledge_gap_log` / `hypothesis_register` meta-tools instead of hallucinating. |
| `verifier` | `test-eval.md`, `peer-reviewer.md`, `security-reviewer.md`, `release-auditor.md` | Test/eval execution + evidence; independent correctness/conformance review; blocks releases failing gates. |

All seven canonical roles are bound by the table above. The mapping is
machine-readable in `harness/shared/agent_authority.ACTIVE_TO_CANONICAL`, which
derives each active role's tool exposure from `agent-policy.json`; this table
and that constant must stay in step, and `test_agent_authority.py` pins the
derivation.

**Derived exposure.** A role's effective actions are the union of its canonical
contracts' `allowed_actions`, **minus** each contract's
`human_approval_required_for` — so `release-auditor`'s approval-gated
`external_write` and `production_change` do not reach the verifier.

| Active role | Effective actions | Tools received |
|---|---|---|
| `planner` | `read`, `plan`, `delegate`, `spec_write` | `knowledge_gap_log`, `hypothesis_register` |
| `nemotron-reasoner` | `read`, `write`, `test_execute` | `write_file`, `run_command`, both meta-tools |
| `verifier` | `read`, `test_execute`, `evidence_write`, `review_write`, `security_scan` | `run_command`, both meta-tools — **no `write_file`** |

**Execution identity.** `EXECUTION_IDENTITY` records the canonical role each
active role *executes as* when the broker asks the authority model for a
verdict: `planner` → `orchestrator`, `nemotron-reasoner` → `implementer`,
`verifier` → `test-eval`. That is deliberately the narrowest covering contract
rather than the union, and the active roles are not themselves declared in
`agent-policy.json`, because declaring them would give the agent's own governing
policy an execution grant (DEC-011). An active role absent from
`EXECUTION_IDENTITY` cannot execute any command.
