# Roadmap & Next Steps: Agentic SSD & Nemotron AI Platform

**Version:** 2.5.0
**Status:** Active roadmap - forward-looking only
**Last reviewed:** 2026-09-09 · `origin/main` is PR #127 (`3e8d69d`). INV-13 evidence + protocol/routing, NS-18 tool parity, NS-36 minus signatures, and NS-39 ratchet/citations/AC-GEA-8 are on `main`. This change lands the capability probe (AEI step 6 / AC-12) and the AQA-007 vocabulary pin. Owner P0 (NS-1 ruleset, NS-2 credential purge, NS-3 tag, NS-30 licence) is unchanged and still hard-gates Phase E. Remaining INV-13 work is the isolation decision and backend (spec steps 7–9), not a new NEXT_STEPS row. CONTRACT Python floor is 3.10 (DEC-064). AC-CE-1 is retired (isolation spec steps 6–9).

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

### 2026-09-07 third peer-rewrite findings (verified)

| ID | Severity | Finding | Effect on this file |
|---|---|---|---|
| PR-13 | **Blocker (architecture)** | `harness/shared/tests/test_mcp_server.py` reached 696 lines against 700 limit (4 lines headroom); `harness/shared/langgraph/nodes.py` reached 482 lines against 500 limit (18 lines headroom). | Decomposed `test_mcp_server.py` into lifecycle and dispatch modules with `_mcp_helpers.py` doubles; decomposed `nodes.py` into `node_reasons.py`, `node_executors.py`, and `nodes.py` facade. All modules now < 300 lines with > 65 lines headroom repository-wide. |
| PR-14 | Major | Regression test pins (`test_scripts_hook_shims.py`, `test_gaps_memory_integrity.py`, `test_scan_findings_windows_waiver.py`) carried silent `pytest.skip()` calls when target files were missing, violating zero-skip policy. | Replaced skips with strict assertions; added dynamic `REPO` bootstrapping and `if __name__ == "__main__":` entrypoint runners for IDE execution. |
| PR-15 | Minor | Agent skills for god-file decomposition and regression pin authoring lacked codification in `.mango/skills/`. | Authored, validated, and registered `god-file-decomposer` and `regression-pin-author` skills. Both landed unclassified and undated and broke `main` (run 34172364840); fixed in PR #123. The original row also named `.agents/skills/`, a directory that does not exist and that `test_no_skill_directory_exists_outside_dot_mango` forbids. |

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

_What "advisory" cost, measured on 2026-09-07 (PR #120)._ A bot-authored commit
`c331e47` became the PR head and produced **two** check runs — the authoring
app's own job and a deployment card — where the human-authored pushes on either
side of it each produced nine. That head failed `make validate` on three Size
Budget entries and failed the suite (`2 failed, 4238 passed`), and none of it
appeared on the pull request. With the ruleset applied, nine required contexts
with no report would have held the merge; with no ruleset, there was nothing to
hold it. This is the first incident on record where the gap between "the gates
pass" and "the gates ran" was demonstrated rather than argued, and it is an
argument for this item, not for a new one (see NS-40, folded).

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


### NS-35 · A mutation score instead of mutation prose *(spec required)*

**Why now.** `gate-mutation-proof` is a by-hand loop whose CHANGELOG claims are
unverifiable (audit H9 / DEC-024).

**Evidence.** `.mango/skills/gate-mutation-proof/SKILL.md`; no `mutmut` in lock.

**Done when.** `mutmut` runs nightly over named governance modules; policy key
`mutation.min_score`; job fails below it.

**Depends on.** NS-6.

### NS-36 · Phase D of the plan: CI truthfulness — `required_signatures` only *(spec exists)*

**Why now.** Attestation SHA binding, Dockerfile digest+USER, Dependabot
`cooldown`, and the scheduled `/rules/branches/main` probe landed on PR #124.
The remaining half of R-SR-24 is `required_signatures` on `main`, which needs
NS-1 (the ruleset is not imported). Dependabot already has the `docker`
ecosystem; the stale "lacks docker" wording is retired.

**Evidence.** `.github/rulesets/main.json` still has no `required_signatures`.

**Done when.** NS-1 imports the ruleset with `required_signatures` (owner).

**Depends on.** NS-1.

**Scheduled.** `docs/specs/reflection-hardening-increment.md` Step 4 remainder.

### NS-39 · Keep lowering the traceability ratchet *(spec exists)*

**Why now.** AC-GEA-8 (baseline + `test_code_graph_is_gated_on_a_recorded_baseline`)
and the generate-code / size-budget residuals closed on PR #124. The gate is
still green on a ratchet, not on a fully cited corpus. `R-GEA-5` stays uncited
on purpose. Lower `traceability.max_uncited_contract_requirement_ids` in the
same policy edit as the citations that earned it; never raise it. Live count
is what `make validate` prints — do not restate it here.

**Done when.** Headroom is zero after each citation batch, and the accepted
ceiling in `test_traceability_scope.ACCEPTED_RATCHET_CEILING` moves with the
policy (C-GEA-4).

**Depends on.** Nothing.


### NS-40 · The bot-push incident is evidence for NS-1, not a separate item *(no spec; folded)*

**Status: folded into NS-1.** This item was opened with the wrong mechanism and
is retained to record the correction rather than deleted, because the wrong
version was quoted in PR #120's description. (An earlier draft of this paragraph
also claimed it was quoted in a decision record. It was not — `DEC-065` does not
mention NS-40. That sentence was written without checking, in the paragraph
withdrawing an item for a claim written without checking, and is corrected here
rather than silently fixed.)

