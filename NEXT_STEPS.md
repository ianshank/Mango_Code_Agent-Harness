# Roadmap & Next Steps: Agentic SSD & Nemotron AI Platform

**Version:** 2.4.0
**Status:** Active roadmap - forward-looking only
**Last reviewed:** 2026-09-07 · `claude/graph-engineering-mango-agent-1ic553` (PR #120) @ `dc42d4c`, DEC-065 landed at `7ff4cd7` — graph-engineering adoption: four derived checks, none of them a new `ci_required_target`; the traceability gate re-scoped from 6 to 412 requirement IDs behind a policy floor and a ratchet, and `make validate` now runs it per-stack **and** repository-scoped so the required check reads the real corpus; `.governance/**` reclassified out of the dormant protected-path set as DEC-056 predicted → what it bounded rather than fixed is **NS-39** · PR #115 merged `origin/main` (#116 DEC-059 NS-37/NS-38); Windows AF_UNIX skip renumbered to DEC-063 · H4 context-window budget moved out of parked (PR #110) · Origin Sync with hypothesis surfacing and **DEC-060** rollback retirement completed (this line said DEC-064; DEC-064 is the Python 3.10 floor — the NS-17/NS-21 rollback pins were retired under DEC-060) · prior peer rewrite against `main` @ `58490c1` (PRs #89-#95 / #93 DECs) · audit in [`docs/reports/2026-STANDARDS-AUDIT.md`](docs/reports/2026-STANDARDS-AUDIT.md) · program plan in [`docs/specs/2026-standards-remediation-plan.md`](docs/specs/2026-standards-remediation-plan.md) · peer review method in [`docs/reports/ROADMAP-PEER-REVIEW.md`](docs/reports/ROADMAP-PEER-REVIEW.md) · deep peer review of agent-memory integrity against `main` @ `6ce45d1` in [`docs/reports/2026-DEEP-PEER-REVIEW-MEMORY-INTEGRITY.md`](docs/reports/2026-DEEP-PEER-REVIEW-MEMORY-INTEGRITY.md) → NS-37 · code generation writing tool spec → NS-38

---

## How to read this file

This file is the single roadmap for the repository, and it contains **only work
that is not yet done**. Completed milestones through v2.5.0 live in
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
| PR-11 | Product | NS-17 open on #97; Copilot: `policy_path` not plumbed into `agent_memory_defaults` / gap injection. | **Closed:** #97 landed `policy_path` + mutation + zero-bound messaging; moved to §6 with NS-34. |
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
not from memory): `build (3.10)`, `build (3.12)`, `build (3.14)`,
`build-full`, `secret-scan`, `dependency-audit`, `dependency-audit (3.10)`,
`dependency-audit (3.12)`, `dependency-audit (3.14)`.

_Updated by `docs/specs/reflection-hardening-increment.md` Step 1/2 /
DEC-064: the Python 3.9 floor moved to 3.10, replacing the `3.9` legs with
`3.14` and retiring `dependency-audit (3.9)`'s `continue-on-error`
carve-out._

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

**Done (3.10 leg).** `docs/specs/python-floor-310.md` (R-RHI-1,
`reflection-hardening-increment.md` Step 1/2) landed: `requires-python`
is `>=3.10`; the forked dependency markers, the 3.9 CI leg, the
`continue-on-error` audit carve-out, `requirements-lock.txt`'s
`--python-version 3.9` header, and `_workflow_paths.UNSUPPORTED_LEG` are
deleted rather than re-homed; mypy is on 2.x with `warn_unused_ignores`;
`DEC-064` supersedes DEC-028.

**Follow-up, dated (not open-ended).** 3.10 itself reaches EOL 2026-10-31.
Before that date: run `make spec NAME=python-floor-311`, re-measuring the
same evidence class this item's original "Why now" ran for 3.10 (runtime
dependency floors, mypy/ruff support windows, any CI matrix leg that would
otherwise ship an EOL-only interpreter) rather than assuming the 3.10 bump's
reasoning still holds unchecked seven weeks later.

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

**Scheduled.** `docs/specs/reflection-hardening-increment.md` Step 3,
implementing `reasoner-bridge-tool-parity.md`'s existing scaffold in place.

**Re-measured 2026-09-07, and the drift now costs more than vocabulary.** The
persona body still enumerates four bridge tools and omits `generate_code`, which
NS-38 added to `NEMOTRON_TOOLS` on #116, while instructing "Always write new
files using `write_file`". Since DEC-065 that instruction names the one write
door that does **not** refuse Python naming a `synthesis.prohibited_imports`
symbol: `generate_code` carries the pre-write refusal, `write_file` is unchanged
by design (C-CGT-2). The persona therefore steers new-file writes away from the
checked door by default. Do **not** patch the list by hand — R-RBT-2 says the
tool inventory must stop living in `.mango/agents/` markdown at all, and a
hand-edit to a protected path buys an attestation for a paragraph this item
deletes. Fix it by landing R-RBT-1/R-RBT-2 so the paragraph is generated from
`tools_for_role(...)`, and add the write-door refusal as an *operating rule*
(R-RBT-2 keeps those in the persona) in the same change.

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

