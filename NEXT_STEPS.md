# Roadmap & Next Steps: Agentic SSD & Nemotron AI Platform

**Version:** 2.4.0
**Status:** Active roadmap - forward-looking only
**Last reviewed:** 2026-09-05 · second peer rewrite against `main` @ `58490c1` (PRs #89-#95 / #93 DECs) · audit in [`docs/reports/2026-STANDARDS-AUDIT.md`](docs/reports/2026-STANDARDS-AUDIT.md) · program plan in [`docs/specs/2026-standards-remediation-plan.md`](docs/specs/2026-standards-remediation-plan.md) · peer review method in [`docs/reports/ROADMAP-PEER-REVIEW.md`](docs/reports/ROADMAP-PEER-REVIEW.md)

---

## How to read this file

This file is the single roadmap for the repository, and it contains **only work
that is not yet done**. Completed milestones through v2.4.0 live in
[`docs/releases/milestone-history.md`](docs/releases/milestone-history.md); the
narrative of what shipped lives in `CHANGELOG.md` and `docs/releases/`.

The roadmap does not own work that a program spec owns. The 2026 remediation
plan (`docs/specs/2026-standards-remediation-plan.md`, R-SR-1 … R-SR-31) carries
every audit finding and every open requirement of the closed
`code-quality-tech-debt-plan.md`; this file lists what is **blocked on a person**,
what an **agent can do without a decision**, and what is **parked** with its
blocker named. Status boxes live in the plan - do not restate them here.

Every item carries four fields, and an item without them is not ready to be
worked:

- **Why now** - the consequence of not doing it, not a restatement of the title.
- **Evidence** - a command, a file reference, or an API result a reviewer can
  re-run today. A claim in prose is not evidence (DEC-024).
- **Done when** - a falsifiable criterion bound to the stage that proves it, with
  the failure it must be able to report.
- **Depends on** - the item that must land first, or `nothing`.

Priorities are an ordering, not a schedule. **Spec discipline.** Items marked
*(spec required)* change behaviour, policy, or a protected path and must not be
implemented without `make spec NAME=<feature>`, the `openspec-peer-review`
skill, then `make pre-pr`.

### 2026-09-05 peer-rewrite findings (verified)

| ID | Severity | Finding | Effect on this file |
|---|---|---|---|
| PR-1 | **Blocker (doc)** | NS-32 said "Land Phase B (PR #86)" while the open roadmap still treated Phase B as unfinished. PR #86's title is `docs(reports): 2026 coding-standards audit`, but its body and 97-file diff landed Phase B (R-SR-6…R-SR-22 / AC-6…AC-22, AC-33 `[x]`); DEC-048…DEC-051 carry the containment/runtime narrative. | NS-32 closed → §6 Delivered; remediation plan bumped to rev 2 (Phase B Done). |
| PR-2 | **Blocker (product)** | Memo 1 / R-SR-27 still recommend PARK, and peer review drafts DEC-053 as park-after-fail-closed - but PR #87/#88 + DEC-052 invested in fail-closed LangGraph on `main`, so KEEP became a live contested alternative. | NS-31 records **DEC-053 park recommended**; KEEP only if a DEC supersedes Memo 1 / R-SR-27. |
| PR-3 | Major | Several P1 items still listed `Depends on: NS-32` after Phase B acceptance criteria were already ticked. | Depends-on retargeted. |
| PR-4 | Unchanged blockers | Re-queried 2026-09-05: `GET …/rules/branches/main` → `[]`; `feature/governed-run-console` still at `5970249…`; zero tags; `license: null`. | NS-1, NS-2, NS-3, NS-30 stay P0. |

### 2026-09-05b second peer-rewrite findings (verified)

| ID | Severity | Finding | Effect on this file |
|---|---|---|---|
| PR-5 | **Blocker (doc)** | NEXT_STEPS still listed NS-11 / NS-31 / NS-33 as open; header cited `2441547` not tip `58490c1`. | Move NS-11 / NS-31 / NS-33 to §6; header retargeted to tip. |
| PR-6 | **Blocker (doc)** | Remediation plan still revision 2 @ `2441547`; AC-5 unchecked; Phase E prose conflated R-SR-5 Done with R-SR-2 still gating. | Plan → revision 3; AC-5 `[x]`; Phase E gated on NS-2 / R-SR-2 only. |
| PR-7 | Major | Phase F still listed `ruff format`; NS-33 delivered on #91 (blame-ignore + format gate). | Drop ruff from Phase F slack; note delivered. |
| PR-8 | Major | NS-4 still said bot PRs left for maintainer; Dependabot open = none (closed #62-#78). | §6 NS-4 disposition updated. |
| PR-9 | Major | §4 Phase E still blocked on NS-31; DEC-053…056 exist on #93. | Phase E retargeted to **NS-2** before destructive slices. |
| PR-10 | Major | NS-9 / NS-34 still treated NS-31 undecided; PARK decided (DEC-053). | NS-9 moves with park; NS-34 Depends on nothing mechanical (DECs logged). |
| PR-11 | Product | NS-17 open on #97; Copilot: `policy_path` not plumbed into `agent_memory_defaults` / gap injection. | Keep open; strengthen Done-when (policy_path + mutation + `max_gaps==0`). |
| PR-12 | Unchanged P0 | Re-queried: ruleset `[]`; tip `58490c1`; branch `5970249…`; 0 tags; `license: null`. | NS-1 / NS-2 / NS-3 / NS-30 stay P0. |

---

## 1. P0 - one owner sitting, zero code

These four are settings, credentials, a file and a release identity.
Nothing an agent does advances them. (NS-31's four DECs landed on #93;
R-SR-5 / AC-5 are closed - see §6.)

### NS-1 · Apply the branch ruleset to `main`

**Why now.** Every gate in this repository is still advisory. Re-queried
2026-09-05: `GET /repos/ianshank/Mango_Code_Agent-Harness/rules/branches/main`
returns `[]`. DEC-044 already chose the export shape
(`required_approving_review_count: 0`, empty `bypass_actors`); importing it is
the only remaining step.

**Evidence.** The API call above; `.github/rulesets/main.json`;
`test_workflow_contracts.py` / `test_ci_gate_required_checks.py` pin the export
to the workflow's job names.

Required status checks (derived from `.github/workflows/python-package.yml`,
not from memory): `build (3.9)`, `build (3.10)`, `build (3.12)`,
`build-full`, `secret-scan`, `dependency-audit`, `dependency-audit (3.9)`,
`dependency-audit (3.10)`, `dependency-audit (3.12)`.

**Done when.** Settings → Rules → Rulesets → Import
`.github/rulesets/main.json` (with `required_signatures` and
`required_linear_history` added first, R-SR-1), and
`GET …/rules/branches/main` returns a non-empty list; a PR whose head has a
failing required check then reports the failure on its merge button
(AC-1). Until the API says so, the item stays open.

**Depends on.** Nothing.

### NS-2 · Rotate the credential DEC-014 documents, then purge and re-verify

**Why now.** DEC-014 states that `feature/governed-run-console` "carries a real
leaked key". The branch is still on the remote at `5970249…` (re-queried
2026-09-05). `make secrets` stays ref-scoped (`--log-opts="HEAD"`) by design,
so no PR gate will ever see that ref again.

**Evidence.** `git ls-remote --heads origin feature/governed-run-console`;
DEC-014; Makefile secrets targets.

**Done when.** Credential rotated at the provider first, branch deleted or
purged, decision-log entry records the date, and
`gitleaks git . --config .gitleaks.toml --log-opts="--all"` reports clean -
it must have failed on the pre-rotation ref set, or the scan proves nothing
(R-SR-2, AC-2).

**Depends on.** Nothing. Do not wait for NS-1. **Required before any Phase E
destructive slice.** DEC-053…056 are logged; they do not lift this gate.

### NS-3 · Settle the release identity, tag it, and cap `[Unreleased]`

**Why now.** No git tag has ever existed (re-queried 2026-09-05: zero tags), so
"2.4.0" names no commit; RCA prose still says v2.5.0 in places; Phase E removal
clocks count from a release that does not exist.

**Evidence.** `git tag -l` / `git ls-remote --tags origin` empty;
`test_documentation_truth.py` release/changelog assertions.

**Done when.** Mirrors agree on one version with a matching `## [x.y.z]`
section; an annotated tag exists at that commit; tests fail when the tag is
absent (R-SR-4, AC-4); the `[Unreleased]` cap can fire.

**Depends on.** Nothing.

### NS-30 · Choose a licence

**Why now.** GitHub `/license` returns null; no `LICENSE`; no licence key in
`pyproject.toml` / `harness/node/package.json`. The repo presents as an adoption
template that nobody may legally adopt (audit B2).

**Evidence.** API `license: null`; `ls LICENSE*` → none.

**Done when.** `LICENSE` exists, `pyproject.toml` declares the same licence
under PEP 639, `package.json` matches, and documentation-truth tests fail when
any of the three is removed (R-SR-3, AC-3). Plan recommends Apache-2.0.

**Depends on.** Nothing.

---

## 2. P0 - agent-executable front

**Phase B is landed on PR #86** (despite the docs-only title; body + AC ticks
are the evidence). Do not open a "finish Phase B" item. **NS-31 DECs are logged
on PR #93** (DEC-053 PARK … DEC-056); do not revive an "undecided" NS-31 item.
Remaining agent work is P1 below. If a Phase B AC box is unticked or its named
command fails on current `main`, file a regression under the remediation plan -
do not revive NS-32.

