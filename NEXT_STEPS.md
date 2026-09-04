# Roadmap & Next Steps: Agentic SSD & Nemotron AI Platform

**Version:** 2.4.0
**Status:** Active roadmap — forward-looking only
**Last reviewed:** 2026-09-03 · findings in [`docs/reports/ROADMAP-PEER-REVIEW.md`](docs/reports/ROADMAP-PEER-REVIEW.md)

---

## How to read this file

This file is the single roadmap for the repository, and it contains **only work
that is not yet done**. Completed milestones through v2.4.0 were moved verbatim
to [`docs/releases/milestone-history.md`](docs/releases/milestone-history.md) on
2026-09-03; the narrative of what shipped lives in `CHANGELOG.md` and
`docs/releases/`. Before that move, 496 of this file's 533 lines were history,
and eight open items were buried inside it under `🚧` headings — the roadmap
could not be read as a roadmap.

Every item below carries four fields, and an item without them is not ready to
be worked:

- **Why now** — the consequence of not doing it, not a restatement of the title.
- **Evidence** — a command, a file reference, or an API result that a reviewer
  can re-run today. This file follows the same rule as the rest of the
  repository: a claim in prose is not evidence (DEC-024).
- **Done when** — a falsifiable acceptance criterion.
- **Depends on** — the item that must land first, or `nothing`.

Priorities are an ordering, not a schedule. P0 items are ordered relative to
each other; everything in P1 is unblocked and may be taken in any order.

**Spec discipline.** Items marked *(spec required)* change behaviour, policy, or
a protected path, and per `CLAUDE.md` must not be implemented without a spec:
`make spec NAME=<feature>`, peer-reviewed with the `openspec-peer-review` skill,
then `make pre-pr`. Items not so marked are contained enough to go straight to a
PR with the usual gate evidence.

---

## 1. P0 — the repository's guarantees do not hold until these land

### NS-1 · Apply the branch ruleset to `main`

**Why now.** Every gate in this repository is advisory. `main` accepts a direct
push and a merge with no passing check and no review, which makes the coverage
floors, the fail-closed policy loaders, the zero-skip evidence hooks and the
secret scan a matter of author discipline rather than enforcement. This has been
the top item since v2.1.9, was independently re-flagged by an external analysis
(DEC-018), and has outlived four releases. It is a repository-settings change,
not code — which is exactly why nothing in CI can nag about it.

**Evidence.** The GitHub branches API reports `"protected": false` for `main`
(checked 2026-09-03). PR #75 merged on 2026-09-03 with one bot review and no
human approval. Three merges since 2026-08-31 left `main` red on its own head
(workflow runs 286, 319, 326); DEC-024 records the same failure on PR #60. The
ruleset to import is committed at `.github/rulesets/main.json` and is pinned to
the workflow by `test_ci_gate_required_checks.py`.

Required status checks (derived from `.github/workflows/python-package.yml`,
not from memory): `build (3.9)`, `build (3.10)`, `build (3.12)`,
`build-full`, `secret-scan`, `dependency-audit`, `dependency-audit (3.9)`,
`dependency-audit (3.10)`, `dependency-audit (3.12)`.

**Done when.** Settings → Rules → Rulesets → New ruleset → Import
`.github/rulesets/main.json`, and the branches API reports `"protected": true`
for `main`. If the decision is *not* to apply it, that is a legitimate answer
for a single-maintainer repository — but it must be recorded as a decision-log
entry, and this item is then closed as declined rather than left open for a
fifth release.

**Depends on.** Nothing.

### NS-2 · Rotate the credential DEC-014 documents, then purge and re-verify

**Why now.** DEC-014 states plainly that the branch `feature/governed-run-console`
"carries a real leaked key". The remediation recorded there was to scope
`gitleaks git` to `--log-opts="HEAD"` so a PR's gate only scans its own
ancestry. That fix is correct on its own terms — a PR author cannot action a
secret on someone else's branch — but it silenced the finding without ever
retiring the credential. DEC-014's accepted consequence was that the secret
"remains caught the moment that branch's own PR is opened"; no PR has been
opened, the branch is still on the remote, and nothing tracks it. A scanner
narrowed until it stops reporting a known live secret is the failure class
DEC-024 exists to name, applied to INV-1.