**Depends on.** NS-1 only for the `required_signatures` half of R-SR-24; the
attestation-SHA-binding and Dockerfile/Dependabot-cooldown halves depend on
nothing.

**Scheduled.** `docs/specs/reflection-hardening-increment.md` Step 4, minus
`required_signatures` (that clause stays gated on NS-1).

### NS-39 · Close the three things DEC-065 bounded rather than fixed *(spec exists)*

**Why now.** DEC-065 landed four derived checks and left three residuals **by
name**, so they are visible now rather than discovered by a later reader who
over-trusts a green run.

1. *The traceability gate is green on a ratchet, not on a traced corpus.*
   Re-scoping it from 6 to 412 requirement IDs did not produce a green gate, it
   produced a backlog: **223** contract-spec IDs missing an implementation
   citation, a test citation, or both (222 as the corpus stood, plus R-GEA-5,
   which is deliberately unimplemented and so has nothing to cite). The number
   lives in `traceability.max_uncited_contract_requirement_ids` and may only be
   lowered — a bound, not a fix.
2. *`AC-GEA-8` is the one unticked criterion in the spec.* R-GEA-5 requires a
   recorded tokens-and-tool-calls-per-subagent-turn baseline under `docs/reports/`
   **before** any code-property graph is built, with the build decision comparing
   that baseline against a policy threshold rather than the imported 10× benchmark
   measured on somebody else's corpus (D-3). Nothing records the number, so the
   argument that would settle it cannot be had — adopting first and measuring
   later is the DEC-024 shape.
3. *`execute_generate_code`'s residual bypass is **closed**; this item is
   retained only to record it.* The check once ran on a tree that existed only
   when `validate_syntax=True` **and** the model-supplied `language` resolved to
   Python, so either argument let the agent switch it off. Python-ness is now
   derived from the resolved target suffix and the check runs on every Python
   write regardless of the flag (`tool_executors.execute_generate_code`, PR #120).
   Nothing remains to do here. The reasoning that first accepted it — that closing
   it would widen a protected-path diff — is worth keeping in view: a diff cost is
   not an argument about a security property, and it had been allowed to settle
   one.

**Evidence.** `python3 harness/shared/governance/check_traceability.py --workspace .`
prints the count, the ratchet and the headroom in one line;
`docs/decisions/DEC-065.md` §"Residual, named rather than discovered later" and
§"Not closed here"; `docs/specs/graph-engineering-adoption.md` AC-GEA-8 unticked;
no baseline file under `docs/reports/`; `harness/shared/tool_executors.py`
`execute_generate_code`'s suffix-derived `is_python` gate (the residual item 3
records as closed).

**Done when.**

- The ratchet is **lowered** in a reviewed policy edit with the citations that
  earned each reduction attached. `test_traceability_gaps_are_cited_or_recorded`
  fails when the backlog exceeds the ratchet, and
  `test_the_repository_run_reports_the_count_and_the_headroom` names the lower
  value on every green run — so an allowance that has stopped being needed is
  reported without waiting for a red run · stage `make test-python` / `make validate`.
- A baseline under `docs/reports/` names measured tokens and tool calls for at
  least three recorded subagent turns, and AC-GEA-8's named test
  (`test_code_graph_is_gated_on_a_recorded_baseline`, which does **not** exist
  yet — the criterion is unticked, so `test_spec_selectors_collect.py` does not
  judge it) is written and fails a tree holding a code-property-graph module with
  no such baseline · stage `make test-python`.
- ~~Either `execute_generate_code` decides the prohibited-symbol question on a
  path no model-supplied argument can skip, or a decision record states why the
  `validate_syntax=False` path is accepted.~~ **Done on PR #120.** The first
  branch was taken: `is_python` derives from the resolved target suffix and the
  check runs regardless of `validate_syntax`, with
  `test_code_generation_tool.py::TestNeitherToolArgumentTurnsTheCheckOff` red
  against the old behaviour across all three policy shapes. Only the first two
  bullets of this item remain open.

**Depends on.** Nothing, and **not** NS-2: none of the three touches Phase E or
the LangGraph park. DEC-065 shipped topology verification as a plain test rather
than a gate precisely so the orphan-reviewer defect stays watched while Phase E
waits on the credential rotation.

### NS-29 · The program plans

Pointer only: status is the remediation plan's boxes, read there, not here.
`docs/specs/code-quality-tech-debt-plan.md` is closed at revision 2.
Remediation plan is revision 3 (Phase B Done; R-SR-5 / AC-5 closed; Phase E
gated on R-SR-2). `docs/specs/reflection-hardening-increment.md` is a ledger
increment against the remediation plan's still-open items (NS-6, NS-18, half
of NS-36) — a spec, not a fifth program plan; it does not restate or
re-litigate boxes above, only schedules what a re-measurement against
`33f21044` still found true.

---

## 4. Parked - blocked on a decision or a gate that does not exist yet

