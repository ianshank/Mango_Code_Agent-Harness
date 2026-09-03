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

**Done when.** Either the four mirrors move to 2.5.0 with a `## [2.5.0]`
changelog section covering PR #75, or the RCA is renamed to the version it
actually documents — and either way an annotated tag exists at the release
commit. Add the missing gate in the same change: extend
`test_documentation_truth.py` so the declared version must have a matching
`## [x.y.z]` section in `CHANGELOG.md`. That is the assertion whose absence
allowed this.

**Depends on.** Nothing.

---

## 2. P1 — unblocked, take in any order

### NS-4 · Resolve the Dependabot contradiction (DEC-031)

DEC-031 closed PRs #38–#46 as superseded by the universal lock and named the
weekly `lock-upgrade-check` job the Python upgrade signal from then on.
`.github/dependabot.yml` still enables the `pip` ecosystem, so twelve bot PRs
reopened on 2026-09-02 (#62–#73), including a `mypy` 1.11 → 2.3 major bump that
no lock-driven process asked for. The config and the decision cannot both be
right. **Done when** the `pip` ecosystem is removed from `dependabot.yml` (the
`github-actions` and `npm` ecosystems stay — R-TDH-10 wants the action majors
moving), the reopened pip PRs are closed citing DEC-031, and #62–#66 are merged
as one batch. **Depends on** nothing.

### NS-5 · Wire `lint-node` into `ci`

The blocker DEC-013 recorded is gone: `harness/node/package.json` now pins
`typescript` `~6.0.3` against `typescript-eslint` `8.68.0`. `lint-node` is still
not a prerequisite of `ci`, so ESLint, Prettier and Knip run in no CI job — and
with them the policy-sourced `max-lines` rule R-TDH-23 added to hold every file
under `src/` to `limits.size_budget_lines`. That rule is currently enforced
nowhere. **Done when** `lint-node` is a direct prerequisite of `ci` and never of
`ci-python` (the matrix legs install no pnpm), and `test_makefile_contracts.py`
pins that asymmetry. `Makefile` is a protected path: `ALLOW_GITHUB_CHANGES=1`
plus the per-change attestation. **Depends on** nothing.

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

### NS-7 · Make the gitleaks allowlist prove it still suppresses something

`test_lint_config_liveness.py` asserts every `.gitleaks.toml` allowlist path
still *exists*; nothing asserts each still *suppresses a finding*. That is how
the list reached 23 paths of which 18 blinded their files for nothing — narrowed
to 7 in the hygiene sweep, with no gate to stop it regrowing. The check must run
where gitleaks is installed: a `make secrets-allowlist-check` target invoked by
the `secret-scan` job, never the unit suite, which has no gitleaks and must not
gain a skip (INV-2). **Done when** the target exists, `secret-scan` runs it, and
removing a load-bearing allowlist entry fails it. **Depends on** nothing; do it
with NS-2 while the secret-scanning surface is already in hand.

### NS-8 · Close the three agent-surface truth gates

Falsification probes found three silent failures, all green under the full
suite because the existing checks are substring-presence rather than row or
membership checks: a `SKILL.md` can name a `make` target that does not exist; a
persona's `tools:` frontmatter can declare `write_file` on the verifier — the
exact authority `agent_authority.py` exists to withhold; and the 3-active →
7-canonical mapping table in `.mango/agents/README.md` can have its rows
*swapped*. **Done when** three assertions in `test_agent_harness_wiring.py` /
`test_agent_surface_liveness.py` fail against each mutation. No new file needed.
**Depends on** nothing.

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

### NS-10 · Give `policy_loader` a logger, and the policy blocks a `TypedDict`

Every threshold in the system resolves through `policy_loader`, and nothing
records what was resolved or from which file — so under `LOG_LEVEL=DEBUG`,
"which policy did this run actually read" is unanswerable. `ExecutionLoop`
already logs its own resolution at DEBUG; copy that pattern. Related and worth
the same change: a `TypedDict` per policy block turns `limits["typo"]` into a
type error at ~20 call sites, and would have caught the `KeyError` fixed under
DEC-032. **Done when** a DEBUG line names the resolved key, value and source
file, and the `limits` block is typed. **Depends on** nothing.

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

### NS-12 · Narrow the two broadest skip waivers

Seven of eight rows pair `unique_id_glob: "…::*"` with `test: "*"`, so any new
skip anywhere in a 600-line module is auto-approved provided its reason contains
`(DEC-026)` — and the reusable `POSIX_ONLY` marker's reason already ends that
way. A waiver that approves skips nobody has written yet is not a waiver.
**Done when** the two broadest globs name specific node ids. **Depends on**
nothing.

### NS-13 · Partition the hook namespace, and test the one live hook

`pre-nemotron-run.sh` is the only hook on a live product path and has no test:
deleting it leaves the suite green, because `HookRunner.run_hook` no-ops on a
missing file (correct behaviour, untested consequence). Nothing asserts the
`.mango/hooks/*.sh` partition into {`PERMITTED_HOOK_NAMES`} ∪
{settings-registered} either, so a new script belongs to neither namespace and
no test says so. **Done when** deleting or renaming the hook fails a test, and
an unpartitioned script is reported by name. **Depends on** nothing.

---

## 3. P2 — real, but nothing breaks while they wait

### NS-14 · The entrypoint contract (DEC-029)

31 `sys.path` bootstrap sites in four styles, accepted as-is because a helper
would need the bootstrap it replaces and the per-stack scripts are digested
root-of-trust artefacts. DEC-029 defers this explicitly to "when the 3.9 floor
moves". **Depends on NS-6** — it is a follow-on, not an independent item.

### NS-15 · Split `write_policy.py` by concern

381 lines, under the 500-line `limits.size_budget_lines` budget — so this is a
cohesion item, not a budget violation, and it should be scheduled as one. Split
into distinct boundary and invariant validators. **Depends on** nothing.

### NS-16 · Retire the duplication `retry.ts` was extracted to address

`nemotron-client.ts` lines 169–183 and 251–265 are a verbatim 15-line
request-body builder differing only in `stream:`; one branch edited both copies
identically three times. `top_p` is now the only sampling parameter in that
literal that is not policy-sourced, and `retry.ts`'s `JITTER_CEILING_MS` is a
new unlinked constant with no triage row, where its Python counterpart has one.
**Done when** one builder feeds both call sites, `top_p` is policy-sourced, and
`JITTER_CEILING_MS` has a triage row. **Depends on** nothing.

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

## 6. Corrected since the last revision

Two items this file carried as open are delivered. Recording the correction
rather than silently unchecking a box, per the convention DEC-032 set:

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
