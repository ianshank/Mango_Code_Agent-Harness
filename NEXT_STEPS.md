# Roadmap & Next Steps: Agentic SSD & Nemotron AI Platform

**Version:** 2.4.1
**Status:** Active roadmap — forward-looking only
**Last reviewed:** 2026-09-05 · tip `main` @ `2441547` (post #86–#88) · audit in [`docs/reports/2026-STANDARDS-AUDIT.md`](docs/reports/2026-STANDARDS-AUDIT.md) · program plan in [`docs/specs/2026-standards-remediation-plan.md`](docs/specs/2026-standards-remediation-plan.md) (rev 2)

---

## How to read this file

This file is the single roadmap for the repository, and it contains **only work
that is not yet done**. Completed milestones through v2.4.0 live in
[`docs/releases/milestone-history.md`](docs/releases/milestone-history.md); the
narrative of what shipped lives in `CHANGELOG.md` and `docs/releases/`.

The roadmap does not own work that a program spec owns. The 2026 remediation
plan (`docs/specs/2026-standards-remediation-plan.md`, R-SR-1 … R-SR-30) carries
every audit finding and every open requirement of the closed
`code-quality-tech-debt-plan.md`; this file lists what is **blocked on a person**,
what an **agent can do without a decision**, and what is **parked** with its
blocker named. An earlier revision of this file restated the program plan's
status paragraph by paragraph and drifted from it on every PR; that is why the
pointer replaces the restatement.

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

---

## 1. P0 — one owner sitting, zero code

These five are settings, credentials, a file and four decision-log entries.
Nothing an agent does advances them, which is why P0 has been static for four
releases: it had no agent-executable front. Section 2 gives it one.

### NS-1 · Apply the branch ruleset to `main`

**Why now.** Every gate in this repository is advisory. `GET
/repos/ianshank/Mango_Code_Agent-Harness/rules/branches/main` returns `[]` and
the branches API reports `"protected": false` (both re-queried 2026-09-04
during the standards audit; re-queried 2026-09-05 still empty). PR #60 merged with all four `build` checks
`failure`; PRs #60, #79 and #80 carry no approving review. DEC-044 already
removed the code-owner rule that made the export unappliable.

**Evidence.** The two API calls above; `.github/rulesets/main.json` (nine
required contexts, `bypass_actors: []`, `required_approving_review_count: 0`);
`test_workflow_contracts.py` pins the export to the workflow's job names.

Required status checks (derived from `.github/workflows/python-package.yml`,
not from memory): `build (3.9)`, `build (3.10)`, `build (3.12)`,
`build-full`, `secret-scan`, `dependency-audit`, `dependency-audit (3.9)`,
`dependency-audit (3.10)`, `dependency-audit (3.12)`.

**Done when.** Settings → Rules → Rulesets → New ruleset → Import
`.github/rulesets/main.json` (with `required_signatures` and
`required_linear_history` added first, R-SR-1), and
`GET …/rules/branches/main` returns a non-empty list; a PR whose head has a
failing required check then reports the failure on its merge button. Plan
criterion AC-1. Until the API says so, the item stays open.

**Depends on.** Nothing.

### NS-2 · Rotate the credential DEC-014 documents, then purge and re-verify

**Why now.** DEC-014 states that the branch `feature/governed-run-console`
"carries a real leaked key". The remediation scoped `gitleaks git` to
`--log-opts="HEAD"`, which is correct for a PR gate and silent about a branch
nobody opens a PR for. The audit's `make secrets` run reports "no leaks found";
that sentence covers this branch's ancestry only, and revision 1 of the audit
misread it as "full history" (corrected in its revision record).

**Evidence.** `git ls-remote --heads origin feature/governed-run-console`
returns `5970249…`; `Makefile:177` and both stack mirrors pass
`--log-opts="HEAD"`; no decision-log entry records a rotation.

**Done when.** The credential is rotated at the provider first, the branch is
deleted or purged, a decision-log entry records the date, and
`gitleaks git . --config .gitleaks.toml --log-opts="--all"` run once reports
clean — it must report the leak on the pre-rotation ref set, or the scan
proves nothing (R-SR-2, AC-2). `make secrets` stays ref-scoped per DEC-014.

**Depends on.** Nothing. Do not wait for NS-1.

### NS-3 · Settle the release identity, tag it, and cap `[Unreleased]`

**Why now.** No git tag has ever existed, so "2.4.0" names no commit;
`docs/rca/e2e_origin_sync_triage_rca_v2.5.0.md` says v2.5.0 while the four
version mirrors say 2.4.0; and `CHANGELOG.md`'s `[Unreleased]` remains far over the 400-line cap (re-check with
`wc -l` / the cap regex in `test_documentation_truth.py`); the regex matches
only `## [x.y.z]` headings, so the cap cannot fire on `[Unreleased]`. The Phase E removal clocks in the program plan count
from a release that does not exist.

