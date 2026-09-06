# Gap + peer review: context-window budget (H4) — 2026-09-06

**Subject:** PR #110 · branch `spec/context-window-budget` · tip reviewed `d43a5ef` (+ follow-up fix commits on this review)
**Baseline:** `origin/main` @ `d1e13c5`
**Spec / plan:** `docs/specs/context-window-budget.md` · `docs/reports/PLAYLIST-ASTRA-CONTEXT-BUDGET-PLAN-2026-09-06.md`
**Method:** ensemble lenses — Architect, Sr SWE, SQE, Security/Governance, Product — against `git diff origin/main...HEAD` focused on H4 only.
**Scope:** context-window budget implementation, closely related docs/tests/policy wiring. Unrelated refactors out of scope unless blocking.

---

## Thesis

The branch delivers the right H4 shape: a **pure** `context_policy` module, **policy-keyed** budgets via fail-closed `orchestrator_defaults`, **group-atomic** eviction wired on a **copy** before `complete_chat`, full `conversation_history` retained, structured `event=context_policy` logging, and DEC-003 dormancy preserved. Unit + regression pins cover the core survival contract. With the CI blockers closed in this review, the change is mergeable once required checks and `infra-reviewed` attestation land.

## Counter-argument

1. Tip `d43a5ef` CI was **red**: OpenSpec `ORPHAN_REQUIREMENT` (C-CW-2, C-CW-3, R-CW-4), a complete-but-stale GraphPolicy liveness fixture missing the new orchestrator keys (fail-closed `PolicyError`), and `test_tool_run_command_success` still assuming `complete_chat` receives the **same mutable** `conversation_history` object (broken by the intentional budgeted copy).
2. Eviction is O(groups × estimate rescans); message copies are **shallow** (nested `tool_calls` still aliased).
3. Audit doc `2026-STANDARDS-AUDIT.md` still narrates H4 as open; problem-statement text in the OpenSpec still says H4 remains open while NEXT_STEPS marks it landing.
4. Edge negatives (empty history, budget `0`, incomplete tool groups) behave reasonably when probed but lack dedicated pytest pins.
5. `event=context_policy` is emitted at **DEBUG** only — easy to miss under default INFO gates.

## Rebuttal

1. All three CI failures are **in-scope, deterministic, and fixed** in small commits on this review (citations + fixture keys + call-time assertion). They do not invalidate the design.
2. Histories at the shipped 128k default almost never enter the eviction loop; O(n²) is acceptable for v1. Shallow copy matches typical immutable provider payloads; deepening can be a follow-up if a client mutates nested structures.
3. Audit/spec problem-statement lag is documentation hygiene, not a runtime defect; NEXT_STEPS / C4 / CHANGELOG / tree indexes already reflect H4.
4. Probed behaviour: empty → no-op; budget `0` evicts all groups and keeps non-group messages with consistent links; incomplete groups are identified as partial units and are not “repaired” (out of v1 scope per OpenSpec open questions).
5. Structured `extra=` fields are first-class in `JSONFormatter`; DEBUG is consistent with other loop budget resolution logs. Raising to INFO on non-zero eviction would be a nice follow-up, not a merge blocker.

---

## Verified checks