---

## 3. P1 - unblocked, take in any order

### NS-6 · Move the Python floor to 3.10, then 3.11 *(spec required)*

**Why now.** 3.9 is EOL; every runtime dependency is already `>= 3.10`. Four
carve-outs hold the floor (forked pytest pin, `continue-on-error` audit leg,
`coverage.optional_extras` waiver, `check_py_compat.py`). mypy is pinned to
1.11.2 because 2.x dropped `--python-version 3.9` (DEC-046).

**Evidence.** `pyproject.toml`; `requirements-dev.txt`; workflow matrix;
DEC-028; audit H1, M10.

**Done when.** `make spec NAME=python-floor-310` supersedes DEC-028;
`requires-python` is `>=3.10`; 3.9 legs and carve-outs are deleted rather than
re-homed; mypy 2.x with `warn_unused_ignores`; ruleset/required-check tests fail
if a 3.9 context remains (R-SR-23, AC-23).

**Depends on.** Nothing. Unblocks NS-35 and packaging halves of Phase F.

### NS-9 · Justify the last pragma, and stop the swallow behind it

**Why now.** `langgraph/__init__.py` still carries the remaining
`# pragma: no cover` over an `except ImportError: pass` that turns a broken
`graph.py` into "`build_graph` just isn't exported".

