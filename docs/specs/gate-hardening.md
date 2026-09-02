# Spec: gate-hardening

> PR 5 of the tech-debt reduction program; infra PR #2 of 2 (requires the
> `infra-reviewed` label — touches Makefile, pyproject.toml, the CI workflow,
> pinned meta-tests, and CONTRACT.md, with per-change attestation in the PR).

## Problem statement

The repository's own meta-tests document that declaration and enforcement
diverge (evidence: `test_coverage_policy_enforcement.py::UNENFORCED_IN_ROOT_CI`
and `harness/CONTRACT.md` §Coverage gate on `main` before this change):

- `make test-node` ran vitest **without `--coverage`**, so the entire
  policy-sourced threshold block in `vitest.config.ts` never executed in CI.
- `coverage.per_file: true` was declared but enforced nowhere; aggregate
  headroom meant a new untested module could ship green.
- mypy checked `harness/shared` and `harness/api_server` but not
  `harness/control-plane`, despite it being in the coverage source set.
- ruff ran only `E,F,W,I,UP`; the `# noqa: BLE001` comments in gate scripts
  were inert, and bugbear/logging-format rules were off.
- `harness/CONTRACT.md` claimed branch coverage was not measured for Python —
  false since `branch = true` landed — and described the retired `COV_MIN`
  mechanism.
- The CI matrix ran the full `make ci` — pnpm install plus the entire Vitest
  suite — on all three matrix Python versions plus build-full, four identical Node runs for one
  Python-independent signal.

Preconditions satisfied by earlier program PRs: every Python file is at or
above the per-file floor and the Node suite passes `--coverage` (PR 3), and
the two control-plane CLIs are importable and tested (PR 3), so this flip
lands green instead of red.

## Requirements

- R-GATE-1: `coverage_gate.py` MUST enforce the `coverage.lines` floor per
  measured file when `coverage.per_file` is true, failing closed when the
  report lacks a `files` block; files with zero statements are skipped. No new
  numeric literal may appear in the gate.
- R-GATE-2: `make test-node` MUST run vitest with `--coverage` so the
  policy-sourced thresholds (including `perFile`) evaluate in root CI.
- R-GATE-3: mypy MUST check `harness/control-plane` in both `lint-python` and
  `lint-cold` (as loose modules; the directory is deliberately not renamed).
- R-GATE-4: ruff MUST additionally select `B` (bugbear) and `G` (logging
  format); `S` (bandit) stays off deliberately (subprocess-heavy gates would
  need blanket waivers). Findings are fixed, not waived.
- R-GATE-5: The CI workflow MUST run the Node-dependent gates once per PR (a
  full `make ci` on one primary leg) while the remaining matrix legs run a
  Python-scoped `ci-python` composite that still invokes every Python gate by
  Make target (INV-5).
- R-GATE-6: The pinned meta-tests (`test_coverage_policy_enforcement.py`,
  `test_ci_gate_coverage.py`) MUST be updated in the same change so the
  classification reflects reality: no declared threshold remains classified
  unenforced, and per-file behavior gains behavioral probes.
- R-GATE-7: `harness/CONTRACT.md` §Coverage gate MUST describe the actual
  mechanism (coverage_gate.py, branch measurement, per-file, Node coverage).
- C-GATE-1: The stale `"scratch/*.py"` ruff ignore and the coverage omit
  entries for the two now-importable control-plane CLIs MUST be removed from
  `pyproject.toml`.
- C-GATE-2: `make ci` keeps its exact prerequisite list (pinned by
  `REQUIRED_CI_STAGES`); `ci-python` is additive.

## Acceptance criteria

- [x] AC-1: A synthetic report with one file below the floor and a green
  aggregate exits 1; `per_file: false` restores aggregate-only behavior —
  verified by `TestPerFileEnforcement` in `make test`. — verified 2026-09-02:
  `pytest harness/shared/tests/test_coverage_policy_enforcement.py -k TestPerFileEnforcement`:
  12 passed
- [x] AC-2: `ALLOW_GITHUB_CHANGES=1 make ci` passes end-to-end with
  `test-node` running `--coverage` and the per-file Python gate active.
  — verified 2026-09-02: `ALLOW_GITHUB_CHANGES=1 make ci` on the Phase 1 tree: lint, lock-check,
  coverage-python (2513 passed, 0 failed), test-node, verify-zero-skips, specs, remotes,
  validate and check-dedup all exit 0; `digest-regen` exits 0 once the regenerated bundle
  is committed (its `git diff --exit-code` compares against the index). The earlier mypy
  blocker was fixed in `test_workflow_contracts.py` before this run
- [x] AC-3: `make ci-python` passes and reaches every Python gate by Make
  target — verified by `test_ci_gate_coverage.py`. — verified 2026-09-02: every `ci-python` stage is a stage of the `make ci` run recorded
  under AC-2 (`ci` differs from `ci-python` only by the Node gates, pinned by
  `test_makefile_contracts.py`)
- [x] AC-4: `ruff check .` is clean with `B` and `G` selected. — verified
  2026-09-02: `python -m ruff check .` under HEAD's pinned 0.6.9 prints
  `All checks passed!`; `pyproject.toml` `select` lists `"B", "G"` (the
  in-flight R-TDH-10 bump to 0.16.5 reports 37 findings and owns them)
- [ ] AC-5: mypy over shared + api_server + control-plane is clean. — open
  2026-09-02: `make lint-cold`: `Found 1 error in 1 file (checked 181 source
  files)`, the `test_workflow_contracts.py:117` `no-any-return`; blocked by
  tech-debt-hardening-plan R-TDH-9

## Invariants touched

- INV-5: preserved and strengthened — gates still invoked by Make target;
  `ci`'s prerequisite list unchanged; the meta-test's reachability and
  evidence assertions updated in the same change.
- INV-2: unaffected — `verify-zero-skips` continues to run on the leg that
  produces vitest results.
- INV-1: unaffected — the secrets job is untouched.

## Validation matrix

- `ALLOW_GITHUB_CHANGES=1 make pre-pr` — full CI + review checklist + cold lint
- `make ci-python` — the new secondary-leg composite
- coverage target: `governance-policy.json → coverage.{lines,branches}` in
  aggregate plus `coverage.lines` per file (`per_file: true`)

## Backward compatibility

- `make ci` semantics unchanged for local users; `ci-python` is additive.
- `coverage_gate.py` CLI flags unchanged; a policy without `per_file` (or with
  it false) behaves exactly as before.
- Adopters running the per-stack Makefiles are unaffected (root Makefile and
  root workflow only).

## Open questions

None. Two recorded deviations from the original program plan:
1. `# noqa: BLE001` comments are kept, not deleted — they carry real
   justifications and make a future `BLE` enablement turnkey; `RUF100` is not
   selected, so inert noqas cannot fail the build.
2. Gate-script `print()` calls are NOT converted to `json_logging`: those
   verdict lines (`zero-skip: passed`, `projections: passed`) are the gates'
   stdout CLI contract, pinned by their test suites; converting them would
   break the contract for no governance gain.