**Evidence.** `git ls-remote --heads origin feature/governed-run-console`
returns `5970249…` (2026-09-03). Searching `docs/`, `CHANGELOG.md` and
`harness/node/.governance/decision-log.md` for rotation, revocation or history
rewriting returns nothing about this key. `Makefile:177` and both per-stack
mirrors pass `--log-opts="HEAD"`, so no scheduled job scans that ref.

**Done when.** The credential is rotated at the provider (do this first —
rewriting history does not un-leak a key that was pushed), the branch is deleted
or its history purged, and a decision-log entry records the rotation date and
the scanning gap that let it sit. Then confirm: a full-history scan
(`gitleaks git . --log-opts="--all"`, run once by hand — not wired into `make
secrets`, which must stay ref-scoped per DEC-014) reports clean.

**Depends on.** Nothing. Do not wait for NS-1.

> Deliberately terse: this item names no path, no key shape and no commit. The
> detail already sits in a public decision log, which is itself part of the
> finding.

### NS-3 · Settle the release identity, then tag it

**Why now.** The repository does not agree with itself about what version it is.
The last merge commit and `docs/rca/e2e_origin_sync_triage_rca_v2.5.0.md` say
v2.5.0; `pyproject.toml`, `README.md`, `CHANGELOG.md` and this file say 2.4.0.
`CHANGELOG.md` has no entry of any kind for the work PR #75 merged — the MCP
tool-schema fix, the live-E2E stabilisation and the Node client hardening are in
the tree and in an RCA, but not in the changelog. And no git tag has ever
existed, so "2.4.0" names no commit. `test_documentation_truth.py` pins the four
version mirrors to each other and passes today, which is precisely why this
drift is invisible: nothing pins a *release* to a changelog entry or a tag.

**Evidence.** `git tag -l` and `git ls-remote --tags origin` are both empty.
`grep -n "2\.5\.0" CHANGELOG.md` returns nothing. The four mirrors agree on
2.4.0 and the suite is green with the RCA claiming otherwise.

**The gate is now in place; the decision is not.**
`test_documentation_truth.TestTheDeclaredVersionIsARealRelease` asserts that the
version `pyproject.toml` declares has a matching `## [x.y.z]` section in
`CHANGELOG.md` (R-GT-9). It passes today because 2.4.0 has one — so it constrains
whichever answer is chosen without choosing it.

**Done when.** Either the four mirrors move to 2.5.0 with a `## [2.5.0]`
changelog section covering PR #75, or the RCA is renamed to the version it
actually documents — and either way an annotated tag exists at the release
commit. Only a person can decide which; the drift is a fact, the resolution is a
judgement about what PR #75 was.

**Depends on.** Nothing.

---

## 2. P1 — unblocked, take in any order

### NS-6 · Move the Python floor to 3.10 *(spec required)*

Python 3.9 reached upstream end-of-life in October 2025. Holding the floor costs
three carve-outs, each currently recorded rather than hidden: the per-file
coverage waiver for `harness/shared/langgraph/**` on the leg that cannot install
the extra (`coverage.optional_extras`), a forked pytest pin (9.0.3 on ≥3.10 for
PYSEC-2026-1845, 8.4.2 below), and a `continue-on-error` dependency-audit leg
carrying unpatchable CVEs (DEC-017). `fastapi` ≥0.141, `langgraph` and `mcp` are
all 3.10+. Moving the floor retires all three at once and unblocks NS-14. **Done
when** `requires-python` is `>=3.10`, the CI matrix drops the 3.9 legs, the three
carve-outs are deleted rather than re-homed, and the suite is green on the
remaining legs. This is a compatibility-breaking decision for adopters: it needs
its own spec and a decision-log entry. **Depends on** nothing (blocks NS-14).

