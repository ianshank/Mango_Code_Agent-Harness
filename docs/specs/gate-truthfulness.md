# Spec: gate truthfulness — gates that cannot pass on absent evidence

**Version:** 2.4.0
**Status:** Delivered — verified 2026-09-03 (see Validation matrix)
**Opened by:** `docs/reports/ROADMAP-PEER-REVIEW.md` (2026-09-03), items NS-3 · NS-5 ·
NS-7 · NS-8 · NS-9 · NS-10 · NS-12 · NS-13

## Problem statement

DEC-032 found four gates that reported PASS on absent or wrong evidence and
fixed each with a test that fails without the fix. The roadmap peer review found
that the same failure shape survives in eight more places, and produced evidence
for each. This spec closes the batch.

The shared defect is not a bug in any one gate. It is that a gate's *scope* is
unbounded: nothing asserts that the set of things it examined is the set of
things that exist. A waiver can widen to cover skips nobody has written; an
`omit` entry can shrink the measured set while raising the aggregate; an
allowlist entry can suppress nothing while permanently blinding its file; a
persona can declare an authority its role exists to withhold. In every case the
gate still prints PASS, because it faithfully reports on a set that quietly got
smaller.

Three findings carry direct evidence that the recorded diagnosis was wrong:

1. **`make lint-node` fails for a different reason than the one on record.**
   DEC-013 and `docs/specs/ci-enforcement-gaps.md` record the blocker as a
   `typescript` / `typescript-eslint` incompatibility. Measured 2026-09-03 with
   the workspace installed: ESLint passes, Knip passes, and `prettier --check`
   fails on exactly one file — `harness/node/.governance/policy.json`, over
   whitespace inside the `coverage.optional_extras.path_prefixes` array DEC-028
   added. That file is digest-pinned: `docs/rca/e2e_origin_sync_triage_rca_v2.5.0.md`
   records Prettier's reformat breaking the root-of-trust SHA256 and the fix
   being to restore the exact bytes. Prettier's preferred formatting and the
   root-of-trust digest are mutually exclusive, so no amount of running
   `prettier --write` can resolve it — the tree must be excluded from Prettier's
   scope instead.
2. **Nothing pins a declared version to a changelog entry.**
   `test_documentation_truth.py` pins the four version mirrors to each other and
   passes today while the repository disagrees with itself about whether the
   current release is 2.4.0 or 2.5.0, and while `CHANGELOG.md` carries no entry
   for the most recently merged work. Mirrors agreeing with each other is not
   the same as the release being real.
3. **`policy_loader` resolves every threshold in the system and logs nothing.**
   Under `LOG_LEVEL=DEBUG`, "which policy file did this run actually read, and
   what did it resolve" is unanswerable. `ExecutionLoop` already logs its own
   resolution at DEBUG; the pattern exists and is simply not applied here.

## Requirements

- R-GT-1: `lint-node` MUST be a direct prerequisite of the root `ci` target and
  MUST NOT be a prerequisite of `ci-python`, whose matrix legs install no pnpm.
- R-GT-2: Prettier MUST NOT reformat the digest-pinned `.governance/` tree, so
  that the formatting gate and the root-of-trust digest can both hold.
- R-GT-3: The coverage gate MUST fail closed when the set of measured files
  diverges from the on-disk first-party source set, so an added `omit` entry
  cannot drop a file from the per-file floor while raising the aggregate.
- R-GT-4: `policy_loader` MUST emit a DEBUG record naming the resolved key, the
  value, and the file it came from, for every threshold it resolves.
- R-GT-5: The `limits` policy block MUST be typed so that reading an undeclared
  key is a static error under `mypy`, rather than the runtime `KeyError`
  DEC-032 fixed by hand.
- R-GT-6: The agent-surface gates MUST reject a `SKILL.md` naming a `make`
  target the root Makefile does not define, a persona whose `tools:` frontmatter
  declares an authority `agent_authority.py` withholds from that role, and a
  mapping table in `.mango/agents/README.md` whose active-to-canonical rows have
  been swapped.
- R-GT-7: Skip waivers MUST match specific test node ids, so that a skip added
  later in an already-waived module is not auto-approved by its reason alone.
- R-GT-8: Every script in `.mango/hooks/` MUST belong either to
  `PERMITTED_HOOK_NAMES` or to the set registered in a settings file, and the
  one hook on a live product path MUST have a test that fails if it is deleted
  or renamed.
- R-GT-9: The version declared in `pyproject.toml` MUST have a matching
  `## [x.y.z]` section in `CHANGELOG.md`.
- R-GT-10: Every allowlist entry in a `.gitleaks.toml` MUST still suppress at
  least one real finding, checked where gitleaks is installed.
- C-GT-1: No gate added here may report PASS on an empty examined set; each MUST
  fail closed when it measures nothing, per `coverage_gate.py`'s own "absence of
  evidence is never a pass" contract.
