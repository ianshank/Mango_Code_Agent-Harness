# Roadmap peer review - `NEXT_STEPS.md` as it stood at `6f0f18b`

**Date:** 2026-09-03
**Reviewed artefact:** `NEXT_STEPS.md` (533 lines, 23 open checkboxes) at
`6f0f18b`, together with the documentation, specs and CI configuration it
claims to summarise.
**Method:** the `openspec-peer-review` skill's four-persona matrix, applied to
the roadmap itself rather than to a single proposal.
**Outcome:** the roadmap is rewritten. This file records why, and the findings
that survived verification.

---

## 0. Verification method, and its limits

Every finding below was checked against the tree or against the GitHub API, not
against the roadmap's own claims. What was run:

| Check | Result |
|---|---|
| Full Python suite (`pytest` over the three test roots, 3.13, langgraph installed) | 2,765 passed, 38 skipped, 7 deselected, 57s |
| `test_documentation_truth.py`, `test_ci_gate_required_checks.py` | 41 passed, before and after the rewrite |
| `git tag -l`, `git ls-remote --tags origin` | both empty |
| Branches API for `main` | `"protected": false` |
| `git ls-remote --heads origin feature/governed-run-console` | present at `5970249…` |
| Workflow runs on `main` (last 30 days) | runs 286, 319, 326 red on `main`'s own head |
| Source reads for each stale-box claim | see F-4 |

**Not verified, and why.** `gitleaks` is not installed in this environment, so
F-2 rests on DEC-014's own statement plus the branch still existing - the
credential itself was deliberately not extracted or inspected. `harness/node`
has no `node_modules`, so the Vitest suite, ESLint and Knip were not run; F-7
rests on reading `package.json` pins and the `Makefile` dependency graph. No
live NIM tests were run (no API key).

---

## 1. Findings

| ID | Severity | Finding | Roadmap item |
|---|---|---|---|
| F-1 | **Blocker** | `main` is unprotected; every gate in the repository is advisory | NS-1 |
| F-2 | **Blocker** | A documented live credential leak was silenced by narrowing the scanner, never rotated, and is tracked nowhere | NS-2 |
| F-3 | Major | The roadmap was 93% changelog, with open items buried inside the history | rewrite |
| F-4 | Major | Two open boxes were already delivered; the roadmap overstated remaining work | §6 |
| F-5 | Major | Release identity is ambiguous in four places at once, and no gate can see it | NS-3 |
| F-6 | Major | `dependabot.yml` contradicts DEC-031; twelve bot PRs reopened | NS-4 |
| F-7 | Major | `lint-node`'s blocker is gone but it still runs in no CI job, taking R-TDH-23's `max-lines` rule with it | NS-5 |
| F-8 | Minor | Roadmap items carried no acceptance criteria, dependencies or evidence - a lower bar than the repo applies to a 40-line spec | rewrite |
| F-9 | Minor | Section headings named versions that had already shipped; parked items did not name their blocker | §4 |
| F-10 | Minor | A commit message misdescribed its own change, breaking the review→fix evidence trail | noted below |
| F-11 | Minor | Two specs cite this file by line number | §7 |

### F-1 - `main` is unprotected (Blocker)

The GitHub branches API reports `"protected": false` for `main` as of
2026-09-03. The consequence is not theoretical: PR #75 merged the same day with
one bot review and no human approval, and three merges since 2026-08-31 left
`main` red on its own head. The coverage floors, the fail-closed policy loaders,
the zero-skip evidence hooks, the secret scan and the nine required checks are
all enforced only by the author's discipline.

This has been the file's self-declared "highest-value item" since v2.1.9 and was
independently re-flagged by an external analysis (DEC-018), which corrected the
check list and added `test_ci_gate_required_checks.py` to keep it accurate - a
mechanically-enforced answer to a problem whose actual blocker is a settings
page. Four releases of increasingly precise preparation for a step nobody takes
is a pattern worth naming.

### F-2 - A known credential leak was silenced rather than retired (Blocker)

DEC-014 states that the branch `feature/governed-run-console` "carries a real
leaked key", found when a fresh `fetch-depth: 0` CI clone scanned every local
ref. The recorded remediation was to add `--log-opts="HEAD"` to all three
`secrets` targets so a PR's gate scans only its own ancestry.

That fix is right on its own terms - a PR author cannot action a secret on a
branch they do not control. But it resolved a *scoping* problem and left the
*security* problem untouched, and DEC-014's own accepted consequence names the
gap: the secret "remains caught the moment that branch's own PR is opened". Four
days on, no PR has been opened, the branch is still on the remote, no rotation
is recorded anywhere in `docs/`, `CHANGELOG.md` or the decision log, and no
roadmap item existed for it. Because `make secrets` is now ref-scoped, no
scheduled job will ever look at that ref again.

