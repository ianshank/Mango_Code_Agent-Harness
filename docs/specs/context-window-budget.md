# Spec: context-window budget (audit H4)

> **Programme:** 2026 standards audit H4 / remediation Phase F context budget.
> **Status:** Approved for implementation in this PR train (peer review documented below).
> **Protected-path status:** touches `governance-policy.json`, `policy_loader.py`,
> and `orchestrator/loop.py` — `infra-reviewed` attestation required.
> **Provenance:** ensemble plan in
> `docs/reports/PLAYLIST-ASTRA-CONTEXT-BUDGET-PLAN-2026-09-06.md` (PR #109 /
> branch `docs/playlist-astra-context-budget-plan-2026-09-06`); peer sign-off
> recorded in `## Peer review`.
> **Base:** `origin/main` @ `29fb154`.

## Problem statement

`ExecutionLoop` keeps one append-only `conversation_history` across
planner → reasoner → verifier. Each `execute_agent` extends system+user and
appends every turn; provider `usage.prompt_tokens` is **logged** in
`_log_model_call` and **never** used to bound or evict context. Bounds remain
iteration count, tool-call budget, and per-tool byte caps — not tokens.

Evidence (re-verified on tip `29fb154`):

- `harness/shared/orchestrator/loop.py` — `execute_agent` passes
  `self.conversation_history` wholesale to `complete_chat_fn`.
- `_log_model_call` records `prompt_tokens` / `completion_tokens` only.
- Audit H4 in `docs/reports/2026-STANDARDS-AUDIT.md` remains open; remediation
  Phase F still lists context budget separately from HITL (H5).

Without a policy-keyed budget, long runs can exceed the model context window
while still “succeeding” under iteration/tool budgets, and naive truncation
risks orphaning `role:tool` messages or leaving `tool_calls` without results.

## Requirements

- R-CW-1: Policy MUST declare `orchestrator.context_budget_tokens` (int) and
  `orchestrator.context_chars_per_token` (number); both MUST load via
  `policy_loader.orchestrator_defaults` with the same fail-closed /
  absent-file-defaults semantics as other orchestrator keys. Application
  modules MUST NOT hard-code budget literals.
- R-CW-2: Before each `complete_chat` / `complete_chat_fn` call inside
  `ExecutionLoop.execute_agent`, the **model-facing** message list MUST be the
  result of `apply_context_policy` on a copy of `conversation_history`.
  `self.conversation_history` MUST remain the full append-only log for dumps
  and API responses.
- R-CW-3: Eviction MUST be atomic over tool-call groups: an `assistant` message
  with `tool_calls` and its matching `role:tool` messages (same
  `tool_call_id` / `id`) are kept or dropped together. Surviving history MUST
  never orphan a tool result and MUST never leave `tool_calls` without matching
  results.
- R-CW-4: Token measurement MUST prefer `usage.prompt_tokens` when the caller
  supplies a usage mapping containing that key; otherwise MUST estimate with
  `context_chars_per_token` from policy (UTF-8 character length / coefficient),
  never a magic number in `loop.py`.
- R-CW-5: Every apply MUST emit a structured log with `event=context_policy`
  and `run_id`, plus `tokens_before`, `tokens_after`, `groups_preserved`, and
  `messages_evicted`.
- R-CW-6: Eviction MUST prefer the oldest completed tool-call groups (and may
  drop oversized tool groups under budget pressure) while preserving group
  atomicity. Non-group messages (system / user / plain assistant) are not
  primary eviction targets in v1.
- C-CW-1: MUST NOT wake DEC-003 `.mango` lifecycle hooks or mirror them into
  `.claude/settings.json`.
- C-CW-2: MUST NOT add GoalCard / `/go` skill surfaces, GBrain, Qdrant,
  playlist indexes, ARC KPIs, or LangGraph HITL / interrupts.
- C-CW-3: MUST NOT persist model scratch to `NOTES.md` or untracked repo-root
  paths; MUST NOT weaken broker / write_policy / CONTRACT invariants.
- C-CW-4: Default `context_budget_tokens` MUST be generous enough that existing
  short unit-test histories do not evict under the shipped policy (documented
  default: **128000** tokens). Over-budget behaviour MUST still be tested with
  an explicit low budget in fixtures.

## Acceptance criteria

- [x] AC-CW-1: Under a fixture history with ≥1 tool-call group and oversized
      tool payloads and an explicit low budget, estimated (or usage-reported)
      size after policy is ≤ budget **or** no further evictable tool groups
      remain; every surviving `tool_calls[].id` has a matching tool result —
      verified by
      `pytest harness/shared/tests/test_context_policy.py -k test_context_policy_evicts_oldest_tool_results_under_budget`
      · stage: `make test-python` (R-CW-3, R-CW-6, C-CW-4)
- [x] AC-CW-2: A dedicated test fails if group-preservation is bypassed
      (orphaned tool result or tool_calls without results) —
      verified by
      `pytest harness/shared/tests/test_context_policy.py -k test_context_policy_preserves_tool_call_groups`
      · stage: `make test-python` (R-CW-3)