| Check | Result | Evidence |
|---|---|---|
| Tip SHA expected ~`d43a5ef` | Pass (pre-fix) | `git rev-parse HEAD` → `d43a5efde985c888fdab5abb3197dbc287bb80a2` |
| Diff scope H4-focused | Pass | 16 files; +~841/−22 vs `origin/main` — policy, `context_policy`, loop wiring, tests, docs |
| OpenSpec vs implementation | Pass (after citation fix) | ACs AC-CW-1…AC-CW-7 map to tests; orphans cleared via `plan_rules.check_plan` |
| Policy keys + artifact | Pass | `governance-policy.json` + `policy-artifact.json` regen; loader TypedDict extended |
| No hard-coded budget in `loop.py` | Pass | `test_loop_has_no_hardcoded_context_budget`; literals only in policy / defaults |
| Group-atomic eviction | Pass | unit + `test_context_window_budget_regression` |
| Stale `usage.prompt_tokens` must not skip eviction | Pass | `test_stale_provider_usage_must_not_skip_eviction_of_grown_history` |
| Fail-closed missing keys | Pass | dedicated PolicyError tests; GraphPolicy liveness fixture completed |
| DEC-003 dormancy | Pass | `test_mango_hooks_stay_dormant`; no `.claude/settings.json` mirroring; no GoalCard |
| New third-party deps | Pass (none) | empty diff on `requirements*.txt` / `pyproject.toml` / dependabot |
| Docs: NEXT_STEPS, C4, CHANGELOG, READMEs | Pass | H4 reflected; HITL remains parked |
| `ruff check` / `ruff format --check` (touched) | Pass (post-fix) | local on touched paths |
| `mypy` touched modules | Pass | `context_policy.py`, `loop.py`, `policy_loader.py` |
| pytest H4 + regression + docs/plan gates + dormant | Pass (post-fix) | see command list below |
| `gh pr checks 110` at tip `d43a5ef` | **Fail → re-run after push** | prior run: orphan plan + langgraph fixture + mango MAS assert |

### Local commands re-run this review

```text
ruff check/format --check (touched paths)
mypy harness/shared/context_policy.py harness/shared/orchestrator/loop.py harness/shared/policy_loader.py
pytest harness/shared/tests/test_context_policy.py \
       harness/shared/tests/regression/test_context_window_budget_regression.py \
       harness/shared/tests/test_mango_mas_tools.py::test_tool_run_command_success \
       harness/shared/tests/test_langgraph_policy.py::TestGraphPolicyFailClosed::test_distinguishable_value_actually_flows_through
pytest harness/shared/tests/test_validate_plan.py::TestTheRepositoryPasses::test_the_real_gate_is_green \
       harness/shared/tests/test_validate_specs.py::TestRepositorySpecsAreConforming::test_the_real_spec_directory_passes \
       harness/shared/tests/test_documentation_claims.py
pytest harness/shared/tests/test_agent_surface_liveness.py -k dormant
```

---

## Findings