A scanner narrowed until it stops reporting a known live secret is the failure
class DEC-024 exists to name, applied to INV-1. Rotation comes first -
rewriting history does not un-leak a key that has already been pushed.

### F-3 - The roadmap was 93% changelog (Major)

496 of 533 lines were completed-milestone history, duplicating `CHANGELOG.md`,
which already holds the same narrative at greater length. Worse than the
redundancy: **eight open items lived inside that history**, under `🚧` headings
interleaved with `✅` ones, so the forward plan could not be read in one place
and no reader could answer "what is left?" without a full pass over the file.
The v2.1.9 section alone runs 150 lines and contains four open boxes.

The repository already solved this once - the v2.2.4 release body was moved to
`docs/releases/` under R-TDH-24 with a pointer left behind. The same treatment
is applied here.

### F-4 - Two open boxes were already delivered (Major)

Verified against the tree:

- **`@with_authority` / `@budgeted` "not applied to any real node function".**
  They are applied, in `harness/shared/langgraph/nodes.py` at lines 58, 87,
  105-106, 156, 287 and 307, against a spec
  (`docs/specs/langgraph-authority-budget-wiring.md`) whose three acceptance
  criteria are checked off and cite passing tests. DEC-022 was accurate when
  written; the roadmap was never updated after the wiring landed.