**Evidence.** `git tag -l` and `git ls-remote --tags origin` are empty;
`test_documentation_truth.py:343` (the cap regex); `CHANGELOG.md:11-1208`.

**Done when.** Either the mirrors move to 2.5.0 with a `## [2.5.0]` section
covering PR #75, or the RCA is renamed; an annotated tag exists at the release
commit; `pytest harness/shared/tests/test_documentation_truth.py -k real_release`
fails when the tag is absent (R-SR-4, AC-4); and the cap applies to
`[Unreleased]` so `-k changelog_section` fails at its current length.

**Depends on.** Nothing.

### NS-30 · Choose a licence

**Why now.** There is no `LICENSE`, no `license` key in `pyproject.toml` or
`harness/node/package.json`, and `/license` on the GitHub API returns 404,
while README and `harness/CONTRACT.md` present the repository as an adoption
template. Nobody may legally adopt it (audit B2).

**Evidence.** `ls LICENSE*` → none; `grep -in license pyproject.toml
harness/node/package.json` → nothing.

**Done when.** `LICENSE` exists, `pyproject.toml` declares the same licence under
PEP 639, `package.json` matches, and
`pytest harness/shared/tests/test_documentation_truth.py -k license` fails when
any of the three is removed (R-SR-3, AC-3). Only a person can choose; the plan
recommends Apache-2.0.

**Depends on.** Nothing.

### NS-31 · Record the four in-or-out decisions

**Why now.** Four half-done stacks cost gates, shims and personas on every PR:
`harness/jvm/` (4 lines of product Kotlin, never built, hard-coded floors),
`harness/shared/langgraph/` (5 of 10 nodes stubs, one experimental caller),
`openspec/` (a strict tier that has run zero times and is mis-specified), and
the per-stack governance mirror (28 shim scripts policed by `check_dedup.py`).
Each has a decision memo with evidence, options, cost and migration order,
summarised in the program plan's review record. Phase E cannot start until
the decisions are entries in the log, because every step there deletes
something a constraint in the closed plan told it to keep (C-CQ-2).

**Evidence.** Program plan §Review record, row "Four in-or-out memos"; audit
H14, M3, M22, M23.

**Done when.** Four decision-log entries exist (JVM relocation, LangGraph park
with a named sunset release — proposed **DEC-053** is one of these four —
`openspec/` fold, mirroring collapse including the DEC-005 push posture), each
restated in `GOVERNANCE_SKILL.md` so `validate_governance_docs.py` passes, and
`make validate` rejects an entry missing from either (R-SR-5, AC-5). DEC-052
(fail-closed in place) MUST NOT count as the park entry. The posture question
(open question 2 of the plan) is the one that needs thought; the other three are
recommendations the review record already summarises (memo files not in tree).

**Depends on.** Nothing.

---

## 2. P0 — agent-executable, no decision needed

No open P0 agent-executable items. Phase B (former NS-32) is in §6 Delivered.

---

## 3. P1 — unblocked, take in any order

### NS-6 · Move the Python floor to 3.10, then 3.11 *(spec required)*

**Why now.** 3.9 reached end-of-life 2025-10-31; 3.10 reaches it 2026-10-31.
Every runtime dependency is already `>= 3.10`. Four carve-outs hold the floor:
the forked pytest pin (`8.4.2` on 3.9 carries PYSEC-2026-1845), a
`continue-on-error` audit leg that is also a *required* check, the
`coverage.optional_extras` per-file waiver, and `check_py_compat.py`'s AST
gate. mypy is pinned to 1.11.2 because 2.x removed `--python-version 3.9`
(DEC-046). An earlier revision of this item listed three carve-outs; the
fourth is the compatibility gate itself.