**Evidence.** `harness/shared/langgraph/__init__.py`; `coverage.optional_extras`;
DEC-053 (PARK).

**Done when.** The swallow is gone and
`pytest harness/shared/tests/test_langgraph_regression.py -k import_failure`
fails when a broken `graph.py` is silently absorbed. Protected path;
attestation required. **DEC-053 chose PARK** - this item moves with the package
into `experimental/` on the Phase E LangGraph park PRs (R-SR-27); it is not
mainline KEEP polish.

**Depends on.** Nothing mechanical; land with the R-SR-27 park slices, not as a
standalone KEEP investment ahead of the move.

### NS-17 · Retention and scoping for the agent memory directory

**Why now.** `knowledge_gap_log` / `hypothesis_register` append to
`.mango/memory/*.json` with no bound; `MEMORY_DIR` resolves from the install
path, so workspaces share one store and nothing reads it back (audit M4).
Open PR #97 implements the bound + workspace scope + planner injection, but
Copilot review is unresolved: `policy_path` is not plumbed into
`agent_memory_defaults()` / gap injection, so non-default governance policies
do not affect retention or planner gap limits.

**Evidence.** `harness/shared/meta_tools.py`; `harness/shared/orchestrator/loop.py`;
PR #97 review threads on `policy_path`; grep for readers outside tests.

**Done when.**
- A bound from `governance-policy.json` is enforced via the **active**
  `policy_path` (same path `ExecutionLoop` already uses for budgets), not only
  the built-in harness defaults.
- Store lives under the workspace; one reader surfaces gaps into the planner
  prompt.
- Tests fail when retention or surfacing breaks.
- A mutation / negative case fails closed when `max_gaps == 0` (no false
  "logged" / non-empty trim result from the `[-0:]` pitfall).
- PR #97 either absorbs these criteria or a follow-up closes them before NS-17
  moves to §6.

**Depends on.** Nothing.

### NS-18 · Connect the reasoner persona to what the bridge exposes *(spec required)*

**Why now.** `.mango/agents/nemotron-reasoner.md` names Claude Code tools
(`Bash`, `Read`, …) and is fed verbatim to Nemotron; only `run_command` matches
the tool bridge (audit M2). Phase B's MCP slice already serves one registry to
both transports (R-SR-15).