### NS-9 · Justify the last pragma, and stop the swallow behind it

**Mostly delivered** by `docs/specs/gate-truthfulness.md` (R-GT-3). The
measured-set bound is live: `coverage_gate.check_measured_set` fails closed when
the report's file set diverges from the on-disk first-party set, so an added
`omit` entry can no longer drop a file from the per-file floor while raising the
aggregate. `mcp_server.py:16`'s pragma is gone; the file measured 94.06% before
and 94.44% after.

What remains is `langgraph/__init__.py:52`, and it is not a one-line change.
Removing the pragma alone leaves the `except ImportError: pass` arc unreachable
wherever langgraph *is* installed, taking the file to 80% against a 90% floor —
red on the 3.10 and 3.12 legs. The defect worth fixing is the swallow itself: a
real failure to import `graph.py` currently degrades silently to "`build_graph`
just isn't exported". Deleting the `try`/`except` fixes that and reads 7/7 where
langgraph is installed, but 5/7 on a local run without the extra and without
`MANGO_CI_DESELECT_LANGGRAPH=1` — no waiver applies there, so it would be a red
gate on a contributor's first `make ci`.

**Done when** the swallow is gone and both cases are measured on a machine with
the extra installed. `harness/shared/langgraph/**` is a protected path, so this
carries an attestation. **Depends on** nothing, but do not fold it into a batch:
its failure mode lands on whoever has not installed the optional extra.

### NS-11 · Reconcile the regression tier with the contract it claims

`harness/CONTRACT.md` defines `harness/shared/tests/regression/` as one
reproduction per defect that reached `main`, run standalone by
`make test-regression`. Several excellent reproductions for recently fixed
defects — the coverage-gate shadowing probe in `test_coverage_gate.py`, the
session-hook `pytester` run in `test_session_hooks.py` — sit in the unit tier
instead, so `make test-regression` runs none of them. **Done when** either they
move (each naming its pre-fix commit, as
`regression/test_write_containment_regression.py` does) or the contract stops
calling that target a per-defect gate. The contract currently states a guarantee
the directory does not provide. **Depends on** nothing.

### NS-14 · The entrypoint contract (DEC-029)

31 `sys.path` bootstrap sites in four styles, accepted as-is because a helper
would need the bootstrap it replaces and the per-stack scripts are digested
root-of-trust artefacts. DEC-029 defers this explicitly to "when the 3.9 floor
moves". **Depends on NS-6** — it is a follow-on, not an independent item.

### NS-15 · Split `write_policy.py` by concern

381 lines, under the 500-line `limits.size_budget_lines` budget — so this is a
cohesion item, not a budget violation, and it should be scheduled as one. Split
into distinct boundary and invariant validators. **Depends on** nothing.

### NS-17 · Retention policy for the agent memory directory

Persistent storage for knowledge-gap logs exists via the `agent-memory-manager`
skill, which declares retention as its responsibility. No retention or periodic
summarisation is implemented, so context grows unbounded across sessions.
**Done when** a bounded policy is sourced from `governance-policy.json` and
enforced, with the bound tested. **Depends on** nothing.

### NS-18 · Connect the reasoner to the MCP server *(spec required)*

The first product item that is genuinely unblocked: `mcp_server.py` shipped in
v2.3.0, and `.mango/agents/nemotron-reasoner.md` still never mentions it — the
persona's tool guidance describes the direct bridge only, and no
`mcp-server-integration` skill exists. **Done when** the persona names the MCP
path, a skill documents it, and a test asserts the persona's declared tools
match what the server exposes. **Depends on** nothing, but do it after the P0
block: it changes the agent control surface, a protected path.

### NS-20 · Turn the mutation-proof procedure into a skill