**Evidence.** `pyproject.toml:4`; `requirements-dev.txt:5-11`;
`.github/workflows/python-package.yml:320`; DEC-028; audit H1, M10.

**Done when.** `make spec NAME=python-floor-310` supersedes DEC-028;
`requires-python` is `>=3.10`; the 3.9 legs, both forked pins, the waiver, the
`continue-on-error` step and the `dependency-audit (3.9)` required context are
deleted rather than re-homed; 3.14 joins the matrix; mypy is 2.x with
`warn_unused_ignores` on; `target-version` is gone from `pyproject.toml`; and
`pytest harness/shared/tests/test_ci_gate_required_checks.py` fails if the
ruleset still names the 3.9 context (R-SR-23, AC-23). Plan open question 3
decides whether 3.11 lands in the same spec.

**Depends on.** Nothing. Unblocks the ESLint and packaging halves of Phase F and
the mypy bump.

### NS-9 · Justify the last pragma, and stop the swallow behind it *(spec required)*

**Why now.** `langgraph/__init__.py:52` carries the one remaining
`# pragma: no cover`, and the `except ImportError: pass` it covers turns a real
failure to import `graph.py` into "`build_graph` just isn't exported".
Removing the pragma alone takes the file to 80% against the 90% floor on the
legs that install the extra; deleting the swallow reads 7/7 there and 5/7 on a
local run without the extra and without `MANGO_CI_DESELECT_LANGGRAPH=1`.

**Evidence.** `harness/shared/langgraph/__init__.py:52`; `coverage.optional_extras`
in `harness/shared/governance-policy.json`.

**Done when.** The swallow is gone and
`pytest harness/shared/tests/test_langgraph_regression.py -k import_failure`
fails when a broken `graph.py` is silently absorbed; both interpreter cases
are recorded from a run with the extra installed. `harness/shared/langgraph/**`
is a protected path, so this carries an attestation. If NS-31 parks the
package first (R-SR-27), this item moves with it.

**Depends on.** Nothing mechanically. Soft-block: prefer after NS-31's LangGraph
DEC (KEEP vs park+sunset / DEC-053); if park wins, this item moves with R-SR-27.
Do not batch it: its failure mode lands on whoever has not installed the optional
extra.

### NS-11 · Reconcile the regression tier with the contract it claims

**Why now.** `harness/CONTRACT.md` defines `harness/shared/tests/regression/` as
one reproduction per defect that reached `main`, run standalone by
`make test-regression`. Reproductions for recent defects (the coverage-gate
shadowing probe in `test_coverage_gate.py`, the `pytester` session-hook run in
`test_session_hooks.py`) sit in the unit tier, and `build-full` runs the
regression tier twice because `testpaths` already recurses into it.

**Evidence.** `harness/CONTRACT.md:104-113`; `test_coverage_gate.py:355`;
`pyproject.toml:26`; `.github/workflows/python-package.yml:195-202`.

**Done when.** Each named reproduction moves into the tier naming its pre-fix
commit (as `regression/test_write_containment_regression.py` does), and
`make test-regression` fails when one is moved back out — pinned by a test that
lists them. Rewriting the contract instead is not an option here: the contract's
guarantee is the one adopters read.

**Depends on.** Nothing.

### NS-17 · Retention and scoping for the agent memory directory *(spec required)*

**Why now.** `knowledge_gap_log` and `hypothesis_register` append to
`.mango/memory/*.json` with no bound, and `MEMORY_DIR` resolves from the harness
install path rather than the workspace, so every workspace shares one store and
nothing ever reads it back (audit M4). Retention alone is the narrow framing.

**Evidence.** `harness/shared/meta_tools.py:20-22,117-166`; grep for readers
outside tests → none.

**Done when.** A bound sourced from `governance-policy.json` is enforced and
`pytest harness/shared/tests/test_meta_tools.py -k retention` fails when a
write exceeds it; the store lives under the workspace; and one reader exists
(open gaps fed into the next planner prompt) with a test that fails when the
gap is not surfaced.

