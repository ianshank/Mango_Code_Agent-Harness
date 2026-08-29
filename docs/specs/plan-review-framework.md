# Spec: plan-review framework (Layer 0)

## Problem statement

`make review`'s checklist names `openspec-peer-review` as the plan-review step. That
skill is four job-title personas with no output schema, no severity vocabulary, and a
termination rule that cannot fail ("Only proceed to execution once all personas sign
off"). Every other gate in this repository predicts a specific job going red; this one
produces prose.

The mechanical half is thinner still. `validate_specs.py`'s falsifiability check is a
three-phrase blocklist — `works correctly`, `as expected`, `appropriately`. **Measured
against all 15 plans in the repository (104 acceptance criteria, 139 requirement IDs) it
fires zero times.** It is a dead rule.

Evidence for what a real rule catches, from the same measurement:

| Rule | Findings | Note |
|---|---|---|
| `UNFALSIFIABLE_ACCEPTANCE` | 7 / 104 ACs | ~4–5 judged real |
| `MISSING_FAILURE_PATH` | 3 / 15 plans | |
| `STAGE_REACHABILITY` | 2 / 104 ACs | a named check assigned to a human |
| current blocklist | **0 / 104** | |

Two further findings shape the scope. First, three additional rules considered here
(step-DAG satisfiability, protected-path collision, scope leak) are **undecidable against
every landed plan** — 15 of 15 have no `## Steps` and no `## Files touched` section, so
there is nothing for them to read. They are deferred, and this change adds the template
sections so the data starts accumulating. Second, requiring each `R-*` to be cited by an
acceptance criterion scores 9 of 11 specs at 100% orphaned, because `SPEC_TEMPLATE.md`
never asked for the citation — so that rule ships as forward-looking convention
enforcement, scoped to specs carrying the new sections, not as a defect detector.

## Requirements

- R-PLR-1: The plan gate MUST report `UNFALSIFIABLE_ACCEPTANCE` for an acceptance
  criterion naming no observable, where an observable is a backticked code span or a
  stage/test selector, and MUST treat a criterion whose stated verification is human
  reading (`verified by review`, `by inspection`, `manually`) as naming none regardless
  of its code spans.
- R-PLR-2: The plan gate MUST report `MISSING_FAILURE_PATH` for a plan whose acceptance
  criteria reference no non-success outcome.
- R-PLR-3: The plan gate MUST report `STAGE_REACHABILITY` for an acceptance criterion
  that names a check but assigns it to a human rather than to a `make` stage. Resolving
  a stage to its underlying selector is out of scope for this change.
- R-PLR-4: The plan gate MUST report `ORPHAN_REQUIREMENT` for a declared `R-*`/`C-*` that
  no acceptance criterion cites, and MUST apply that rule only to plans carrying the
  sections this change adds, so that plans written against the previous template are not
  retroactively failed.
- R-PLR-5: The plan gate MUST examine only specs reported modified by
  `validate_invariants.git_modified_files`, so new and edited plans fail closed while
  landed plans are neither re-litigated nor back-filled.
- R-PLR-6: A spec the gate cannot parse MUST be a finding, never a skip.
- R-PLR-7: The three structural rules currently embedded in `validate_specs.sh` MUST move
  into the shared rule module, and three defects in them MUST be fixed in the move: the
  two recorded in `NEXT_STEPS.md` — an unfilled template scaffold satisfying every rule,
  and an `AC-*` bullet containing `MUST` that can never satisfy the requirement-ID regex
  — plus a third found by running the gate against this spec, where the blocklist scan
  matches a phrase inside a code span and so fails any document that names the phrases it
  bans. Code spans MUST be stripped before the scan, since a backticked phrase is being
  named rather than used.
- R-PLR-8: `SPEC_TEMPLATE.md` MUST gain `## Steps` and `## Files touched` sections, and
  its `## Invariants touched` prompt MUST name the contract's actual range rather than
  `INV-1..INV-7`.
- C-PLR-1: The change MUST NOT weaken any invariant in `harness/CONTRACT.md`.
- C-PLR-4: Every phrase-matching rule MUST ignore backticked spans, because a phrase
  inside a code span is being named rather than used. Both rules that match phrases hit
  this: the blocklist failed any document naming the phrases it bans, and the
  human-deferral check failed this spec's own AC-2 for quoting `verified by inspection`
  as test data.
- C-PLR-2: The gate MUST reuse `validate_invariants.is_protected` and the requirement-ID
  regex already shared by `validate_specs.py` and `check_traceability.py` rather than
  defining a second matcher for either.
- C-PLR-3: The gate MUST run as a third tier of the existing `specs` target and MUST NOT
  add an entry to `target_contract`, `pre_pr_order`, or `ci_required_targets`, which are
  cross-stack contracts the Node and JVM stacks would then be obliged to implement.

## Steps

1. **Extract the rule module.** — produces `harness/shared/plan_rules.py`
2. **Build the CLI.** — consumes `harness/shared/plan_rules.py`; produces
   `harness/shared/validate_plan.py`
3. **Migrate the structural rules.** — consumes `harness/shared/plan_rules.py`; produces
   the reduced `harness/shared/validate_specs.py` and `validate_specs.sh`
4. **Extend the template.** — produces `docs/specs/SPEC_TEMPLATE.md`
5. **Wire and govern.** — consumes `harness/shared/validate_plan.py`; produces the
   `specs` tier, the `protected_paths` entries, INV-17, and the meta-test updates

## Files touched

- `harness/shared/plan_rules.py`
- `harness/shared/validate_plan.py`
- `harness/shared/validate_specs.py`
- `harness/shared/validate_specs.sh`
- `harness/shared/governance-policy.json`
- `harness/shared/tests/test_plan_rules.py`
- `harness/shared/tests/test_validate_plan.py`
- `harness/shared/tests/test_ci_gate_coverage.py`
- `harness/CONTRACT.md`
- `docs/specs/SPEC_TEMPLATE.md`

## Acceptance criteria

- [ ] AC-1: A criterion carrying only prose is reported `UNFALSIFIABLE_ACCEPTANCE`, and
      one naming `` `make ci` `` is not — verified by `pytest -k TestUnfalsifiableAcceptance`
      · stage: `make specs` (R-PLR-1)
- [ ] AC-2: A criterion reading ``  `git grep x` returns nothing — verified by inspection ``
      is reported despite its code span — verified by
      `pytest -k test_human_deferral_overrides_a_code_span` · stage: `make specs` (R-PLR-1)
- [ ] AC-3: A plan whose criteria never reference a non-success outcome is reported
      `MISSING_FAILURE_PATH`; adding one criterion saying a gate `fails closed` clears it
      — verified by `pytest -k TestMissingFailurePath` · stage: `make specs` (R-PLR-2)
- [ ] AC-4: A criterion naming a check assigned to a human is reported
      `STAGE_REACHABILITY`, not `UNFALSIFIABLE_ACCEPTANCE` — verified by
      `pytest -k TestStageReachability` · stage: `make specs` (R-PLR-3)
- [ ] AC-5: A plan with no `## Steps` section yields no `ORPHAN_REQUIREMENT` findings;
      the same plan with the section yields one per uncited ID — verified by
      `pytest -k TestOrphanRequirement` · stage: `make specs` (R-PLR-4)
- [ ] AC-6: With one spec edited and one unrelated file edited, the gate examines exactly
      one plan and names it; with no spec edited it reports zero examined and exits 0 —
      verified by `pytest -k TestModifiedScoping` · stage: `make specs` (R-PLR-5)
- [ ] AC-7: A spec whose acceptance section cannot be parsed exits 1 naming the file —
      verified by `pytest -k test_unparseable_spec_is_a_finding` · stage: `make specs`
      (R-PLR-6)
- [ ] AC-8: An unfilled `SPEC_TEMPLATE.md` copy is rejected, and an `AC-*` bullet
      containing `MUST` is accepted — verified by `pytest -k TestMigratedStructuralRules`
      · stage: `make specs` (R-PLR-7)
- [ ] AC-9: A document naming a banned phrase inside a code span passes, while one using
      the same phrase as prose is rejected — verified by
      `pytest -k test_banned_phrase_inside_a_code_span_is_not_a_finding` · stage:
      `make specs` (R-PLR-7, C-PLR-4)
- [ ] AC-10: `bash harness/shared/validate_specs.sh` exits 0 on this repository with this
      spec present, and exits 1 with a seeded defect of each class — verified by
      `pytest -k TestNegativeProbes` · stage: `make specs` (R-PLR-1, R-PLR-2, R-PLR-3)
- [ ] AC-11: `ALLOW_GITHUB_CHANGES=1 make ci` exits 0 end to end (R-PLR-8, C-PLR-1,
      C-PLR-2, C-PLR-3)

## Invariants touched

Which of `INV-1..INV-16` (see `harness/CONTRACT.md`) does this change affect, and how is
each shown to still hold?

- INV-5: preserved and extended. The gate is reached by an existing Make target rather
  than a new one, so `test_ci_gate_coverage.py` continues to map every
  `ci_required_targets` entry to a root target; the `specs` entry's description and its
  `PARTIAL_COVERAGE` reason are updated in this change to describe three tiers.
- INV-17 (added): a plan reaching implementation has been checked for the defect classes
  this gate decides. Enforced by `validate_plan.py` in `make specs`, with its
  `test_invariant_liveness.INVARIANT_MECHANISMS` entry landing in the same change so the
  invariant is never a published MUST with nothing behind it.
- INV-1, INV-2, INV-3: unaffected. No change to secret scanning, skip handling, or remote
  allowlisting.
- INV-16: unaffected. This gate is deterministic and consults no model output; nothing
  here gives a cognitive-plane field a control path.

## Validation matrix

Thresholds are read from `harness/shared/governance-policy.json` — no value is restated
here.

- `make specs` — structural, plan, and (when available) strict tiers
- `make ci` — ruff + mypy + pytest + coverage + check-dedup + validate_invariants
- coverage target: `coverage.lines` and `coverage.branches` from
  `governance-policy.json`, applied as separate floors plus the per-file lines floor

## Backward compatibility

Landed specs are unaffected: R-PLR-5 scopes the gate to modified files, and R-PLR-4
scopes the orphan rule to plans carrying the new sections. `validate_specs.sh` keeps its
name, its exit-code contract, and its `SPEC_DIR` / `REQUIRE_STRICT_SPEC_VALIDATOR`
environment interface, so both per-stack Makefiles continue to call it unchanged. No
existing rule is removed — the three structural rules move module, not meaning.

## Open questions

- **Deferred, not open.** The step-DAG, protected-path-collision and scope-leak rules
  need `## Steps` and `## Files touched` data that does not exist yet. This change adds
  the sections; the rules are reconsidered once enough plans carry them to calibrate
  against, on the evidence standard this change was itself held to.
- **Resolved.** Whether findings need a persisted schema. They do not here — the gate
  reports to stderr and exits non-zero, like every other validator. A persisted finding
  artifact would collide with `synthesis.critique_schema_version`, which is pinned to
  INV-11 but backed by no implementation, and that fork is not this change's to settle.