Every gate added in the `gate-truthfulness` batch was validated the same way:
mutate the thing the gate claims to catch, assert the gate fails, restore the
tree, assert it passes. That loop ran **more than ten times by hand** in one
change — delete `.prettierignore`; drop `lint-node` from `ci`; add it to
`ci-python`; add `write_file` to the verifier persona; swap two mapping rows;
fabricate a `make` target inside a fenced block; delete the live hook; rename it
to snake_case; plant an orphan hook; restore the pre-narrowing waiver registry.
It also caught two defects in the batch's *own* gates that no test would have
found: a `[tool.coverage.run]` table as the last table in `pyproject.toml`
matched nothing, and a `# keep:` comment anywhere in `.gitleaks.toml` granted an
exemption.

A repeated manual procedure with a mechanical shape and a history of finding
real defects is the definition of a skill this repository already uses
elsewhere (`tech-debt-audit` codified exactly this kind of recurring review).
**Done when** `.mango/skills/gate-mutation-proof/SKILL.md` states the procedure,
including the two failure modes it must warn about — a mutation that leaves the
tree dirty (`git checkout` cannot restore an untracked file, which happened
here), and a "proof" run against a stale artifact — and
`test_agent_surface_liveness.py` classifies it. **Depends on** nothing.

### NS-21 · The hook surface has one live hook and no loop

Five of six `.mango/hooks/` scripts are dormant by DEC-003, and the sixth
(`pre-nemotron-run.sh`) is the only hook on a live product path. NS-13 now
asserts the partition and pins that hook, so the surface is *described*
accurately for the first time — which makes the gap visible rather than closing
it: three of the four names in `PERMITTED_HOOK_NAMES`
(`post-planner-run`, `post-nemotron-reasoner-run`, `post-verifier-run`) have no
script on disk, so `ExecutionLoop` fires them into `hook_path.exists()`'s false
branch on every agent turn. That is by design today, and it means the loop has
no post-turn observation point at all.

Two candidates, both needing a decision rather than code first:

- **A post-turn hook that records the turn's verdict and tool-call count.** The
  data already exists in `ExecutionLoop`; nothing persists it per turn, so
  "which turn exhausted the budget" is answerable only from logs that are not
  kept. This is the cheapest real use of the dormant namespace.
- **Waking the five dormant scripts** would change tool-call behaviour for every
  session on logic that has never executed. DEC-003 declined this deliberately;
  reversing it needs a superseding entry, not an edit to `.mango/settings.json`
  — which is not the file Claude Code reads anyway.

**Done when** either a post-turn hook exists with a test that fails when it stops
being fired, or a decision-log entry records that the post-`*`-run namespace
stays empty and why — so the three unfired names stop reading as an oversight.
**Depends on** nothing.

### NS-29 · Audit round 3: the code-quality and hardening plan *(spec exists)*

**Why now.** Round 2 (`docs/specs/tech-debt-hardening-plan.md`) closed all 29 of
its boxes and left the gates green and advisory. The third audit, peer-reviewed
into revision 2, found the product path bypassable: `cat .en?` and process
substitution classified as `read` for every role, the write side had no
credential-file rule so a patch to `.env` redirected the API key on the next call,
and the modules that enforce this were agent-writable. Those four are closed —
Phase 1 landed R-CQ-3..R-CQ-7 and R-CQ-30, and adversarial re-review closed three
more spellings the first fix missed (quoting and backslash escaping, brace
expansion, then parameter expansion and ANSI-C quoting) plus a second write door
that derived its action from a synthesised command. A follow-up closed R-CQ-8
(DEC-043): every Python policy reader now fails closed on a *present* policy
missing a key, `protected_paths` and `limits` lost their permissive defaults,
the three size-budget environment overrides may only tighten a budget, and
`verify_zero_skips` resolves its grammar on first use rather than at import.
**Phase 1 is now complete; the plan is not** — phases 2–7 are untouched, so the
actions are still unpinned, the lock carries no hashes, the `make` stage the
shim test cites still does not exist, and five landed specs still show every
acceptance box open.