**What was claimed.** That a required status check which was never created reads
as *pending* rather than failing, so a branch ruleset cannot block on it and
`absent` renders identically to `passing` on the merge button.

**Why that is wrong.** GitHub's required status checks *do* block on an absent
report — an unreported required context shows as "Expected — waiting for status
to be reported" and holds the merge. The claim was asserted with no run cited,
which is the DEC-024 shape, in an item written about the DEC-024 shape. A peer
review of the drafted spec caught it (Product Manager, P1) and the structural
reason is stronger than the review's: **NS-1 records that
`GET /repos/…/rules/branches/main` returns `[]`.** No ruleset is applied, so
nothing is required, so there was never a required check to be pending. The bot
head read green because **every gate here is advisory** — which is NS-1's
opening sentence, and NS-1 is P0 and blocked on a person.

**What the incident is actually good for.** It is the concrete cost of NS-1
staying open, and belongs in NS-1's evidence: on PR #120, `c331e47` became the
head, produced **two** check runs (the authoring app's own job and a deployment
card) where the neighbouring human-authored pushes each produced nine, and
failed `make validate` on three Size Budget entries and the suite
(`2 failed, 4238 passed`) — with none of it visible on the pull request. That is
what advisory gates cost, measured rather than argued.

**The residual, if any.** Once the ruleset is applied, the merge button is
protected and the remaining question is only reviewer *visibility* — whether a
person scanning a short green list is prompted to ask which runs are missing.
That is a smaller item than this one claimed to be, it overlaps **NS-36**
(Phase D, CI truthfulness), and it should not be opened until NS-1 lands and the
residual can be measured instead of predicted.

**What was tried and withdrawn.** A spec (`required-run-presence.md`) and a pure
verdict module were drafted, then removed unlanded. Four of this repository's own
gates rejected them — the traceability ratchet (8 uncited requirement IDs),
`validate_plan` (4 orphan requirements), mypy, and
`test_verdict_literals` (restating status names the repo names once) — and all
four `openspec-peer-review` personas refused signoff. The review's closing
prediction was that the tests would be written to make the ratchet arithmetic
work rather than to prove the property, naming `C-RRP-3` — a clause asserting
the spec does not overclaim — as the one that would end up cited by a test
asserting nothing. That test had already been written when the review arrived.
The gates and the review agreed, and the item was withdrawn rather than argued
past.

### NS-29 · The program plans

Pointer only: status is the remediation plan's boxes, read there, not here.
`docs/specs/code-quality-tech-debt-plan.md` is closed at revision 2.
Remediation plan is revision 3 (Phase B Done; R-SR-5 / AC-5 closed; Phase E
gated on R-SR-2). `docs/specs/reflection-hardening-increment.md` is a ledger
increment against the remediation plan's still-open items (NS-6, half
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

**Closed 2026-09-09 (INV-13 step 6 / AC-12 host inventory):**

| Was | Now |
|---|---|
| **INV-13 step 6 · host capability probe** | **Landed (PR #128).** Stdlib-only `capability_probe.py`; `make validate` prints `--json`. Vocabulary is `enforced`/`absent`/`undetermined` (not `IsolationState`). Pinned by `test_capability_probe.py` and AQA-007. Remaining INV-13 work is steps 7–9. |

**Closed 2026-09-08 (PR #124 on `main`: INV-13 evidence + protocol, NS-18):**

| Was | Now |
|---|---|
| **NS-18 · Connect the reasoner persona to what the bridge exposes** | **Landed on PR #124.** `format_tools_paragraph` is generated from `tools_for_role`; YAML frontmatter is stripped before the Nemotron prompt; `model_call` logs `prompt_sha`; `generate_code` is the write door named in the persona. Spec `docs/specs/reasoner-bridge-tool-parity.md` AC-1…AC-5. DEC-068 names `MIN_MESSAGES_BEFORE_FALLBACK`. |
| **INV-13 steps 3–5** | **Landed on PR #124.** Broker-injected signing key, digest-of-digests over the loop baseline, sink outside workspace/`protected_paths`; `ExecutionBackend` protocol + `ProcessBackend` adapter; `policy_loader` split; `execution.routing` `brokered`/`refuse`. Sandbox digest still unattestable (steps 7–9). |
| **`AC-CE-1` ProcessBackend capability profiles** | **Retired.** Isolation spec steps 6–9 supersede the parked row. |

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

**Closed 2026-09-07 (v2.5.0 Origin-Sync, Hook Shims, DEC-064 & Live E2E):**

| Was | Now |
|---|---|
| **HOOK-1** Missing hook shim scripts | **Landed.** Created `scripts/verify-tier-a.sh` and `scripts/guard-forbidden-paths.sh` with dynamic Makefile/validate_invariants delegation; tested by AQA-001 `test_scripts_hook_shims.py`. |
| **RCA-7** RecordingBackend probe xdist isolation | **Landed.** Overrode `_probe()` in `RecordingBackend` to return `True` unconditionally, eliminating 17 spurious parallel test failures on Windows; pinned by AQA-006 `test_process_backend_isolation_regression.py`. |
| **MEM-1 (DEC-066)** Stub corruption in gaps memory | **Landed.** Pruned 199 corrupt stub records from `.mango/memory/gaps.json`, preserving 24 substantive entries; documented in `docs/decisions/DEC-066.md` and pinned by AQA-004 `test_gaps_memory_integrity.py`. |
| **Tier 5 Live Nemotron E2E** Real NIM verification | **Landed.** Full live E2E and smoke suites verified against live NVIDIA Nemotron NIM endpoint across Python and Node/Vitest; resolved Windows console charmap encoding and DEC-026 zero-skip governance attribution. |

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
