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

The four canonical roles not bound to an active Mango role
(`security-reviewer`, `peer-reviewer`, `release-auditor`, `spec-analyst`) are
exercised by the `verifier` step and by the mandatory pre-PR review skills
(`openspec-peer-review`, `repo-invariant-review`). External write / production
changes routed through `release-auditor` always require human approval.