**Depends on.** Nothing.

### NS-21 · The hook surface has one live hook and no loop

**Why now.** Five of six `.mango/hooks/` scripts are dormant by DEC-003; three of
the four names in `PERMITTED_HOOK_NAMES` have no script on disk, so the loop
fires them into `hook_path.exists()`'s false branch on every turn. Phase B adds
a `run_id` and one structured event per model and tool call (R-SR-13), which
is the observation point this item wanted; what remains is the decision about
the dormant namespace.

**Evidence.** `harness/shared/orchestrator/hook_runner.py:51`; `.mango/hooks/`;
DEC-003.

**Done when.** Either a post-turn hook records the turn's verdict and tool-call
count with a test that fails when it stops being fired, or a decision-log entry
records that the `post-*-run` namespace stays empty and why.

**Depends on.** Nothing.

### NS-18 · Connect the reasoner persona to what the bridge exposes *(spec required)*

**Why now.** `.mango/agents/nemotron-reasoner.md` was written for a Claude Code
subagent: it names `Bash`, `Read`, `Grep`, `Glob`, a skill and `make pre-pr`,
and is fed verbatim to Nemotron as its system prompt; only `run_command`
matches the tool bridge (audit M2). Phase B's MCP slice already serves one
registry to both transports (R-SR-15); the persona still describes neither.

**Evidence.** `.mango/agents/nemotron-reasoner.md:4,26-27`;
`harness/shared/orchestrator/loop.py:96-105`; `harness/shared/tool_schemas.py`.

**Done when.** The runtime system prompt's tool paragraph is generated from
`NEMOTRON_TOOLS`, a prompt sha is logged on the `run_id` events, and
`pytest harness/shared/tests/test_agent_prompts.py -k tools_match_bridge`
fails when the persona names a tool the bridge does not expose. Protected
path; attestation required.

**Depends on.** Nothing.

### NS-33 · Adopt `ruff format`

**Why now.** No `[tool.ruff.format]`, no target, no CI step; `ruff format
--check` would change 176 of 361 files. `E`/`W` are selected but the formatter
that replaced them is absent (audit H11). It is one commit, and it must be its
own commit so `git blame` can skip it.

**Evidence.** `grep -rn "ruff format" Makefile pyproject.toml .github/workflows`
→ nothing; `python -m ruff format --check .` (re-run for current count; was 176 on 2026-09-04).

**Done when.** One reformat commit is listed in `.git-blame-ignore-revs`,
`make lint-python` runs `ruff format --check`, and
`pytest harness/shared/tests/test_makefile_contracts.py -k format_check` fails
when the step is removed.

**Depends on.** Nothing.

### NS-34 · Decision records as records *(spec required)*

**Why now.** 48 decisions are single pipe-delimited lines (longest 4,591
characters) in `harness/node/.governance/decision-log.md`, each restated by
validator in a 31 KB `GOVERNANCE_SKILL.md`; `docs/decisions/` does not exist.
Supersession is prose. Every PR writes each decision twice (audit H15).

**Evidence.** `harness/node/.governance/decision-log.md:3`;
`harness/shared/validate_governance_docs.py:21`.

**Done when.** One file per decision under `docs/decisions/` with status,
context, decision, consequences and a machine-readable `supersedes:` field;
`verify_zero_skips.py` and `validate_governance_docs.py` read the generated
index; the `GOVERNANCE_SKILL.md` lockstep copy is deleted; and `make validate`
fails on a decision file without a status. This is the migration NS-31's four
entries should be the last to write in the old format.

**Depends on.** NS-31.

### NS-35 · A mutation score instead of mutation prose *(spec required)*

**Why now.** `gate-mutation-proof` is a by-hand loop whose results appear in
CHANGELOG as "five mutation proofs" — the unverifiable claim CLAUDE.md rejects
(audit H9). The skill stays as the procedure for one-off proofs; the score is
what CI can read.

**Evidence.** `.mango/skills/gate-mutation-proof/SKILL.md:40-58`; no `mutmut`
in the lock or the Makefile.