- [x] AC-CW-3: `execute_agent` passes the budgeted list to `complete_chat`
      while retaining fuller history on the loop for dump/API —
      verified by
      `pytest harness/shared/tests/test_context_policy.py -k test_execute_agent_passes_budgeted_messages_to_complete_chat`
      · stage: `make test-python` (R-CW-2, R-CW-5)
- [x] AC-CW-4: Missing `orchestrator.context_budget_tokens` (or
      `context_chars_per_token`) on a **present** policy fails closed with
      `PolicyError`; an **absent** policy file yields the built-in defaults
      that mirror the shipped block —
      verified by
      `pytest harness/shared/tests/test_context_policy.py -k "test_context_budget_policy_defaults or test_present_policy_missing_context_budget_fails_closed or test_present_policy_missing_chars_per_token_fails_closed"`
      · stage: `make test-python` (R-CW-1)
- [x] AC-CW-5: DEC-003 dormancy remains green —
      verified by
      `pytest harness/shared/tests/test_agent_surface_liveness.py -k test_mango_hooks_stay_dormant`
      · stage: `make test-python` (C-CW-1)
- [x] AC-CW-6: No hard-coded context budget literal appears in
      `harness/shared/orchestrator/loop.py` —
      verified by
      `pytest harness/shared/tests/test_context_policy.py -k test_loop_has_no_hardcoded_context_budget`
      · stage: `make test-python` (R-CW-1, C-CW-4)

At least one criterion (AC-CW-2 / AC-CW-4) names a non-success outcome:
orphaning tool groups fails the suite; a present policy that dropped the new
keys fails closed rather than silently substituting.

## Steps

1. Land this OpenSpec — produces `docs/specs/context-window-budget.md`.
2. Add pure `harness/shared/context_policy.py` + unit tests — produces
   group-preserving eviction without importing the loop.
3. Add policy keys + `OrchestratorLimits` / `orchestrator_defaults` wiring;
   regenerate control-plane policy artifact / digests — produces loader +
   artifact drift green.
4. Wire `ExecutionLoop.execute_agent` to apply policy on a copy before
   `complete_chat_fn`; emit `event=context_policy` — produces H4 closure on
   the live path.
5. CHANGELOG `[Unreleased]` entry; attestation table for protected paths.

## Files touched

- `docs/specs/context-window-budget.md` (new)
- `docs/reports/CONTEXT-WINDOW-BUDGET-PEER-REVIEW-2026-09-06.md` (new, brief)
- `harness/shared/context_policy.py` (new)
- `harness/shared/tests/test_context_policy.py` (new)
- `harness/shared/governance-policy.json` (**protected**)
- `harness/shared/policy_loader.py` (**protected**)
- `harness/shared/orchestrator/loop.py` (**protected**)
- `harness/shared/tests/test_policy_loader.py`
- `harness/control-plane/policy-artifact.json` (regen)
- `harness/control-plane/policy-bundle.example.json` (regen if digests drift)
- `CHANGELOG.md`

## Invariants touched

- INV-6 (protected paths): engaged — attestation required for policy / loop /
  loader edits.
- INV-7 / broker / write_policy: unaffected — eviction is message-list shaping
  only; it does not change tool exposure or grades.
- DEC-003 dormancy: preserved (C-CW-1); pinned by AC-CW-5.

## Validation matrix

- `pytest harness/shared/tests/test_context_policy.py -q`
- `pytest harness/shared/tests/test_policy_loader.py -q`
- `pytest harness/shared/tests/test_agent_surface_liveness.py -k dormant -q`
- `pytest harness/shared/tests/test_policy_consistency.py -k orchestrator -q`
- `make digest-regen` (no unexpected drift after artifact regen)
- coverage target: from `governance-policy.json → coverage.lines`

## Backward compatibility

- Shipped default `context_budget_tokens=128000` is high enough that existing
  short histories and unit tests that do not set a low budget are unchanged
  in observed eviction behaviour.
- `conversation_history` remains append-only and complete for dumps / HTTP.
- Absent policy file: built-in defaults match the committed orchestrator block
  (same contract as other orchestrator keys).
- Present policy missing the new keys: `PolicyError` (fail closed), matching
  R-CQ-8.

## Peer review

Brief `openspec-peer-review` matrix (aligned with the 2026-09-06 ensemble plan):

| Persona | Verdict | Notes |
|---|---|---|
| Architect | Approve | Budget on Nemotron `ExecutionLoop` plane B only; leave Claude `.mango` hooks asleep (DEC-003); no LangGraph revival (DEC-053). |
| SDLC / CI | Approve | Policy-keyed thresholds; attestation for protected paths; small PR train; digest/artifact regen. |
| QA | Approve | Falsifiable ACs with named pytest selectors; group atomicity mutation pin; dormancy pin. |
| Product | Approve | Reliability / H4 closure — not GoalCard, ARC KPIs, or playlist RAG productization. |
| Security / Governance | Approve | No hook wake; no NOTES.md; untrusted tool output remains data; eviction must not invent a new authority path. |

Detail: `docs/reports/CONTEXT-WINDOW-BUDGET-PEER-REVIEW-2026-09-06.md`.

## Open questions

- None blocking v1. Optional later: per-role handoff seeding (plan R-CW-6
  optional) and content-level truncation inside an oversized single tool
  payload while keeping ids — out of scope for this PR.