- C-GT-2: The change MUST NOT weaken any invariant in `harness/CONTRACT.md`, and
  MUST NOT add a test skip, an `xfail`, or a waiver to make any gate green.
- C-GT-3: All new code MUST run on the interpreters the CI matrix declares,
  whose floor is `requires-python` in `pyproject.toml`.

## Acceptance criteria

- [x] AC-1: `make lint-node` exits 0 with the workspace installed, and `make ci`
      lists it as a direct prerequisite while `make ci-python` does not —
      verified by `pytest -k TestLintNodeWiring`
      · stage: `make ci` (R-GT-1)
- [x] AC-2: Removing the `.governance/` entry from `harness/node/.prettierignore`
      makes `prettier --check` report `policy.json`, and reformatting that file
      makes `validate_adoption.py` fail on the root-of-trust digest — the two
      outcomes this exclusion exists to keep apart — verified by
      `pytest -k test_governance_tree_is_excluded_from_prettier`
      · stage: `make ci` (R-GT-2, C-GT-2)
- [x] AC-3: Adding any first-party source file to the coverage `omit` list makes
      the gate exit 1 naming that file, and a run measuring zero files also
      exits 1 rather than reporting a vacuous pass — verified by
      `pytest -k TestMeasuredSetIsBounded`
      · stage: `make coverage-python` (R-GT-3, C-GT-1)
- [x] AC-4: With `LOG_LEVEL=DEBUG`, resolving any threshold emits a record
      naming the key, the value and the source path; at default level it emits
      nothing — verified by `pytest -k TestPolicyResolutionLogging`
      · stage: `make ci` (R-GT-4)
- [x] AC-5: Reading an undeclared key from the typed `limits` block is reported
      by `python -m mypy`, and every declared key still resolves at runtime —
      verified by `pytest -k TestLimitsAreTyped`
      · stage: `make lint` (R-GT-5)
- [x] AC-6: Each of the three agent-surface mutations is rejected by name — a
      `SKILL.md` naming `make no-such-target`, a `verifier` persona declaring
      `write_file`, and a mapping table with two rows swapped — verified by
      `pytest -k TestAgentSurfaceTruth`
      · stage: `make ci` (R-GT-6)
- [x] AC-7: A skip added to an already-waived module is reported as unapproved
      by `make verify-zero-skips-python`, while every skip present today stays
      approved — verified by `pytest -k TestWaiversAreNodeScoped`
      · stage: `make ci` (R-GT-7)
- [x] AC-8: Deleting or renaming `pre-nemotron-run.sh` fails a test, and a
      script in `.mango/hooks/` belonging to neither namespace is reported by
      name — verified by `pytest -k TestHookNamespacePartition`
      · stage: `make ci` (R-GT-8)
- [x] AC-9: A declared version with no matching `## [x.y.z]` changelog section
      fails the documentation-truth suite, proved against a synthetic tree —
      verified by `pytest -k test_declared_version_has_a_changelog_section`
      · stage: `make ci` (R-GT-9)
- [x] AC-10: `make secrets-allowlist-check` exits 1 naming any allowlist entry
      that suppresses no finding, and exits 0 on the current tree — verified by
      `make secrets-allowlist-check` · stage: `secret-scan` (R-GT-10)
- [x] AC-11: The full suite runs with no new skip and no waiver added: the skip
      count reported by `make verify-zero-skips-python` is unchanged from the
      pre-change baseline (38 on a leg without the langgraph extra, 1 on
      `build-full` which installs it) — verified by `make verify-zero-skips-python`
      and `pytest -k TestTheShippedRegistryIsParseable`
      · stage: `make ci` (C-GT-2, C-GT-3)

Verified 2026-09-03: `make ci` exit 0 locally with pinned tools, real gitleaks
and the pnpm workspace installed; `make lint-node` confirmed green in CI on
`build-full`, which is the first time the Node lint tier has executed in this
repository's CI. Each acceptance criterion above was additionally
mutation-tested — the mutation it names was applied, the test observed failing,
and the tree restored.

## Steps

1. Add `harness/node/.prettierignore` — produces the exclusion R-GT-2 needs;
   consumed by `make lint-node`.
2. Wire `lint-node` into `ci` in the root `Makefile` — consumes step 1; produces
   the prerequisite edge R-GT-1 asserts. Protected path.
3. Add the measured-set bound to `harness/shared/coverage_gate.py` — consumes
   `coverage.json`; produces the R-GT-3 failure path.
4. Add resolution logging and the typed `limits` block to
   `harness/shared/policy_loader.py` — produces the R-GT-4/R-GT-5 surface.
5. Add the three agent-surface assertions — consumes `.mango/agents/`,
   `.mango/skills/`, the root Makefile target list and `agent_authority.py`.