| ID | Severity | Persona | Evidence | Recommendation |
|---|---|---|---|---|
| F1 | **Blocker** (fixed) | SQE / SDLC | CI: `ORPHAN_REQUIREMENT` for C-CW-2, C-CW-3, R-CW-4 in `docs/specs/context-window-budget.md` | Cite IDs from ACs / validation matrix — **done** (AC-CW-5 expanded; AC-CW-7 + matrix rows for R-CW-4) |
| F2 | **Blocker** (fixed) | Sr SWE / Security | `test_distinguishable_value_actually_flows_through` fixture omitted new orchestrator keys → `PolicyError` under R-CQ-8 fail-closed | Complete fixture with distinguishable `context_budget_tokens` / `context_chars_per_token` — **done** |
| F3 | **Blocker** (fixed) | SQE | `test_tool_run_command_success` asserted `messages[-2]==tool` relying on post-call mutation of shared `conversation_history`; budgeted **copy** correctly ends with `tool` at call time | Assert call-time tool result (`messages[-1]` / filter by role) — **done** |
| F4 | **Major** | Security / Governance | PR touches protected paths (`governance-policy.json`, `policy_loader.py`, `loop.py`); labels empty at review time; merge requires `infra-reviewed` + attestation table match (INV-6 / DEC-038) | Human: ensure PR description attestation table matches `make attestation-check`; apply `infra-reviewed` after CI green |
| F5 | **Minor** | Sr SWE | `apply_context_policy` uses `[dict(m) for m in history]` — **shallow**; nested `tool_calls` / dict values remain aliased (`meta` mutation probe leaked) | OK for v1 if clients treat messages as read-only; follow-up: `copy.deepcopy` for tool_calls or freeze | 
| F6 | **Minor** | Architect / Sr SWE | Eviction loop re-runs `identify_tool_call_groups` + full `estimate_tokens` each drop → O(G · N) | Accept for v1; optional: maintain running char totals / drop by index set without full rescan |
| F7 | **Minor** | SQE | No dedicated tests for empty history, `budget_tokens=0`, incomplete multi-tool groups (behaviour probed manually OK) | Add small negative unit cases in a follow-up; not blocking given AC coverage of primary paths |
| F8 | **Minor** | Product / Docs | `2026-STANDARDS-AUDIT.md` H4 row still open; OpenSpec problem statement still says H4 open while NEXT_STEPS §6 marks landing | After merge: mark H4 remediated in audit (or link PR #110); soften problem-statement tense |
| F9 | **Minor** | Sr SWE / Ops | `event=context_policy` logged at DEBUG only | Consider INFO when `messages_evicted > 0` for production observability |
| F10 | **Note** | Architect | `loop.py` grew ~28 net lines (now ~359) but eviction logic lives in `context_policy.py` — avoids god-file growth of the algorithm itself | Keep algorithm out of the loop; no further split required for v1 |
| F11 | **Note** | Security | Constructor now **always** calls `orchestrator_defaults(policy_path)` (even when iteration/timeout overridden) so context keys resolve — correct fail-closed; any present incomplete fixture policy must list the new keys | Document in contributor notes; fixture pattern already used in `test_context_policy` |
| F12 | **Note** | Product | Default 128000 means short runs unchanged; over-budget only under explicit low budgets in tests — matches C-CW-4 | Keep; do not lower default without a product decision |

---

## Explicit merge gate

### Must fix before merge

1. ~~F1–F3 CI blockers~~ — fixed on this review; push must leave `build` / `build-full` green.
2. **F4** — protected-path attestation + `infra-reviewed` label (human/process).
3. No DEC-003 wake-ups, no GoalCard, no new runtime deps (already held).

### OK to leave (post-merge / follow-up)

- F5 shallow copy, F6 eviction cost, F7 extra negatives, F8 audit wording, F9 INFO-on-evict.
- OpenSpec open questions: per-role handoff seeding; content-level truncation inside a single oversized tool payload.

---

## Skills / agents / hooks / loops — opportunities (observation only)

**Do not implement wake-ups (DEC-003 / C-CW-1).**

| Surface | Observation | Opportunity (future, gated) |
|---|---|---|
| `.mango/hooks/*` | Still dormant; loop still uses existing `HookRunner` pre/post agent hooks only | Optional later: a **non-mirrored** debug hook that records `context_policy` stats to run dumps — only with an explicit revival DEC |
| `.mango/skills/*` | Untouched | Optional skill doc: “how to tune `context_budget_tokens`” for operators — docs-only, not a GoalCard |
| Agents (`planner` / `reasoner` / `verifier`) | Shared history still cross-role; eviction is global oldest-group | Optional: per-role handoff seed (plan optional R-CW-6) under a new OpenSpec |
| `ExecutionLoop` | Budget wired on every `complete_chat` | Done for H4; future: surface `ctx_stats` on dump/API |
| LangGraph / HITL | PARK (DEC-053); not woken | Keep parked; HITL remains separate parked item in NEXT_STEPS |
| Compact / PreCompact | `save_state_before_compact.sh` still git-status oriented | Do **not** extend to model scratch / NOTES.md (C-CW-3) |

---

## Persona roll-up

| Persona | Verdict | One-line |
|---|---|---|
| Architect | **Approve** (after F1–F3) | Plane-B policy eviction; DEC-003/053 respected; algorithm extracted |
| Sr SWE | **Approve** (after F1–F3) | Pure module + fail-closed keys; shallow copy / O(n²) acceptable v1 debt |
| SQE | **Approve** (after F1–F3) | ACs falsifiable; regression tier pin present; add edge negatives later |
| Security / Governance | **Conditional Approve** | Runtime OK; merge blocked on `infra-reviewed` + green CI only |
| Product | **Approve** | Ships as reliability (H4), not a new skill/KPI surface |

---

## Diff inventory (review scope)

`context_policy.py` (new), `loop.py` wiring, `policy_loader.py` + `governance-policy.json` + `policy-artifact.json`, `test_context_policy.py`, regression pin + tier pin, docs (`context-window-budget.md`, brief peer review, NEXT_STEPS, C4, CHANGELOG, README trees). No dependency or Dependabot changes.