| Item | Blocked on |
|---|---|
| **Phase E** (R-SR-26 … R-SR-29) | **NS-2 / R-SR-2 before any destructive slice.** DEC-053…056 (NS-31 / R-SR-5 / AC-5) are logged on #93 - PARK order stands: **JVM → LangGraph → openspec → mirroring**. Do not start Phase E code while the DEC-014 credential branch remains. Premature Phase E inverts DEC-024 (claimed readiness without the hard gate). |
| **NS-19 · NIM multi-model routing / prompt-cache cost** | No spec; `complete_chat` has no provider boundary (`stream: False` hard-coded, `usage` discarded). Phase F boundary first. |
| **HITL interrupts** | Needs an explicit non-graph design under DEC-053 PARK (in-graph interrupts stay with a revival DEC). Context-window budget (audit H4) is no longer parked — see §6 / PR #110. |
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

**Closed 2026-09-07 (DEC-059 / agent-memory integrity NS-37 & code generation writing tool NS-38):**

| Was | Now |
|---|---|
| **NS-37 · Close the raw-write bypass of `hypothesis_register` / `knowledge_gap_log`** | **Delivered on PR #116.** `write_policy.write_denial_reason` denies direct raw writes to `.mango/memory/**` across `write_file`, `apply_patch`, `generate_code`, and `run_command` shell redirects under both workspace-scoped and install-root resolution modes. Regression suite `test_memory_integrity_regression.py` asserts well-formed forgeries are refused and store is byte-for-byte unchanged. Memory store remains excluded from `protected_paths` to preserve digest baseline validity. Decision DEC-059. |
| **NS-38 · Dedicated code generation writing tool with syntax validation** | **Delivered on PR #116.** `generate_code` writing tool added to `NEMOTRON_TOOLS` and `agent_authority.TOOL_REQUIRED_ACTION` (`write`), implemented in `tool_executors.py` and `dispatcher.py`. Provides pre-write AST parsing for Python and JSON decoding for JSON, workspace confinement, write policy checks, overwrite guard, and structured logging. Tested via `test_code_generation_tool.py`. Spec `docs/specs/code-generation-tool.md`. Decision DEC-059. |

**Closed 2026-09-05c (Windows portability hardening):**

| Was | Now |
|---|---|
| **Windows parity** RCA-1 -> RCA-11 | **3 417 passed, 133 expected skips, 0 failures** on Windows dev. DEC-063 (AF_UNIX), DEC-061 (make guards), DEC-062 (asyncio self-pipe). `test_windows_portability_regression.py` expanded to enterprise AQA. `pyrightconfig.json` added for IDE parity. NS-17/NS-21 temporary rollback regressions retired via **DEC-060** after origin re-landed the forward feature (this row said DEC-064; `docs/decisions/DEC-060.md` is the record that retires those pins, and DEC-064 — added later, on #118 — is the Python 3.10 floor). |

**Closed 2026-09-06 (DEC-058 / hypothesis surfacing, phase 2 of DEC-057):**

| Was | Now |
|---|---|
| **Phase 2 · Surface open hypotheses to the reasoner** (parked on an exposure limit and the eviction proof) | **Landing on PR #114** (spec landed first on #113). `REASONER_PROMPT_TEMPLATE` gains `{open_hypotheses}`, filled by `memory_view.format_hypotheses_for_reasoner`; bounded by `agent_memory.reasoner_hypothesis_limit` / `reasoner_hypothesis_budget_tokens` (fail-closed, `0` = kill switch); coexistence with `context_policy` eviction and the oversized-block degenerate case pinned; `C-HR-2` narrowed to `C-HS-1`. Spec `docs/specs/hypothesis-surfacing.md` (peer-reviewed rev 2), record DEC-058. Audit M4 fully remediated. |

**Closed 2026-09-06 (audit H4 / context-window budget):**

| Was | Now |
|---|---|
| **Context-window budget** (parked with HITL) | **Landing on PR #110.** Policy keys `orchestrator.context_budget_tokens` / `context_chars_per_token`; pure `harness/shared/context_policy.py` group-atomic eviction; `ExecutionLoop` applies on a copy before `complete_chat` and logs `event=context_policy`. Spec: `docs/specs/context-window-budget.md`. HITL remains parked above. |

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

**Closed 2026-09-05d (NS-34 / NS-17):**

| Was | Now |
|---|---|
| **NS-34** Decision records as records | **Landed on PR (this change).** One file per decision under `docs/decisions/` with YAML frontmatter (`status`, `supersedes`, …); generated `index.md` / `index.json`; `validate_governance_docs` fails on missing status, index drift, or skill restatement; skill points at the index; thin legacy `decision-log.md` retains DEC ids for `--decision-log` consumers. |
| **NS-17** Agent memory retention / scoping | **Landed on PR #97.** Policy-bounded FIFO retention via active `policy_path`, workspace-scoped `.mango/memory`, planner `{open_gaps}` injection, zero-bound fail-closed messaging + mutation tests. |

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
- **Decisions** - `docs/decisions/` (index in `docs/decisions/index.md`; NS-34).
- **Specifications** - `docs/specs/`; Phase B / R-SR-5 status boxes in
  `2026-standards-remediation-plan.md` (revision 3).

Cite section IDs (`NS-1`, `R-SR-1`), never line numbers into this living file.