6. Narrow the skip-waiver rows — consumes the current skip inventory; produces
   the R-GT-7 node-scoped registry.
7. Add the hook-partition and live-hook tests — consumes `.mango/hooks/`,
   `PERMITTED_HOOK_NAMES` and the settings files.
8. Add the changelog-section assertion to `test_documentation_truth.py`, and
   `make secrets-allowlist-check` plus its `secret-scan` step.

## Files touched

- `harness/node/.prettierignore` (new)
- `Makefile` — **protected path**, needs the `infra-reviewed` attestation
- `.github/workflows/python-package.yml` — **protected path**, same attestation
- `harness/shared/coverage_gate.py`, `harness/shared/coverage_scope.py` (new —
  the scope half, split out at 470/500 lines; see DEC-035),
  `harness/shared/policy_loader.py`
- `harness/shared/tests/` — the new and amended gate tests
- `harness/shared/tests/skip-waivers.json`
- `.github/dependabot.yml`, `harness/node/.governance/decision-log.md`

## Invariants touched

- INV-1 (no secrets): strengthened. R-GT-10 makes the allowlist prove it still
  suppresses something, closing the path by which it grew to 23 entries of which
  18 suppressed nothing.
- INV-2 (zero unapproved skips): strengthened by R-GT-7; no skip is added, per
  C-GT-2.
- INV-5 (every required target reachable from CI): strengthened by R-GT-1, which
  brings the Node lint tier into the root pipeline for the first time.
- The root-of-trust digest chain: preserved by R-GT-2, which removes the only
  tool that was rewriting a pinned file.

## Validation matrix

- `make ci` — ruff + mypy + pytest + coverage + zero-skips + specs + validate +
  check-dedup + digest-regen, now including `lint-node` (R-GT-1, R-GT-6, R-GT-7,
  R-GT-8, R-GT-9)
- `make coverage-python` — coverage floors from
  `governance-policy.json → coverage.lines` and `coverage.branches`, plus the
  per-file floor and the new measured-set bound (R-GT-3)
- `make lint` — `python -m ruff` and `python -m mypy` through the interpreter,
  never a bare binary on `PATH` (DEC-013) (R-GT-5)
- `make secrets` and `make secrets-allowlist-check` — run where gitleaks is
  installed (R-GT-10)
- `make lint-node` — ESLint, Prettier and Knip (R-GT-2)
- coverage target: `coverage.lines` from `governance-policy.json`; no threshold
  is restated here.

## Backward compatibility

Additive for every caller. `policy_loader`'s public functions keep their
signatures and return types; the typed `limits` block is a `TypedDict`, which is
a `dict` at runtime, so existing subscript access is unchanged and adopters
reading it dynamically are unaffected. The new logging is at DEBUG and silent by
default. `.prettierignore` changes no committed byte of the files it excludes —
that is its purpose. Wiring `lint-node` into `ci` makes a previously unrun tier
run: an adopter fork whose Node workspace is not installed will see `ci` fail
where it previously passed, which is the intended change and is why it is a
prerequisite of `ci` only, never of `ci-python`.

## Open questions

None blocking. Two decisions sit outside this spec and are recorded in
`NEXT_STEPS.md` rather than answered here: whether the branch ruleset is applied
(NS-1) and which version number the current release carries (NS-3). R-GT-9 adds
the missing assertion either answer will be checked by; it does not choose the
answer.

**Deferred from this change, with the measurement that decided it.** NS-9 named
two unjustified `# pragma: no cover` sites. `mcp_server.py:16` is fixed here:
the arc is the 3.9 leg's real path, `test_import_failure_sets_mcp_unavailable`
already executes it, and removing the pragma moved the file from 94.06% to
94.44% — measured, not predicted. `langgraph/__init__.py:52` is **not** fixed
here, and deliberately:

- Removing that pragma alone leaves lines 59-60 (`except ImportError: pass`)
  unreachable on any leg that *has* langgraph, taking the file to 8/10 = 80%
  against a 90% floor. It would turn the 3.10 and 3.12 legs red.
- The change that is actually right — deleting the `try`/`except` so a real
  failure to import `graph.py` propagates instead of degrading to "`build_graph`
  just isn't exported" — is a behavioural change to a protected path, and its
  coverage effect differs per leg: 7/7 where langgraph is installed, but 5/7 on
  a local run without it and without `MANGO_CI_DESELECT_LANGGRAPH=1`, which is
  no waiver and a red gate for a contributor who has not installed the extra.

Folding that into this batch would ship a change whose failure mode is a
contributor's first `make ci`. It needs its own change, with the extra installed
on the verifying machine so both legs can be measured. Tracked in `NEXT_STEPS.md`
under NS-9; the swallow, not the pragma, is the defect worth fixing.
