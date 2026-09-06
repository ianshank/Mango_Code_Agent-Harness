# Playlist / Astra → Mango context-budget program plan (2026-09-06)

**Reviewed artefacts:** Grok share
[YouTube Playlist Data Analysis](https://grok.com/share/c2hhcmQtMi1jb3B5_2829b07c-d644-43e2-a656-00670f484267);
ingested talks (Gaspar *Agentic Loops for Knowledge Workers*; Welch Labs ResNet;
Prompt Engineering *GPT-6 Astra / harness*); live `Mango_Code_Agent-Harness`
evidence on `main` @ `29fb154` (post NS-34 / PR #101).
**Method:** ensemble of SDLC agents — Product, Architect, Sr SWE, SQE,
Security/Governance, Engineering Manager — with thesis / counter / rebuttal
and DEC-024-style re-runnable evidence.
**Outcome:** adopt / reject / sequence plan. **Docs-only** for this report PR;
runtime work is Phase 1–2 below under OpenSpec discipline.

---

## Thesis

The highest-ROI *technical* residue of the playlist corpus and the three talks,
for this repository, is a **policy-keyed context-window budget on the live
Nemotron `ExecutionLoop`** (2026 standards audit **H4**), with tests that
**tool-call groups survive eviction**. It is *not* waking Claude `.mango`
lifecycle hooks (DEC-003), *not* a new GoalCard skill, *not* ARC-AGI 62.7% /
99.9% KPIs, and *not* GBrain / Qdrant as runtime dependencies. LangGraph remains
**PARK** (DEC-053). Owner P0s **NS-1 / NS-2 / NS-3 / NS-30** stay first in
priority and are out of agent scope.

## Counter-argument

1. Context budget sits in remediation **Phase F** slack next to HITL and
   provider boundaries — implementing it now invents priority ahead of owner
   gates and Phase E.
2. B3 (typed history), M1 (single `ToolBudget`), and H6 (`run_id`) already
   landed; H4 may be stale or low urgency.
3. Astra’s dual-harness story argues for waking the dormant “adopter” path
   (compact / checklist / LangGraph) and measuring A/B, not a quiet eviction
   helper.

## Rebuttal

1. Phase F is an *ordering* in the remediation plan, not a claim that H4 is
   false. This plan does **not** displace NS-1/2/3/30; it names the first
   *agent-executable* harness-quality slice once owners unblock (or in
   parallel as a non-destructive PR train).
2. Re-read on `main` @ `29fb154`: `ExecutionLoop` still keeps **one**
   `conversation_history` across planner → reasoner → verifier; each
   `execute_agent` extends system+user and appends every turn; `usage` /
   `prompt_tokens` are **logged** and **not** used to evict. Bounds remain
   iteration count, tool-call budget, and per-tool byte caps — not tokens.
   H4 is live.
3. Dual-harness A/B that mirrors `.mango` hooks into `.claude/settings.json`
   reverses DEC-003 and DEC-021 (“never wire logic into a dormant hook”).
   `save_state_before_compact.sh` checkpoints **git status/diff** under
   `.mango/.state/`, not model scratch — extending it recreates the rejected
   `NOTES.md` pattern (`docs/specs/agent-surface.md`). ARC wrapper percentages
   are not Mango acceptance criteria.

---

## Ensemble findings

### Product Manager

**Value.** Adopters experience “model × harness,” not model alone. A budgeted
loop that keeps tool evidence coherent is the product story Astra sells without
importing Astra’s marketing numbers.

**Do not productize:** playlist RAG as a default capability; GBrain sidecar;
GoalCard UX; “99.9% harness” dashboards; residual-connection metaphors in
user-facing docs as if they were orchestration features.

**Positioning.** Ship as governance-quality / reliability (H4 closure), not as
a new agent persona or skill marketplace item.

### Architect

**Two planes (do not conflate):**

| Plane | Runtime | Today | Role in plan |
|---|---|---|---|
| A. Claude Code session | `.mango/hooks/*`, `PreCompact` | Dormant (DEC-003); not mirrored into `.claude/settings.json` | **Leave asleep** |
| B. Nemotron `ExecutionLoop` | Shared `conversation_history` ReAct loop | Live default path; H4 open | **Budget here** |

**Gaspar loop vs graph.** Stay in the while-loop until a *machine-checkable*
finish fails. Fan out to a graph only on rubber-stamp verification, context
overflow, parallelism, moving finish lines, or quality flatlines. With
DEC-053 PARK, overflow is handled by **eviction/handoff on plane B**, not by
reviving LangGraph.

**Welch Labs.** `y = x + F(x)` is neural optimization literacy (ablation /
gradient path). It is **not** a ReAct or LangGraph design principle. Keep it
out of orchestration code and out of this program’s APIs.

**Contracts between roles.** Prefer compact handoffs (plan text / code summary)
into the next role’s model-facing messages rather than replaying entire tool
transcripts — aligns with Gaspar “pass contracts, not full transcripts.”

### Sr SWE

**Touch surface (expected):**

- New pure module, e.g. `harness/shared/context_policy.py` —
  `apply_context_policy(history, budget, *, usage=None) -> list[dict]`
- `harness/shared/policy_loader.py` + `governance-policy.json` —
  `orchestrator.context_budget_tokens` (and optional per-role ceilings); **no
  literals in `loop.py`**
- `harness/shared/orchestrator/loop.py` — apply policy on the **model-facing**
  message list before `complete_chat`; keep full history for debug dump if
  needed
- Control-plane policy artifact regen if that remains a protected contract
- Tests under `harness/shared/tests/`

**Invariant.** Eviction is atomic over tool-call groups: an `assistant` message
with `tool_calls` and its matching `role:tool` messages (same ids) are kept or
dropped together. Never orphan a `tool` turn; never leave `tool_calls` without
results the provider schema expects.

**Hypothesis (non-binding):** per-role handoff (fresh system + summarized prior
role output) plus tool-result eviction is simpler than one global sliding
window; verify in the OpenSpec.

### SQE

**Falsifiable acceptance (minimum):**

1. Fixture history with ≥1 tool-call group and oversized tool payloads:
   after policy, estimated or reported prompt size ≤ budget **and** every
   surviving `tool_calls[].id` has a matching tool result.
2. Deleting / bypassing the group-preservation branch fails a dedicated test
   (mutation-style pin).
3. Missing policy key fails closed **or** resolves through
   `orchestrator_defaults` exactly as other orchestrator limits do today —
   pick one in the spec and pin it.
4. `test_mango_hooks_stay_dormant` and agent-surface liveness remain green
   (no accidental `.claude` mirroring).

**First three tests to write:**

1. `test_context_policy_preserves_tool_call_groups`
2. `test_context_policy_evicts_oldest_tool_results_under_budget`
3. `test_execute_agent_passes_budgeted_messages_to_complete_chat` (mock captures
   kwargs; debug dump may still see fuller history)

**Out of scope for this program’s CI:** live NIM evals, ARC harness A/B,
playlist embedding quality.

### Security / Governance

- **DEC-003** stands: do not wake PreToolUse / Stop / PreCompact / SessionStart
  mango lifecycle hooks as a side effect of this work.
- Playlist RRF / caption KB / GBrain stay on the **observation plane** —
  default-off, cannot change tool exposure, broker grades, or policy.
- If `loop.py` / `governance-policy.json` remain protected paths, the
  implementation PRs need attestation tables and `infra-reviewed` per
  `harness/CONTRACT.md`.
- Do not reintroduce `NOTES.md` or untracked scratch at repo root.
- Untrusted tool output remains data (M19); eviction must not become a channel
  to drop denial records the verifier needed — prefer summarizing denials over
  deleting them when under budget pressure (call out in OpenSpec).

### Engineering Manager

**Sequence:**

| Phase | Who | What | Exit |
|---|---|---|---|
| 0 | Owner | NS-1 ruleset, NS-2 credential purge, NS-3 tag, NS-30 licence | API / tag / LICENSE evidence |
| 1 | Agent | OpenSpec `context-window-budget` + peer review | Spec approved |
| 2a | Agent | Pure `context_policy` + unit tests | Green PR |
| 2b | Agent | Wire `ExecutionLoop` + mock integration test | Green PR; H4 AC met |
| 2c | Agent | Policy keys + artifact regen if required | Green PR |
| 3 | Agent (later) | NS-18 reasoner↔bridge parity; optional default-off research MCP | Separate specs |
| 4 | — | Explicit rejects (below) | Not scheduled |

**PR slicing.** Prefer 2–3 small PRs over one mega-PR. Spec required before
behavior change (`make spec`, `openspec-peer-review`, `make pre-pr`).

**Does not block on:** LangGraph revival, HITL interrupts (H5), Phase E
destructive slices (still gated on NS-2).

---

## Verified evidence (re-run on tip)

| Check | Result (2026-09-06 pass) |
|---|---|
| `main` tip | `29fb154` (`feat(ns-34): decision records…` / #101) |
| DEC-003 dormancy | `.mango/settings.json` declares hooks; `.claude/settings.json` mirrors only SessionStart; `$comment` + `test_mango_hooks_stay_dormant` |
| PreCompact script | Writes git status/diff into `.mango/.state/precompact-checkpoint.md` only |
| H4 loop behavior | Single `conversation_history`; `execute_loop` runs planner→reasoner→verifier on same list; `prompt_tokens` logged in `_log_model_call`, not applied to eviction |
| Landed since audit rev-2 | M1 single task `ToolBudget`; H6 `run_id`; B3 `HistoryMessage` / `parse_history`; NS-17 memory retention; NS-21 post-run JSONL; NS-33 ruff format; NS-34 decision records; DEC-053 LangGraph PARK |
| Human P0s | NS-1 / NS-2 / NS-3 / NS-30 still owner-blocked per `NEXT_STEPS.md` |
| Phase F list | Remediation plan still names context budget (H4) and HITL (H5) as separate slack items |

Re-verify before implementation with: `git rev-parse origin/main`,
`pytest harness/shared/tests/test_agent_surface_liveness.py -k dormant`,
and a read of `execute_loop` / `_log_model_call`.

---

## Comprehensive plan

### Phase 0 — Owner (zero agent code)

Close **NS-1, NS-2, NS-3, NS-30**. This program must not claim readiness that
those gates deny (DEC-024). Phase 1–2 may proceed as non-destructive PRs in
parallel; Phase E / destructive work must not.

### Phase 1 — OpenSpec `context-window-budget`

**Maps to:** audit H4; remediation Phase F “context budget”; NEXT_STEPS parked
“Context-window budget / HITL interrupts” — **split HITL out**; this spec owns
budget only.

**Requirements (draft IDs):**

- **R-CW-1** Policy key(s) under `orchestrator` (e.g. `context_budget_tokens`);
  loaded via `policy_loader` / `orchestrator_defaults`; no hard-coded budgets
  in application modules.
- **R-CW-2** Before each `complete_chat`, model-facing messages pass through
  `apply_context_policy`.
- **R-CW-3** Tool-call group atomicity (keep/drop together by `tool_call_id`).
- **R-CW-4** Prefer provider `usage.prompt_tokens` when present; otherwise a
  documented estimate coefficient from policy (not a magic number in loop code).
- **R-CW-5** Structured log `event=context_policy` with `run_id`,
  tokens_before/after, groups_preserved, messages_evicted.
- **R-CW-6** (optional in v1) Per-role handoff seeding so verifier does not
  replay full reasoner tool dumps.

**Constraints:**

- **C-CW-1** Do not wake DEC-003 hooks or mirror them into `.claude/settings.json`.
- **C-CW-2** Do not add GoalCard / `/go` skill surfaces.
- **C-CW-3** Do not persist model scratch to `NOTES.md` or untracked roots.
- **C-CW-4** Do not implement LangGraph HITL / interrupts in this spec.
- **C-CW-5** Do not add GBrain, Qdrant, or playlist indexes as runtime deps.
- **C-CW-6** Do not cite Astra 62.7% / 99.9% as Mango KPIs or CI thresholds.

**Done when:** ACs in the SQE section pass on CI; H4’s “no token bound” claim
is false on the live path; dormancy tests still pass.

### Phase 2 — Implementation PR train

1. **2a** — Pure function + unit tests (no loop import side effects).
2. **2b** — Wire `ExecutionLoop`; integration test with mocked `complete_chat`.
3. **2c** — Policy JSON + loader + control-plane artifact if required; changelog
   under `[Unreleased]` per project norms.

Each PR: attestation if protected paths; `make pre-pr`; no hook-surface edits.

### Phase 3 — Adjacent (separate programs)

- **NS-18** — Reasoner persona ↔ bridge tool parity (harness decides what the
  model can call) — same Astra thesis, different surface; spec already
  scaffolded on #100.
- **Observation MCP** — default-off `search_playlist` / RRF over caption
  windows; never on the authority plane.
- **Caption crawl** — resume `core_agent_harness` split from a non-cloud IP;
  keep metadata-only cards out of evidence collections.

### Phase 4 — Explicit rejects (do not schedule)

- Wake PreCompact / Stop / PreToolUse mango hooks to “look like” Astra adopter
- New GoalCard duplicating verification + policy budgets
- ARC-AGI percentage dashboards or CI gates
- GBrain or vector DB inside the live ReAct authority path
- Residual-stream APIs in the orchestrator
- LangGraph KEEP revival without a DEC that supersedes DEC-053 / Memo 1 /
  R-SR-27
- Mixing HITL (H5) into the first context-budget PR

---

## Risks and open questions

| Risk / question | Mitigation |
|---|---|
| Char-estimate vs real tokenizer drift | Prefer `usage.prompt_tokens`; treat estimate as fail-safe upper bound; document coefficient in policy |
| Debug dump vs model-facing view | Keep full history for dumps; budget only the list passed to `complete_chat` |
| Interaction with 64 KiB tool output caps | Evict whole groups or truncate tool *content* under policy; never break ids |
| Protected-path / attestation overhead | Plan 2b/2c as separate PRs with tables |
| Priority fights with NS-18 | EM sequence: budget before or parallel to NS-18; do not merge scopes |
| Stale local clones | Always `git ls-remote` / hard-reset to `origin/main` before evidence claims |

---

## Success metrics (falsifiable)

- Under the SQE fixture: model-facing size ≤ policy budget; **zero** orphaned
  `tool_call_id`s.
- Existing suite green; DEC-003 dormancy tests green.
- Audit H4 remediation checkbox / remediation-plan AC (when filed) can be
  ticked with a named command, not prose.
- No new required dependency for vector search or GBrain on the primary path.

---

## Share residue map (what survived peer rewrite)

| Source claim | Disposition |
|---|---|
| Route-before-retrieve playlist RAG | Observation track only (Phase 3) |
| RRF hybrid search | Observation track only |
| GBrain durable memory | Not a Mango runtime dep |
| Gaspar: checkable finish, loop vs schedule, graph triggers | Design constraints for Phase 1–2; no `/go` |
| Welch: residual / shattered gradients | Literacy only |
| Astra: model × harness; compact vs truncate | **H4 context policy** on plane B |
| Dual-harness wake hooks | **Rejected** (DEC-003) |
| GoalCard | **Rejected** (duplicates governance) |

---

## References

- `docs/reports/2026-STANDARDS-AUDIT.md` — H4, H5, M1–M3, B3
- `docs/specs/2026-standards-remediation-plan.md` — Phase F context budget
- `docs/specs/agent-surface.md` — DEC-003 dormancy, PreCompact / NOTES rejection
- `NEXT_STEPS.md` — NS-1/2/3/30; parked context-window budget; DEC-053 PARK
- `harness/shared/orchestrator/loop.py` — live shared history path
- `.mango/hooks/save_state_before_compact.sh` — git-only checkpoint
- Grok share: playlist analysis → Mango mapping → final peer rewrite