**Done when.** `mutmut` runs nightly in `scheduled-drift.yml` over
`orchestrator/`, `tool_dispatch.py`, `tool_executors.py`,
`governance/command_actions.py` and `write_policy.py`, a `mutation.min_score`
policy key exists, and the job fails below it.

**Depends on.** NS-6 (mutmut's current major is `>= 3.10`).

### NS-36 · Phase D of the plan: CI truthfulness *(spec exists)*

**Why now.** The `infra-reviewed` label survives later pushes, so a PR labelled
once accepts arbitrary later commits to workflows and policies (audit H3); the
Dockerfile runs as root on an un-digested base and is never built (M17);
Dependabot lacks `docker` and an explicit `cooldown` (M18).

**Evidence.** `.github/workflows/python-package.yml:84,201`; `Dockerfile:2,38`;
`.github/dependabot.yml`.

**Done when.** R-SR-24 and R-SR-25 are landed with AC-24 and AC-25 ticked by
the commands they name; a PR with a stale SHA in its attestation table fails
`build-full`.

**Depends on.** R-SR-24 needs NS-1 (signatures / protection report assume the
ruleset is live). R-SR-25 (Dockerfile + Dependabot docker/cooldown) does **not**
— it can land independently.

### Dependabot disposition (post-DEC-046)

**Why now / record.** DEC-046 kept Action majors open as the tracked vehicle;
as of 2026-09-05 the listed bot PRs ended closed and unmerged,
and the open Dependabot queue is empty. Package bumps are expected to reappear
via Dependabot recreate (ops). Deferred maps: mypy 2.x / floor still NS-6;
docker + cooldown still R-SR-25 / NS-36; Action major upgrades remain an owner
decision when the bot reopens them.

**Evidence.** Open Dependabot pulls: 0. Closed set covers #62-#78 with null merged_at.

### NS-29 · The program plans

The audit-round-3 plan (`docs/specs/code-quality-tech-debt-plan.md`) is
**closed** at revision 2: Phase 1, R-CQ-9, R-CQ-10 and most of R-CQ-30 landed;
three of its ticked criteria were found to cite selectors collecting zero tests
and were corrected in place; its open remainder is carried or dropped by
`docs/specs/2026-standards-remediation-plan.md`, which owns every audit finding.
Status is that spec's boxes, read there, not here.

---

## 4. Parked — blocked on a decision or a gate that does not exist yet

| Item | Blocked on |
|---|---|
| **Phase E of the plan** (JVM relocation, LangGraph park, `openspec/` fold, mirroring collapse; R-SR-26 … R-SR-29) | NS-31's four decision-log entries; NS-2's rotation before any Phase E slice. Order (plan §Steps SoT): **JVM → LangGraph → openspec → mirroring**, with `[project.scripts]` first inside the last. Memo files are not on `main` — do not invent a second order. |
| **NS-19 · NIM multi-model routing and prompt-cache cost tracking** | No spec; and no provider boundary to route through — `complete_chat` is a monkeypatched module function with `stream: False` hard-coded and `usage` discarded (audit M5). The boundary is a Phase F item; routing follows it. |
| **Context-window budget and human-in-the-loop interrupts** (audit H4, H5) | The Phase B events give the loop token counts for the first time; a budget needs a policy key and a spec. HITL needs the LangGraph decision (interrupts live there or nowhere). |
| **LATS end-to-end wiring** | `synthesis.lats_enabled` is `false` and INV-15 requires an ablation gate that does not exist (DEC-027). Moves with the LangGraph decision. |
| **`AC-CE-1` capability-profile enforcement in `ProcessBackend`** | The permanent fix for audit B4 is OS-level isolation of the backend; the Phase B digest check is containment. Needs the versioned profile schemas first. |
| **Eval harness and nightly live smoke** (audit H10) | A scoped `NVIDIA_API_KEY` secret in the scheduled workflow, which is an owner action, and the recorded-transcript fixtures the eval spec (`openspec/changes/add-neurosym-governed-synthesis/specs/agent-evaluation/spec.md`, DRAFT) would replay — which moves under `docs/specs/` in Phase E. |

---

## 5. Explicitly not doing

Recorded so a future audit does not rediscover them as findings:

- **Annotating the test suite** (`--disallow-untyped-defs` reports ~530 findings,
  essentially all `no-untyped-def` on test functions). Strict typing lands on
  source via mypy overrides in NS-6; the tests are a separate project.
- **Regrouping `harness/shared/`** — DEC-020 stands, reaffirmed by DEC-029. A
  regroup needs a superseding entry answering DEC-020's three reasons, and an
  acyclicity test landed first.
- **The closed plan's ceremony items** — R-CQ-13 child spec, R-CQ-15, R-CQ-19,
  R-CQ-20, R-CQ-21's fixture-dedup rule, R-CQ-24, R-CQ-26, R-CQ-27, R-CQ-28,
  R-CQ-31 and AC-31/34/35: inventory or process assertions with no defect
  behind them for a single maintainer. Listed with reasons in the remediation
  plan's §Explicitly not doing.
- **Pre-emptive decomposition of the three files nearest their size budget**
  (`write_policy.py` 448/500, `plan_rules.py` 428, `nemotron-client.ts` 432).
  Headroom exists; a split lands with the change that needs it. Phase B's
  containment slice is the first such change for `write_policy.py`.
- **Raising the `fastapi` floor to ≥0.141.1** (Dependabot #40) until NS-6 lands.
- **A `HEALTHCHECK` in the Dockerfile** — nothing listens; the CMD exits.

---

## 6. Delivered, and removed from the list above

**Closed 2026-09-05 (post #86-#88 status sync):**

| Was | Now |
|---|---|
| **NS-32** Land Phase B of the remediation plan (PR #86) | **Delivered.** PR #86 merged 2026-09-04 (d9ab598). Title understated (`docs(reports): 2026 coding-standards audit`) relative to the Phase B code it shipped; evidence is plan AC-6…AC-22 / AC-33 [x] and DEC-048…DEC-051, not the PR title. |
| **#87 / #88 · DEC-052** LangGraph fail-closed / conclusive counts | **Landed on main** (merges 633f728, 2441547). Fail-closed **in place** under `harness/shared/langgraph/`. Does **not** satisfy R-SR-27 (park + sunset); that remains NS-31 / proposed DEC-053. Spec: `docs/specs/langgraph-fail-open-hardening.md`. |

**Closed on 2026-09-04 by the standards audit and the plan rewrite:**

| Was | Now |
|---|---|
| **NS-20** Turn the mutation-proof procedure into a skill | Landed (`.mango/skills/gate-mutation-proof/`, classified by `test_agent_surface_liveness.py`); it sat in P1 marked "Landed" for a day. The *score* half is NS-35. |
| **NS-14** The entrypoint contract (DEC-029) | Folded into R-SR-29: `[project.scripts]` is the CLI-contract change DEC-029 named, and the mirroring collapse is where the 28 shims go. Two owners (this item and R-CQ-18) disagreed on its dependency; the plan settles it. |
| **NS-15** Split `write_policy.py` by concern | Folded into the plan's "Explicitly not doing": headroom exists (448/500); the split lands with the first change that needs it, which is Phase B's containment slice. |
| **NS-29** as a status mirror | Reduced to a pointer. The paragraph-by-paragraph restatement of the program plan drifted from it on every PR and once counted Phase 0 prerequisites as Phase 1 slices. |

An item that is done does not stay on a roadmap. The peer review's F-4 finding
was that this file listed two already-delivered items as open, which teaches
readers that the entries are decorative; leaving these here after shipping them
would repeat exactly that. Each is stated with the evidence a reviewer can
re-run, not with a checkbox.

**Shipped by `docs/specs/gate-truthfulness.md` (this branch):**

| Was | Now |
|---|---|
| **NS-4** Dependabot contradicted DEC-031 | The `pip` ecosystem is gone from `.github/dependabot.yml`; DEC-033 records why, and that re-enabling it means superseding DEC-031 rather than editing the config. The reopened bot PRs (#62–#73) are left for the maintainer to close. |
| **NS-5** `lint-node` ran in no CI job | A direct prerequisite of `ci`, never of `ci-python`. The blocker on record was wrong: ESLint and Knip passed, and Prettier failed on the digest-pinned `.governance/policy.json`, whose bytes the root-of-trust pins. `harness/node/.prettierignore` resolves it (DEC-034). Confirmed green in CI on `build-full`. This puts R-TDH-23's ESLint `max-lines` rule into a job for the first time. |
| **NS-7** The gitleaks allowlist proved only that its paths existed | `make secrets-allowlist-check` scans with the allowlist removed and fails any entry suppressing nothing. Runs in `secret-scan`, never the unit suite (no gitleaks there, and INV-2 forbids a skip). Deliberate keeps are declared in `.gitleaks.toml` beside the entry. |
| **NS-8** Three agent-surface mutations passed silently | A `SKILL.md` naming a nonexistent `make` target, a persona declaring an authority `agent_authority.py` withholds, and swapped rows in the active→canonical table are each rejected by name. |
| **NS-10** `policy_loader` resolved every threshold and logged nothing | DEBUG record naming key, value and source file; silent at INFO. One `TypedDict` per block, so an unknown key is a mypy error — which immediately surfaced `dict[str, Any]` annotations in `langgraph/policy.py` discarding that checking. |
| **NS-12** Two waiver globs addressed ~135 node ids to approve 4 skips | Narrowed to the classes that carry the skip condition. `test_skip_waiver_scope.py` is the first test to read the shipped registry. |
| **NS-13** Renaming the one live hook silently disabled it | The `.mango/hooks/*.sh` partition is asserted, and `pre-nemotron-run.sh` is pinned by name and by the validator it runs. |
| **NS-16** `complete()` and `stream()` each carried a verbatim copy of the request body, and `top_p` was a literal `0.7` | One `buildChatRequestBody` feeds both call sites, and `top_p` is policy-sourced. Wiring it surfaced the real defect NS-16 understated: the **Python bridge never sent `top_p` at all**, so the two stacks sampled differently against the same endpoint. Both now read `nemotron.top_p` (DEC-036). |
| **NS-3** (gate half) Nothing tied a declared version to a release | `TestTheDeclaredVersionIsARealRelease` requires a matching `## [x.y.z]` changelog section. The *decision* half stays open above. |
| **NS-28** No test invoked `make`, so the new recipes and the workflow's shell had zero end-to-end coverage | `regression/test_gate_truthfulness_e2e.py` runs `make attestation`, `make attestation-check` and `make secrets-allowlist-check` as subprocesses and executes the attestation step's `run:` block read from the YAML with `curl` stubbed — the pipefail claim from DEC-040 is now executed, not asserted. `sampling-parity.test.ts` compares the real Python payload with the real Node body against the shipped policy; reverting `top_p` fails four of nine. |
| **NS-27** The INV-2 suite was sixteen lines from a red budget, and nothing said so | `test_verify_zero_skips.py` (684/700) splits at its own section banner, sharing the runner and fixture via `_zero_skip_harness.py` rather than copying them; the test-function set is unchanged, verified by diff. The budget itself now logs the closest file and its headroom on a passing run — INFO-only, suppressed on failure. A misnamed test (`test_junit_missing_fields`, which used vitest evidence) is renamed for what it asserts (DEC-041). |
| **NS-26** The attestation check judged a snapshot of the PR description, and no re-run could clear it | The payload's `body` is captured when the run is queued, so a corrected description was judged as it had been; `edited` was not a trigger and "Re-run failed jobs" replays the original event, leaving a no-op commit as the only escape; and the env var printed the whole description into the CI log. Now fetched from the API with `pull-requests: read` scoped to `build-full` alone, under an explicit `set -euo pipefail` (DEC-040). |
| **NS-23** The constant inventory was never checked for completeness | `TestTheInventoryIsComplete` discovers module-level numeric constants with `ast` (parsed, not imported) and requires each to be triaged or `EXCLUDED` with a reason; exclusions must still be discovered and must not outnumber the triaged rows. Seven live operational defaults were unlinked — three lock timings, a directory mode of `0o700` that replaced a world-readable default, a substring-redaction floor, a hypothesis-confidence default and a log-preview bound (DEC-039). |
| **NS-24** No gate proved a mermaid diagram could render, and one could not | `AgentMetaTools[... (Context7) [Planned]]` in `c4_architecture.md` ended its label at the first `]`, so the whole agent-topology diagram was an error box on GitHub. `TestEveryMermaidDiagramCanRender` scans every fenced block under `docs/`, `README.md` and `CLAUDE.md`; the detector itself is pinned by a positive and a negative case. |
| **NS-25** The attestation *skill* still carried a second, weaker matcher | DEC-038 made the tool single-source and left the procedure a human follows re-deriving the set with its own `fnmatch` loop, a hard-coded `origin/main`, and `merge-base...HEAD` discovery blind to staged, unstaged and untracked files. The skill now calls `make attestation` / `make attestation-check`. |
| **NS-22** The attestation table the `infra-reviewed` label signs was transcribed by hand, and drifted | `harness/shared/governance/attestation.py` derives it from `validate_invariants`' own matcher and discovery (asserted as symbol identity, so a second implementation cannot appear), and `--check` verifies a PR description against it — failing closed on a missing section, a section with no table, or a mismatch either way. Runs on every pull request in `build-full`, not gated on the label, because the reviewer has to read a verified table *before* deciding. Found by replaying the matcher over an earlier head: a comment on this PR claimed thirteen rows where the set was ten (DEC-038). |
| **NS-9** (bound half) An `omit` entry could drop a file from the floor and raise the aggregate | `coverage_gate.check_measured_set` fails closed on divergence and on an empty set. `mcp_server.py`'s pragma is gone: 94.06% → 94.44%, and 92% on the 3.9 leg where the SDK is absent. The swallow behind the *other* pragma stays open above. |

Every one was mutation-tested against the defect it claims to catch. No test
skip, `xfail` or waiver was added.

**Corrected earlier, from the previous revision of this file:**

- **`@with_authority` / `@budgeted` applied to real nodes.** DEC-022 correctly
  found them unwired and this file said so. They are now applied in
  `harness/shared/langgraph/nodes.py` (lines 58, 87, 105–106, 156, 287, 307)
  against the spec at `docs/specs/langgraph-authority-budget-wiring.md`, whose
  three acceptance criteria are checked and cite passing tests. INV-LG-4 is
  active.

  **Corrected again 2026-09-04 (DEC-052).** "Active" was true of *application*
  and false of *enforcement*: the decorators ran and recorded a denial, and
  nothing read the channel they recorded it into, so a denied planner reached a
  `VERIFIED` verdict over an empty plan. Applied is not enforcing, and the
  three acceptance criteria could not tell the difference because none of them
  ran the compiled graph. `INV-LG-6` supplies the consumer and
  `docs/specs/langgraph-fail-open-hardening.md` carries the reproduction. The
  same shape one level up is why `R-LPW-4`'s policy wiring also did nothing:
  its criteria called the routing functions directly, where an ordinary Python
  default applies, while LangGraph never injected `config` into them at all.
  Two entries in this section have now been corrected for the same reason — a
  criterion satisfied on a path production never takes.
- **The specs-gate template and MUST-bullet refinements.** Both are live in
  `harness/shared/plan_rules.py`: `UNFILLED_TEMPLATE` rejects an unmodified
  scaffold, and `ANY_ID_PATTERN` accepts `AC-*` bullets containing MUST, which
  the old `[CR]-` regex made unsatisfiable (R-PLR-7).

---

## 7. Where the history went

- **Completed milestones v2.1.3 – v2.4.0** —
  [`docs/releases/milestone-history.md`](docs/releases/milestone-history.md),
  moved verbatim 2026-09-03.
- **Per-release narrative** — `CHANGELOG.md`; long release bodies in
  `docs/releases/`.
- **Decisions and their reasoning** — `harness/node/.governance/decision-log.md`.
- **Specifications** — `docs/specs/`, one per non-trivial change.

Two documents cite this file by line number
(`docs/specs/tech-debt-hardening-plan.md`, at what were lines 253 and 258–261:
the "highest-value item" phrasing and the required-status-check list). Those
citations are historical records of a completed change and are left as they
stand; both targets now live in NS-1 above. Line-number citations into a living
document are themselves a drift source — cite a section or an ID instead.