Behind that, unchanged: the two stacks disagree about which HTTP statuses to
retry, no GitHub Action is SHA-pinned although `harness/CONTRACT.md` requires it
of adopters, the lock carries no hashes, a `make` stage the shim test cites does
not exist, and five landed specs show every acceptance box open again. The
committed ruleset (NS-1) cannot be applied as it stands: one required code-owner
approval, no bypass actor, one code owner.

**Evidence.** `docs/specs/code-quality-tech-debt-plan.md`, problem items 1–16 and
the Review record, each with the file, line or command that reproduces it on
`487870a`; the four bypasses were reproduced by running the real `classify`,
`write_denial_reason` and `execute_apply_patch`. Each is now pinned by an
end-to-end reproduction in
`harness/shared/tests/regression/test_credential_containment_regression.py`,
whose premise test runs every credential-read spelling through a real `bash -c`
so the suite fails if a spelling stops reaching the file it claims to reach.

**Done when.** Its 35 acceptance boxes are ticked, each by the command it names;
8 are ticked (all of Phase 1). Phase 0 decides the ruleset shape, rotates the NS-2 credential,
dispositions the Dependabot queue and lands NS-20 (landed:
`.mango/skills/gate-mutation-proof/`); Phase 1 is the product path; the rest is
ordered there.

**Depends on.** NS-2 (rotation) before any Phase 1 slice merges; NS-20 (the
mutation-proof skill) is written in Phase 0; NS-3 (a settled release) before the
shim removal clock in Phase 4 and the `control-plane` shim directory in Phase 6.

### NS-19 · NIM multi-model routing and prompt-cache cost tracking *(spec required)*

Dynamic model fallback (fast reasoning → deep synthesis) and a local prompt-cache
adapter to cut repeated token cost on invariant-verification prompts. Both are
still one-line roadmap ambitions with no spec, no owner and no acceptance
criteria; neither should be started until one exists. **Depends on** nothing
mechanical — only on someone deciding it is worth the spec.

---

## 4. Parked — blocked on a gate that does not exist yet

These are not backlog items. Each is blocked on something specific, and naming
the blocker is the point: without it, they resurface every audit.

| Item | Blocked on |
|---|---|
| **LATS end-to-end wiring into the supervisor StateGraph** | `synthesis.lats_enabled` is `false` and INV-15 requires passing an ablation gate first. No ablation result exists. `lats_optimizer.py` is parked under `harness/shared/experimental/` with zero runtime callers (DEC-027). |
| **Autonomous healing triggered by test-suite failure** | The lifecycle hooks it would bind to are dormant by DEC-003, and `.mango/settings.json` is not the file Claude Code reads. NS-13 is the prerequisite that would make a hook namespace trustworthy. |
| **`AC-CE-1` — capability-profile enforcement in `ProcessBackend`** | The production broker does not enforce capability profiles; the passing tests simulate the violation in a mock. Open in `openspec/changes/add-neurosym-governed-synthesis/`, needs the versioned profile schemas under `harness/control-plane/capability-profiles/` first. |
| **`harness/jvm/` CI parity** | Declared an unadopted reference template with no live CI enforcement. Bringing it to parity is substantially larger than labelling it, and nothing depends on it. |

---

## 5. Explicitly not doing

Recorded so a future audit does not rediscover them as findings:

- **Annotating the test suite** (`--disallow-untyped-defs` reports 533 findings,
  essentially all `no-untyped-def` on test functions). A separate project, not a
  hygiene item.
- **Regrouping `harness/shared/`** — DEC-020 stands, reaffirmed by DEC-029. A
  regroup needs a superseding entry answering DEC-020's three reasons, and an
  acyclicity test landed first.
- **Deleting the 20 per-stack shim scripts** — they are root-of-trust artefacts;
  DEC-004 sizes removal as a rotation. R-TDH-21 keeps them.
- **Raising the `fastapi` floor to ≥0.141.1** (Dependabot #40) until NS-6 lands;
  fastapi 0.141 requires 3.10 and would break the 3.9 leg today.

---

## 6. Delivered, and removed from the list above

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