**Evidence.** `.mango/agents/nemotron-reasoner.md`;
`harness/shared/orchestrator/loop.py`; `harness/shared/tool_schemas.py`;
`docs/specs/reasoner-bridge-tool-parity.md`.

**Done when.** Runtime system prompt tool paragraph is generated from
`NEMOTRON_TOOLS`; prompt sha logged on `run_id` events; tests fail when the
persona names a tool the bridge does not expose. Protected path; attestation.

**Depends on.** Nothing (Phase B MCP parity shipped).

### NS-34 · Decision records as records

**Why now.** ~52 decisions are pipe-delimited lines in
`harness/node/.governance/decision-log.md`, restated into `GOVERNANCE_SKILL.md`.
Every PR writes each decision twice (audit H15). DEC-053…056 were the last
four NS-31 entries written in the old format (#93).

**Evidence.** decision-log; `validate_governance_docs.py`; PR #93.

**Done when.** One file per decision under `docs/decisions/` with status,
context, decision, consequences, machine-readable `supersedes:`; validators
read a generated index; skill lockstep copy deleted; `make validate` fails on a
decision without status.

**Depends on.** Nothing (NS-31 / R-SR-5 closed on #93). Prefer migrating before
further Phase E decision churn, but the DECs are no longer a blocker.

### NS-35 · A mutation score instead of mutation prose *(spec required)*

**Why now.** `gate-mutation-proof` is a by-hand loop whose CHANGELOG claims are
unverifiable (audit H9 / DEC-024).

**Evidence.** `.mango/skills/gate-mutation-proof/SKILL.md`; no `mutmut` in lock.

**Done when.** `mutmut` runs nightly over named governance modules; policy key
`mutation.min_score`; job fails below it.

**Depends on.** NS-6.

### NS-36 · Phase D of the plan: CI truthfulness *(spec exists)*

**Why now.** `infra-reviewed` survives later pushes (audit H3); Dockerfile runs
as root on an un-digested base (M17); Dependabot lacks `docker` / cooldown
(M18).

**Evidence.** workflows; `Dockerfile`; `.github/dependabot.yml`.

**Done when.** R-SR-24 and R-SR-25 landed with AC-24 and AC-25; a PR with a
stale SHA in its attestation table fails `build-full`.

**Depends on.** NS-1 (signatures / ruleset live).

### NS-29 · The program plans

Pointer only: status is the remediation plan's boxes, read there, not here.
`docs/specs/code-quality-tech-debt-plan.md` is closed at revision 2.
Remediation plan is revision 3 (Phase B Done; R-SR-5 / AC-5 closed; Phase E
gated on R-SR-2).

---

## 4. Parked - blocked on a decision or a gate that does not exist yet

| Item | Blocked on |
|---|---|
| **Phase E** (R-SR-26 … R-SR-29) | **NS-2 / R-SR-2 before any destructive slice.** DEC-053…056 (NS-31 / R-SR-5 / AC-5) are logged on #93 - PARK order stands: **JVM → LangGraph → openspec → mirroring**. Do not start Phase E code while the DEC-014 credential branch remains. Premature Phase E inverts DEC-024 (claimed readiness without the hard gate). |
| **NS-19 · NIM multi-model routing / prompt-cache cost** | No spec; `complete_chat` has no provider boundary (`stream: False` hard-coded, `usage` discarded). Phase F boundary first. |
| **Context-window budget / HITL interrupts** | Budget needs policy key + spec (Phase B events exist). HITL needs an explicit non-graph design under DEC-053 PARK (in-graph interrupts stay with a revival DEC). |
| **LATS end-to-end wiring** | `synthesis.lats_enabled` is `false`; INV-15 needs ablation gate (DEC-027). Moves with DEC-053 park / revival. |
| **`AC-CE-1` ProcessBackend capability profiles** | OS isolation is the permanent B4 fix; Phase B digest is containment only. |
| **Eval harness / nightly live smoke** | Scoped `NVIDIA_API_KEY` in scheduled workflow (owner) + fixtures after openspec fold. |

---

## 5. Explicitly not doing

- **Annotating the test suite** (~530 `no-untyped-def` on tests). Strict typing
  on source via NS-6; tests are a separate project.
- **Regrouping `harness/shared/`** - DEC-020 / DEC-029 stand.
- **Closed-plan ceremony items** listed in the remediation plan's
  §Explicitly not doing.
- **Pre-emptive decomposition** of files near size budget without a behaviour
  change that needs the seam.
- **Raising the `fastapi` floor to ≥0.141.1** until NS-6.
- **A `HEALTHCHECK` in the Dockerfile** - nothing listens; the CMD exits.
- **Starting Phase E before NS-2** - DECs logged ≠ credential rotated.

---

## 6. Delivered, and removed from the open list

**Closed 2026-09-05b (this rewrite's evidence pass):**

| Was | Now |
|---|---|
| **NS-31** Four in-or-out decisions | **Logged on PR #93.** DEC-053 LangGraph PARK (sunset TBD); DEC-054 JVM relocate; DEC-055 `openspec/` fold; DEC-056 mirroring collapse Option A (supersedes DEC-005 mechanism). Restated in `GOVERNANCE_SKILL.md`. Remediation plan rev 3 ticks AC-5 / R-SR-5. Phase E code still waits on NS-2. |
| **NS-11** Reconcile regression tier | **Landed on PR #90.** Reproductions in `harness/shared/tests/regression/`; `test_regression_tier_pin.py` fails if moved back; duplicate `make test-regression` dropped from `build-full`. |
| **NS-33** Adopt `ruff format` | **Landed on PR #91** (+ #95 size-budget hotfix). `[tool.ruff.format]`; `make lint-python` runs `ruff format --check`; reformat commit in `.git-blame-ignore-revs`. Removed from Phase F slack. |

**Closed 2026-09-05c (NS-21):**

| Was | Now |
|---|---|
| **NS-21** Hook surface / post-turn observation | **Landed on PR #99.** `post-*-run` scripts + shared recorder append turn `status` / `run_id` / tool-call spend to `.mango/.state/post-run.jsonl`; liveness + record-contract tests fail if firing stops. DEC-003 unchanged. |

**Closed 2026-09-05 (prior rewrite's evidence pass):**

| Was | Now |
|---|---|
| **NS-32** Land Phase B (PR #86) | **Landed on PR #86.** Title was docs-only (`docs(reports): 2026 coding-standards audit`), but the PR body and 97-file diff delivered Phase B (R-SR-6…R-SR-22; AC-6…AC-22, AC-33 `[x]`). Runtime/containment narrative: DEC-048…DEC-051. Remediation plan rev 2 marked Phase B Done. Do not re-open under a different PR label. |

**Closed earlier - Dependabot disposition (keep visible):**

| Was | Now |
|---|---|
| **NS-4** Dependabot contradicted DEC-031 | The `pip` ecosystem is gone from `.github/dependabot.yml`; DEC-033 records why, and that re-enabling it means superseding DEC-031 rather than editing the config. **Bot PRs #62-#78 are all closed**; Dependabot open queue is empty (re-queried 2026-09-05). |

**Closed earlier (pointers only - details in prior revisions / CHANGELOG):**
NS-5, NS-7, NS-8, NS-10, NS-12, NS-13, NS-14, NS-15, NS-16, NS-20,
NS-22…NS-28, gate half of NS-3, bound half of NS-9 - see git history of this
file at `6f0f18b`…`58490c1` and `docs/reports/ROADMAP-PEER-REVIEW.md`.

**Corrected record (do not re-open as "unwired"):**

- `@with_authority` / `@budgeted` are applied **and**, after DEC-052 / PR #87-#88,
  denials fail closed through the compiled graph (INV-LG-6). Applied ≠ enforcing
  was the 2026-09-04 defect; do not claim either half without a graph-level test.
- Specs-gate template / MUST-bullet refinements remain live in `plan_rules.py`.

---

## 7. Where the history went

- **Completed milestones v2.1.3 - v2.4.0** -
  [`docs/releases/milestone-history.md`](docs/releases/milestone-history.md).
- **Per-release narrative** - `CHANGELOG.md`; long bodies in `docs/releases/`.
- **Decisions** - `harness/node/.governance/decision-log.md` (migrate via NS-34).
- **Specifications** - `docs/specs/`; Phase B / R-SR-5 status boxes in
  `2026-standards-remediation-plan.md` (revision 3).

Cite section IDs (`NS-1`, `R-SR-1`), never line numbers into this living file.
