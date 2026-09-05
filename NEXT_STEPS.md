# Roadmap & Next Steps: Agentic SSD & Nemotron AI Platform

**Version:** 2.4.0
**Status:** Active roadmap — forward-looking only
**Last reviewed:** 2026-09-05 · peer rewrite against `main` @ `2441547` (PRs #86–#88) · audit in [`docs/reports/2026-STANDARDS-AUDIT.md`](docs/reports/2026-STANDARDS-AUDIT.md) · program plan in [`docs/specs/2026-standards-remediation-plan.md`](docs/specs/2026-standards-remediation-plan.md) · prior peer review method in [`docs/reports/ROADMAP-PEER-REVIEW.md`](docs/reports/ROADMAP-PEER-REVIEW.md)

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
blocker named. Status boxes live in the plan — do not restate them here.

Every item carries four fields, and an item without them is not ready to be
worked:

- **Why now** — the consequence of not doing it, not a restatement of the title.
- **Evidence** — a command, a file reference, or an API result a reviewer can
  re-run today. A claim in prose is not evidence (DEC-024).
- **Done when** — a falsifiable criterion bound to the stage that proves it, with
  the failure it must be able to report.
- **Depends on** — the item that must land first, or `nothing`.

Priorities are an ordering, not a schedule. **Spec discipline.** Items marked
*(spec required)* change behaviour, policy, or a protected path and must not be
implemented without `make spec NAME=<feature>`, the `openspec-peer-review`
skill, then `make pre-pr`.

### 2026-09-05 peer-rewrite findings (verified)

| ID | Severity | Finding | Effect on this file |
|---|---|---|---|
| PR-1 | **Blocker (doc)** | NS-32 said "Land Phase B (PR #86)". PR #86 is `docs(reports): 2026 coding-standards audit`. Phase B ACs AC-6…AC-22 and AC-33 are `[x]` in the remediation plan; containment/runtime work is recorded in DEC-048…DEC-051. | NS-32 closed → §6 Delivered. |
| PR-2 | **Blocker (product)** | NS-31's memo recommended parking LangGraph, but PR #87/#88 + DEC-052 invested in fail-closed LangGraph on `main`. "Park" is no longer the default reading of reality. | NS-31 requires an explicit KEEP vs PARK decision. |
| PR-3 | Major | Several P1 items still listed `Depends on: NS-32` after Phase B acceptance criteria were already ticked. | Depends-on retargeted. |
| PR-4 | Unchanged blockers | Re-queried 2026-09-05: `GET …/rules/branches/main` → `[]`; `feature/governed-run-console` still at `5970249…`; zero tags; `license: null`. | NS-1, NS-2, NS-3, NS-30 stay P0. |

---

## 1. P0 — one owner sitting, zero code

These five are settings, credentials, a file and decision-log entries.
Nothing an agent does advances them.

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
`gitleaks git . --config .gitleaks.toml --log-opts="--all"` reports clean —
it must have failed on the pre-rotation ref set, or the scan proves nothing
(R-SR-2, AC-2).

**Depends on.** Nothing. Do not wait for NS-1. **Required before any Phase E
destructive slice.**

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

### NS-31 · Record the four in-or-out decisions (LangGraph is now contested)

**Why now.** Four half-done stacks still cost gates, shims and personas on
every PR: `harness/jvm/`, `harness/shared/langgraph/`, `openspec/`, and
per-stack governance mirroring. Phase E cannot start until the decisions are
entries in the log (C-CQ-2 / R-SR-5).

**LangGraph is no longer a soft "park" default.** Between the remediation
plan's review memos and 2026-09-05, PR #87/#88 and DEC-052 landed fail-closed
graph routing, conclusive-count hardening, and INV-LG-6/7 on `main`. A decision
that says "park" without addressing that investment is false. The entry must
choose one of:

| Choice | Meaning | Consequences |
|---|---|---|
| **KEEP** | LangGraph stays a supported runtime path | Supersede the park recommendation; rewrite R-SR-27 / Phase E order; continue NS-9 and graph expansion under specs; HITL/LATS stay gated on ablation (DEC-027) not on "move to experimental". |
| **PARK** | Stop feature work; move under `experimental/` with a named sunset | Honour R-SR-27 as written; freeze further LangGraph PRs except security; NS-9 moves with the package; do not open new graph-expansion specs. |

JVM relocate, `openspec/` fold, and mirroring collapse remain as the memos
recommend unless a new memo says otherwise.

**Evidence.** Program plan §Review record; audit H14/M3/M22/M23; DEC-052;
`gh pr view 87` / `88` merged on 2026-09-05.

**Done when.** Four decision-log entries exist (JVM, LangGraph KEEP-or-PARK with
sunset if PARK, `openspec/` fold, mirroring collapse including DEC-005 push
posture), each restated so `validate_governance_docs.py` passes, and
`make validate` rejects an entry missing from either (R-SR-5, AC-5).

**Depends on.** Nothing.

---

## 2. P0 — agent-executable front

**Phase B is landed.** Do not open a "finish PR #86" item. Remaining agent
work is P1 below. If a Phase B AC box is unticked or its named command fails on
current `main`, file a regression under the remediation plan — do not revive
NS-32.

---

## 3. P1 — unblocked, take in any order

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

**Evidence.** `harness/shared/langgraph/__init__.py`; `coverage.optional_extras`.

**Done when.** The swallow is gone and
`pytest harness/shared/tests/test_langgraph_regression.py -k import_failure`
fails when a broken `graph.py` is silently absorbed. Protected path;
attestation required. If NS-31 chooses PARK, this item moves with the package
into experimental and is not a mainline P1.

**Depends on.** Nothing mechanical; **coordinate with NS-31** — do not invest
in KEEP-only polish the same week a PARK decision lands.

### NS-11 · Reconcile the regression tier with the contract it claims

**Why now.** `harness/CONTRACT.md` defines `harness/shared/tests/regression/` as
one reproduction per defect that reached `main`, run by `make test-regression`.
Recent reproductions still sit in the unit tier; `build-full` runs the
regression tier twice because `testpaths` already recurses into it.

**Evidence.** `harness/CONTRACT.md`; `pyproject.toml` `testpaths`; workflow.

**Done when.** Named reproductions live in the regression tier with a pin that
fails when one is moved back out. Rewriting the contract instead is not an
option.

**Depends on.** Nothing.

### NS-17 · Retention and scoping for the agent memory directory

**Why now.** `knowledge_gap_log` / `hypothesis_register` append to
`.mango/memory/*.json` with no bound; `MEMORY_DIR` resolves from the install
path, so workspaces share one store and nothing reads it back (audit M4).

**Evidence.** `harness/shared/meta_tools.py`; grep for readers outside tests.

**Done when.** A bound from `governance-policy.json` is enforced; store lives
under the workspace; one reader surfaces gaps into the planner prompt; tests
fail when retention or surfacing breaks.

**Depends on.** Nothing.

### NS-21 · The hook surface has one live hook and no loop

**Why now.** Five of six `.mango/hooks/` scripts are dormant by DEC-003; three
of four `PERMITTED_HOOK_NAMES` have no script on disk. Phase B already added
`run_id` + structured events (R-SR-13) — the observation point this item wanted.

**Evidence.** `harness/shared/orchestrator/hook_runner.py`; `.mango/hooks/`;
DEC-003; DEC-050.

**Done when.** Either a post-turn hook records verdict and tool-call count with
a failing test when it stops firing, or a decision-log entry records that the
`post-*-run` namespace stays empty and why.

**Depends on.** Nothing (Phase B events already shipped).

### NS-18 · Connect the reasoner persona to what the bridge exposes *(spec required)*

**Why now.** `.mango/agents/nemotron-reasoner.md` names Claude Code tools
(`Bash`, `Read`, …) and is fed verbatim to Nemotron; only `run_command` matches
the tool bridge (audit M2). Phase B's MCP slice already serves one registry to
both transports (R-SR-15).

**Evidence.** `.mango/agents/nemotron-reasoner.md`;
`harness/shared/orchestrator/loop.py`; `harness/shared/tool_schemas.py`.

**Done when.** Runtime system prompt tool paragraph is generated from
`NEMOTRON_TOOLS`; prompt sha logged on `run_id` events; tests fail when the
persona names a tool the bridge does not expose. Protected path; attestation.

**Depends on.** Nothing (Phase B MCP parity shipped).

### NS-33 · Adopt `ruff format`

**Why now.** No `[tool.ruff.format]`, no CI step; `ruff format --check` would
change ~176 files (audit H11). Must be its own commit so blame can skip it.

**Evidence.** No `ruff format` in Makefile / pyproject / workflows.

**Done when.** One reformat commit listed in `.git-blame-ignore-revs`;
`make lint-python` runs `ruff format --check`; makefile-contract test fails
when the step is removed.

**Depends on.** Nothing (Phase B file churn has landed; do not batch with
behaviour PRs).

### NS-34 · Decision records as records

**Why now.** ~48 decisions are pipe-delimited lines in
`harness/node/.governance/decision-log.md`, restated into `GOVERNANCE_SKILL.md`.
Every PR writes each decision twice (audit H15).

**Evidence.** decision-log; `validate_governance_docs.py`.

**Done when.** One file per decision under `docs/decisions/` with status,
context, decision, consequences, machine-readable `supersedes:`; validators
read a generated index; skill lockstep copy deleted; `make validate` fails on a
decision without status. NS-31's four entries should be the last written in the
old format.

**Depends on.** NS-31.

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

---

## 4. Parked — blocked on a decision or a gate that does not exist yet

| Item | Blocked on |
|---|---|
| **Phase E** (R-SR-26 … R-SR-29) | NS-31's four entries (LangGraph KEEP vs PARK changes whether R-SR-27 is delete/move or "continue under specs"); **NS-2 before any destructive slice**. If PARK: order JVM → openspec → LangGraph → mirroring. If KEEP: drop LangGraph from the delete sequence; still fold openspec / relocate JVM / collapse mirroring. |
| **NS-19 · NIM multi-model routing / prompt-cache cost** | No spec; `complete_chat` has no provider boundary (`stream: False` hard-coded, `usage` discarded). Phase F boundary first. |
| **Context-window budget / HITL interrupts** | Budget needs policy key + spec (Phase B events exist). HITL needs NS-31 KEEP (interrupts in-graph) or an explicit non-graph design if PARK. |
| **LATS end-to-end wiring** | `synthesis.lats_enabled` is `false`; INV-15 needs ablation gate (DEC-027). Moves with NS-31. |
| **`AC-CE-1` ProcessBackend capability profiles** | OS isolation is the permanent B4 fix; Phase B digest is containment only. |
| **Eval harness / nightly live smoke** | Scoped `NVIDIA_API_KEY` in scheduled workflow (owner) + fixtures after openspec fold. |

---

## 5. Explicitly not doing

- **Annotating the test suite** (~530 `no-untyped-def` on tests). Strict typing
  on source via NS-6; tests are a separate project.
- **Regrouping `harness/shared/`** — DEC-020 / DEC-029 stand.
- **Closed-plan ceremony items** listed in the remediation plan's
  §Explicitly not doing.
- **Pre-emptive decomposition** of files near size budget without a behaviour
  change that needs the seam.
- **Raising the `fastapi` floor to ≥0.141.1** until NS-6.
- **A `HEALTHCHECK` in the Dockerfile** — nothing listens; the CMD exits.

---

## 6. Delivered, and removed from the open list

**Closed 2026-09-05 (this rewrite's evidence pass):**

| Was | Now |
|---|---|
| **NS-32** Land Phase B (PR #86) | **Mis-attributed.** PR #86 landed the audit report only. Phase B requirements R-SR-6…R-SR-22 are accepted in the remediation plan (AC-6…AC-22, AC-33 ticked). Runtime/containment narrative: DEC-048…DEC-051. Do not re-open under the PR #86 label. |

**Closed earlier (pointers only — details in prior revisions / CHANGELOG):**
NS-4, NS-5, NS-7, NS-8, NS-10, NS-12, NS-13, NS-14, NS-15, NS-16, NS-20,
NS-22…NS-28, gate half of NS-3, bound half of NS-9 — see git history of this
file at `6f0f18b`…`2441547` and `docs/reports/ROADMAP-PEER-REVIEW.md`.

**Corrected record (do not re-open as "unwired"):**

- `@with_authority` / `@budgeted` are applied **and**, after DEC-052 / PR #87–#88,
  denials fail closed through the compiled graph (INV-LG-6). Applied ≠ enforcing
  was the 2026-09-04 defect; do not claim either half without a graph-level test.
- Specs-gate template / MUST-bullet refinements remain live in `plan_rules.py`.

---

## 7. Where the history went

- **Completed milestones v2.1.3 – v2.4.0** —
  [`docs/releases/milestone-history.md`](docs/releases/milestone-history.md).
- **Per-release narrative** — `CHANGELOG.md`; long bodies in `docs/releases/`.
- **Decisions** — `harness/node/.governance/decision-log.md` (migrate via NS-34).
- **Specifications** — `docs/specs/`; Phase B status boxes in
  `2026-standards-remediation-plan.md`.

Cite section IDs (`NS-1`, `R-SR-1`), never line numbers into this living file.