- **Specs-gate refinements** ("the structural tier accepts an unfilled template
  scaffold"; "an `AC-*` bullet containing MUST can never pass the requirement-ID
  regex"). Both are live in `harness/shared/plan_rules.py` - `UNFILLED_TEMPLATE`
  and `ANY_ID_PATTERN`, the latter citing R-PLR-7 and `NEXT_STEPS.md` by name.

A roadmap that overstates remaining work is the same defect class as DEC-024's
overclaimed completion, inverted - and it is more corrosive, because it teaches
readers that the checkboxes are decorative.

### F-5 - Release identity is ambiguous, and invisible to CI (Major)

Four disagreeing statements coexist: the merge commit for PR #75 and
`docs/rca/e2e_origin_sync_triage_rca_v2.5.0.md` say v2.5.0; `pyproject.toml`,
`README.md`, `CHANGELOG.md` and `NEXT_STEPS.md` say 2.4.0; `CHANGELOG.md` has no
entry for PR #75's work at all; and no git tag has ever existed, so "2.4.0"
names no commit.

The interesting part is why no gate caught it. `test_documentation_truth.py`
pins the four version mirrors *to each other* and passes today. Nothing pins a
declared version to a changelog section, and nothing pins a release to a tag -
so the mirrors can agree perfectly while the repository as a whole is wrong. The
fix belongs with the fix for the drift: the assertion is the deliverable, not
just the version bump.

### F-6 - `dependabot.yml` contradicts DEC-031 (Major)

DEC-031 closed PRs #38-#46 as superseded by the universal lock and named
`lock-upgrade-check` the Python upgrade signal from then on. The `pip` ecosystem
is still enabled in `.github/dependabot.yml`, so twelve bot PRs reopened on
2026-09-02 - including `mypy` 1.11 → 2.3, a major bump no lock-driven process
requested. Either the decision or the config is wrong; leaving both in place
guarantees the queue keeps refilling with PRs the decision log says to close.

### F-7 - `lint-node` is unblocked and still unwired (Major)

DEC-013 deferred wiring `lint-node` into `ci` because `typescript` 7.0.2 and
`typescript-eslint` 8.67.0 were incompatible. `harness/node/package.json` now
pins `typescript` `~6.0.3` against `typescript-eslint` `8.68.0`; the stated
blocker no longer exists, and the roadmap still carried the item with its
original blocker text. The cost is larger than "lint does not run": R-TDH-23
added an ESLint `max-lines` rule sourced from `limits.size_budget_lines` to hold
every file under `src/` to the policy budget, and that rule is enforced in no CI
job at all.

### F-8 - Roadmap items were held to a lower standard than specs (Minor)

Every spec in `docs/specs/` carries requirements, acceptance criteria, a
validation matrix and a backward-compatibility statement, and `validate_specs`
enforces the shape. Roadmap items carried a title and a paragraph - no
acceptance criterion, no dependency, no evidence, no ordering. The repository
applies a higher evidentiary standard to a 40-line spec than to the document
that decides what gets specced. The rewrite imposes four fields on every item.

### F-9 - Stale headings, unnamed blockers (Minor)

Sections 1 and 2 were headed "Near-Term Milestones (v2.2.0 / v2.3.0)" and
"Infrastructure & DevSecOps Milestones (v2.3.0)" - both versions shipped. The
items under them (LATS wiring, the healing CI hook) are blocked on gates the
headings never mention: `synthesis.lats_enabled` is `false` pending an INV-15
ablation result that does not exist, and the healing hook would bind to hooks
DEC-003 keeps dormant. An item whose blocker is unnamed gets rediscovered by
every audit.

### F-10 - A commit message misdescribed its own change (Minor)

Copilot's review of PR #75 raised two real defects: `execute_read_file`'s new
directory branch returned an uncapped listing, bypassing the shared output cap,
and two live test modules set `NEMOTRON_MODE` at import time, which leaks into
hermetic runs because pytest imports deselected modules. **Both were fixed
before merge** - verified by diffing `128e9fe..HEAD`. They landed in `028fda4`,
whose message reads only "fix(ci): resolve 7 ruff 0.16.5 lint errors breaking CI
gates". The fixes are real; the evidence trail from review to fix is broken by
the message, which is the kind of thing that makes a later audit re-flag a
closed finding.

### F-11 - Line-number citations into a living document (Minor)

`docs/specs/tech-debt-hardening-plan.md` cites `NEXT_STEPS.md:253` and
`:258-261`. Those citations are historical records of a completed change and are
left as they stand; the rewrite notes where both targets moved. Cite a section
or an ID, never a line, when the target is a file that changes.

---

## 2. Persona matrix

**Architect.** The system boundaries are sound and the dependency graph is
respected; DEC-020 and DEC-029 have been re-litigated twice and hold. The
architectural problem is not in the code - it is that the enforcement layer's
guarantees terminate at an unprotected branch (F-1). A fail-closed kernel behind
an open door is a fail-open system with extra steps. **Sign-off: conditional on
NS-1.**

**SDLC / CI Lead.** The gates are real, well-tested and mostly fail closed. Three
wiring gaps undercut them: no branch protection (F-1), `lint-node` in no job
(F-7), and a dependency-update process whose config and decision log disagree
(F-6). The testing gates are realistic - the full suite runs in 57 seconds,
which is the reason the discipline has held this long. **Sign-off: conditional
on NS-1, NS-4, NS-5.**

**QA Director.** Coverage and determinism are genuinely strong: 2,765 tests
green, a per-file floor, branch coverage as its own gate, zero-skip evidence
hooks that were themselves recently hardened (DEC-030, DEC-032). The remaining
QA risk is *evidence about evidence* - an allowlist that no longer proves it
suppresses anything (NS-7), an `omit` list nothing bounds (NS-9), waivers
broader than the skips they cover (NS-12), a regression tier that does not
contain the reproductions its contract promises (NS-11), and three
agent-surface probes that pass on substring presence (NS-8). Each is a gate that
can go quietly vacuous. **Sign-off: conditional on the P1 block.**

**Product Manager.** This is where the review is least comfortable. Since
v2.3.0, every shipped increment has been infrastructure about infrastructure:
gates, gate tests, tests for gate tests, and hygiene sweeps over the results.
The three §1 product ambitions (LATS wiring, healing triggers, memory retention)
have not moved, and two of them are blocked on gates nobody has built. Meanwhile
the one product capability that *did* ship - the MCP server, v2.3.0 - is still
not reachable from the reasoner persona, which never mentions it. The harness is
excellent; it is not obvious what it is a harness *for* if the agent surface
does not pick up the capabilities it delivers. **Sign-off: conditional on NS-18
being scheduled, not parked.**

---

## 3. Knowledge gaps

Logged rather than guessed, per the reasoner persona's meta-tool rule:

1. **Is the DEC-014 credential still valid?** Unknown without the provider
   console. If it was already rotated, NS-2 collapses to purge-and-record. This
   should be checked before anything else on the list.
2. **Is applying the ruleset actually wanted?** A single-maintainer repository
   may reasonably decline required reviews. NS-1 accepts "declined, recorded as
   a decision" as a valid close - but not silence.
3. **Which version is v2.5.0 meant to be?** The RCA and the merge commit assert
   it; nothing else does. Only the owner can say whether PR #75 was a release or
   a fix batch.
4. **Node-side verification is unrun here** (no `node_modules`). F-7's claim
   that the pins are now compatible is from reading `package.json`; it needs one
   `make lint-node` on a machine with pnpm to confirm before NS-5 is worked.

---

## 4. What changed as a result

- `NEXT_STEPS.md` rewritten: forward-looking only, 19 items in four priority
  bands, each with why-now / evidence / done-when / depends-on. Two stale boxes
  corrected in the open. Parked items each name their blocker. The
  required-status-check paragraph and the `**Version:**` mirror are preserved
  verbatim, so `test_ci_gate_required_checks.py` and
  `test_documentation_truth.py` keep passing.
- `docs/releases/milestone-history.md` added: the completed-milestone record
  moved verbatim, with a banner marking it a snapshot rather than a tracker.
- No source file changed. No gate changed. This review is a documentation
  change and claims nothing about behaviour.

---

## 5. Second peer-rewrite pass (2026-09-05b)

**Reviewed artefact:** `NEXT_STEPS.md` and `docs/specs/2026-standards-remediation-plan.md`
on `main` @ `58490c1` (post PRs #89-#95; DEC-053…056 on #93).
**Method:** same four-persona matrix as §0-§2 above (Architecture / SDLC / QA /
Product), plus live GitHub API checks (DEC-024). No git clone; evidence via
`gh api` contents, pulls, refs, and rules endpoints.
**Outcome:** roadmap + plan rewritten on branch
`docs/roadmap-peer-rewrite-2026-09-05b`; remediation plan bumped to revision 3.

### Thesis

Highest value after #89-#95 / #93 is **roadmap truthfulness**: the open plan
still treated NS-11, NS-31, and NS-33 as unfinished, cited tip `2441547` instead
of `58490c1`, left AC-5 unticked, and kept Phase E / NS-9 / NS-34 wording as if
NS-31 were undecided. A roadmap that overstates remaining work teaches readers
the checkboxes are decorative (same defect class as DEC-024, inverted).

### Counter-argument

DEC-053…056 are already in the decision-log and `GOVERNANCE_SKILL.md`, so Phase E
destructive work (JVM relocate, LangGraph park, openspec fold, mirroring
collapse) should start now. Waiting on NS-2 looks like ceremony once the
in-or-out decisions exist.

### Rebuttal

NS-2 / R-SR-2 is a **hard gate before any destructive Phase E slice**, named in
the plan and in NEXT_STEPS since the first rewrite. Logged DECs close R-SR-5 /
AC-5; they do not rotate the DEC-014 credential or purge
`feature/governed-run-console` @ `5970249…`. Starting Phase E while that ref
remains is claimed readiness without the named control - DEC-024 inverted.
Order stays: finish NS-2, then JVM → LangGraph → openspec → mirroring.

### Verified checks (2026-09-05b)

| Check | Result |
|---|---|
| `GET …/git/ref/heads/main` | `58490c1…` (prior tip was this SHA after #93) |
| `GET …/rules/branches/main` | `[]` |
| License API | `null` |
| Tags | 0 |
| `feature/governed-run-console` | present @ `5970249…` |
| PR #89 | MERGED - first roadmap peer rewrite |
| PR #90 | MERGED - NS-11 regression tier pin |
| PR #91 | MERGED - NS-33 `ruff format` gate + blame-ignore |
| PR #93 | MERGED - DEC-053…056 (NS-31 / R-SR-5) |
| PR #95 | MERGED - size-budget hotfix after format |
| PR #97 | OPEN - NS-17; unresolved Copilot: `policy_path` not plumbed into `agent_memory_defaults` / gap injection |
| Dependabot open | none (closed #62-#78) |
| Remediation AC-5 | was `[ ]` on tip; DECs exist - tick in rev 3 |
| Phase F / ruff | still listed on tip despite #91 |

### Findings

| ID | Severity | Finding |
|---|---|---|
| PR-5 | Blocker (doc) | NEXT_STEPS still listed NS-11 / NS-31 / NS-33 open; header cited `2441547` not tip |
| PR-6 | Blocker (doc) | Plan still rev 2 @ `2441547`; AC-5 unchecked; Phase E conflated R-SR-5 Done with R-SR-2 gating |
| PR-7 | Major | Phase F still listed `ruff format`; NS-33 done |
| PR-8 | Major | NS-4 still said bot PRs left for maintainer; all closed |
| PR-9 | Major | §4 Phase E still blocked on NS-31; DECs exist; retarget to NS-2 |
| PR-10 | Major | NS-9 / NS-34 still treated NS-31 undecided; PARK decided |
| PR-11 | Product | Keep NS-17 open; strengthen Done-when for `policy_path` + mutation + `max_gaps==0`; cite #97 |
| PR-12 | Unchanged P0 | NS-1 / NS-2 / NS-3 / NS-30 still owner-blocked |

### Rewrite actions

1. Close NS-11 / NS-31 / NS-33 into §Delivered; header → `58490c1`; append PR-5…
   findings table.
2. Bump remediation plan to revision 3; tick AC-5; Phase E gated on R-SR-2 only;
   drop `ruff format` from Phase F slack.
3. Retarget NS-9 (moves with park), NS-34 (Depends on nothing), §4 Phase E → NS-2.
4. Strengthen NS-17 Done-when; fix NS-4 Dependabot closed disposition.
5. Docs-only CHANGELOG `[Unreleased]` entry; no source / gate changes.
