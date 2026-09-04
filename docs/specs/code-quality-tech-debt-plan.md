# Spec: Code-quality, tech-debt and hardening plan (audit round 3)

> Status: PROPOSED · Date: 2026-09-04 · Base: `main` @ `487870a` (PR #76)
>
> Third full-team audit of this repository, after `docs/specs/tech-debt-hardening-plan.md`
> (round 2, all 29 acceptance boxes closed by PR #61) and the roadmap peer review in
> `docs/reports/ROADMAP-PEER-REVIEW.md`. It was produced by the procedure
> `.mango/skills/tech-debt-audit/SKILL.md` describes: mechanical gates first, then
> three fresh-eyes sweeps (hard-coded values, dead and duplicated code, structure and
> hardening) told what the previous rounds already fixed so they would not re-report
> it. Every number below was measured on `487870a` in this session; a claim in prose
> is not evidence (DEC-024), so each finding names the command or the file and line
> that reproduces it. Slices marked *child spec* get their own `make spec` before
> implementation.

## Executive summary

The uncomfortable part first: **CI is already green and coverage is already above
99 %.** "Get CI/CD green" is done; what is not done is making green *mean*
something. `main` still has no ruleset (NEXT_STEPS NS-1, open since v2.1.9), so
every gate in this repository is advisory. The 24 requirements below are ordered
so that the enforcement decision comes first and the code follows.

| Phase | Outcome | PRs | Risk | Owner decision needed |
|---|---|---|---|---|
| 0 | Ruleset on `main`, or a decision-log entry declining it; the open Dependabot queue dispositioned | 0 code + 1 doc | low | **yes**: apply the ruleset; close #67 (blocked on the 3.9 floor) |
| 1 | Supply chain: every GitHub Action pinned to a full commit SHA, `pip` installs hash-verified, the Docker runtime non-root with a health check | 3 (workflows protected) | low | **yes**: accept `--require-hashes` on the install path |
| 2 | Policy single-source, round 2: the cross-stack retry drift, the third copy of the policy defaults, the control-plane bundle literals, and the inventory's blind spots (dataclass and keyword defaults) | 4 (1 child spec) | medium | **yes**: where the new `nemotron.retryable_statuses` key lives |
| 3 | Dead and duplicated code the current gates cannot see: nine byte-identical shell copies outside `check_dedup`, a transitively dead `langgraph/ablation.py`, five copy-pasted deprecation shims with no removal date, fixture bodies duplicated up to four times | 4 | medium (protected paths) | **yes**: `ablation.py` moves to `experimental/` |
| 4 | CI truthfulness and cost: a required check that cannot fail, uncached `go install` twice per PR, two test tiers with no marker and one registered marker with zero users | 2 (workflows protected) | low | no |
| 5 | Structure and docs without reopening DEC-020: the `harness/control-plane` hyphen, the two files nearest their size budget, six self-declared stale snapshots, three unpinned version strings, five landed specs with every box unticked | 4 (1 child spec) | medium | **yes**: rename `control-plane` or record the DEC that keeps it |
| 6 | Coverage rides every slice; each new gate is mutation-proved before it ships | per slice | low | no |

Seventeen PRs. Highest value per line changed: Phase 0 (zero lines) and R-CQ-3
(SHA pinning: the root workflows currently hold themselves to a lower bar than the
adopter templates they ship, `harness/CONTRACT.md:49`).

## Problem statement

All numbers measured on `487870a`. The local toolchain was the pinned one from
`requirements-lock.txt` in a fresh virtualenv; Node from `pnpm install --frozen-lockfile`.

**1. The gates are green and the guarantees are advisory.** Workflow run 434 on
`main` is green on every job. Locally: `make lint` clean (ruff, mypy on 209 files,
vulture, py-compat on 232 files); `make coverage-python` 2 976 passed, 1 skipped
(waived, DEC-026), 7 deselected, lines **99.29 %**, branches **97.81 %**, 76 files
measured, 73 at or above the per-file floor with 0 waived; `make validate`,
`check-dedup`, `specs`, `lock-check`, `remotes`, `digest-regen` all pass;
`make lint-node` clean; Vitest 112 passed, 11 skipped (all waived), lines 98.91 %.
None of that is enforced: the branches API still reports `main` unprotected
(NS-1), and `.github/rulesets/main.json` has been committed and not imported.
The roadmap peer review (F-1) called this a blocker on 2026-09-03; it still is.

**2. The two stacks disagree about what to retry, and no gate can see it.**
`harness/shared/nemotron_bridge.py:104` retries `{429, 500, 502, 503, 504}`;
`harness/node/src/ai/nemotron/retry.ts:56-58` retries 429 plus every status in
`[500, 600)`. A 501 or 505 from the same endpoint is retried by one client and
fatal in the other. `nemotron.max_retries` is policy-sourced in both (DEC-036), so
the *count* agrees while the *set* diverges. `sampling-parity.test.ts` proved the
pattern for `top_p`; nothing applies it here.

**3. The policy has three in-code copies, and one more in the control plane.**
`harness/shared/governance-policy.json` is the source. `policy_loader.py:193-317`
carries 21 built-in fallbacks (the documented adopter path, pinned equal by
`test_policy_consistency.py`). `harness/shared/langgraph/policy.py:21-53` carries
the same eleven values a third time as dataclass field defaults, pinned equal to
`policy_loader` by `TestGraphPolicyDefaultsMirrorPolicyLoaderFallbacks`, but
invisible to `test_constant_triage.py`'s inventory, whose discovery (`:245-290`)
finds only module-level upper-case numeric names. `harness/control-plane/build_policy_bundle.py:48-61`
restates `policy_id`, `version` (`"2.0.0"`, equal to the policy's `schema_version`)
and the five `human_approval_required` categories as literals that no test compares
to the policy.

**4. Duplication that `check_dedup` cannot see.** `check_dedup.py:246` globs
`*.py` only. The nine `.sh` files under `harness/node/scripts/` and
`harness/jvm/scripts/` are byte-identical copies of their `harness/shared/`
counterparts (`cmp` on all nine; 162 lines of shared shell in total), and
`harness/node/scripts/run_vitest.sh:6-7` says so in a comment: "must be kept in sync
manually". Inside Python: `_policy_is_absent` is AST-identical in
`check_projections.py:21` and `governance/verify_zero_skips.py:26` (a third variant
is `policy_loader.policy_file_is_absent`, `:104`); `_decision_id_regex` and
`FALLBACK_ID_PATTERN` are duplicated in the same pair; the PEP 562 `__getattr__`
deprecation shim body is copy-pasted in `write_policy.py:110`,
`nemotron_bridge.py:95`, `autonomous_healing.py:22` and `lats_optimizer.py:22`.
In tests: `mock_workspace` is defined four times (`tests/conftest.py:92`,
`_orchestrator_helpers.py:28`, `test_mango_mas_tools.py:10`, and as
`agent_workspace` in `regression/conftest.py:16`); `run_script` twice
(`_zero_skip_harness.py:31`, `test_validators.py:18`); the API-server key fixture
three times; `_passing_outcome` twice with its six-line docstring; and the
control-plane import-purity test pair twice. `test_test_quality.py` scans for
assertion-free tests but not for duplicated bodies, so none of this trips a gate.

**5. Dead by transitivity, and deprecations with no clock.**
`harness/shared/langgraph/ablation.py` has exactly one non-test importer,
`experimental/lats_optimizer.py:10`, which DEC-027 parked; it sits in the live,
protected `langgraph/` package with nothing marking it as parked too.
`synthesis.lats_enabled` has no reader outside the policy file itself. Five
deprecation shims promise removal "after one minor release" (`autonomous_healing.py`,
`lats_optimizer.py`, `write_policy.ALWAYS_DENIED_PREFIXES`,
`nemotron_bridge.RETRY_BACKOFF_BASE_SEC`, `ToolBudget.remaining`); no release has
been tagged since (NS-3: `git tag -l` is empty), so the clock has never started and
nothing will fail when it runs out. `vulture --min-confidence 60` lists 35 symbols
the 80 gate does not, all in these shim, parked and fallback-only regions.

**6. Supply chain is weaker than the repository's own contract.** All 20 `uses:`
references across both root workflows are tag-pinned (`actions/checkout@v5` ×9,
`actions/setup-python@v6` ×7, `actions/setup-go@v6` ×2, `actions/setup-node@v5`,
`pnpm/action-setup@v5`); none is a full commit SHA, which `harness/CONTRACT.md:49`
requires of every adopter and which GitHub's own hardening guidance names as the
only immutable reference. `requirements-lock.txt` carries 0 `--hash` lines and
both workflows install it with a plain `pip install -r`, in a repository that
digest-pins its own policy bundle. `Dockerfile` runs the runtime stage as root
(no `USER`), declares `EXPOSE 8080` with no `HEALTHCHECK`, pulls `node:22-alpine`
by floating tag, and restates `pnpm@11.23.0` at line 4 while CI deliberately reads
it from `package.json` (`python-package.yml:126-128`).

**7. Hard-coded values in the inventory's blind spots.** Beyond item 3:
`governance/verification.py:73` defaults `timeout: int = 300`, equal to
`orchestrator.api_timeout_sec`, read from nowhere; `langgraph/nodes.py:76,97,175`
truncate at `[:200]` and `:67` at `[:80]` while `agent_prompts.TASK_LOG_PREVIEW_CHARS`
is 100 (DEC-039); `plan_rules.py:193` truncates at 40 and `:310` at 48 for adjacent
purposes; `meta_tools.py:92` adds a bare `+ 2` to a lock-poll budget whose three
siblings are DEC-039 rows; `control-plane/verify_repository.py:18` re-types `64`
where `publish_policy_artifact.SHA256_HEX_LEN` exists; `Makefile:68`
`VULTURE_MIN_CONFIDENCE ?= 80` is a lint threshold outside the policy; and
`python-version: "3.11"` appears five times across the two workflows for an
interpreter that is in no matrix and no `pyproject.toml` field. The
NVIDIA base URL and the `/chat/completions` path are literals in both stacks.

**8. CI cost and one check that cannot fail.** Per PR: eight checkouts, seven
Python set-ups, the full pytest suite four times (three `ci-python` legs plus
`build-full`), `lint` four times, and `go install` for gitleaks and osv-scanner
twice with no cache. The two `setup-python` steps in `scheduled-drift.yml:117,232`
have no pip cache. `dependency-audit (3.9)` is a required check in
`.github/rulesets/main.json` whose only step is `continue-on-error` (DEC-017), so
it is required and green by construction.

**9. Structure, tiers and size.** `harness/shared/` holds 41 flat modules across
six concerns plus six top-level compatibility shims; DEC-020 and DEC-029 decline a
regroup, and this plan keeps that. `harness/control-plane` is not an importable
name: it has spawned bespoke path loaders in at least six places
(`_helpers.load_module_by_path`, `regression/test_cross_platform_regression.py:46-56`,
`test_import_purity.py:60`), a third `testpaths`, coverage and Makefile entry each,
and two spellings of one module in `test_constant_triage.py:222,242`. Of six
registered pytest markers, `security` has zero users; the regression and liveness
tiers, the two largest structural categories, have no marker at all. Nothing is over
the 500-line source or 700-line test budget, but `nemotron-client.ts` (432) is 68
lines from a hard ESLint failure and `plan_rules.py` (428) is 72 from the Python
gate; eleven source files sit above 300 lines and none is in any decomposition spec.

**10. Documents that contradict the tree.** `docs/reports/TEST-REPORT.md:8-15`
says "do not read any number below as current"; `docs/reports/SDLC_HYGIENE_REPORT.md`
reports 161 tests at 86.99 %; `docs/SDLC_HYGIENE_AND_GAP_ANALYSIS.md` is the only
loose file at `docs/` root and its §2 contradicts `god-file-decomposition.md`.
`god-file-decomposition.md:21,53` states a branch floor of 85 % against a policy of
80. `harness/README.md:1` says v2.0 and `harness/CONTRACT.md:1` v2.1, outside the
six mirrors `test_documentation_truth.py` pins. Five specs whose work has landed
still show every acceptance box open: `verdict-propagation.md` (15),
`plan-review-framework.md` (11), `agent-read-patch-tools.md` (10),
`mangomas-integration-core.md` (9), `node-policy-wiring.md` (7; its AC-4 grep
returns nothing today). This is the R-TDH-8 failure class, back within two days,
because the fix ticked boxes instead of adding a gate.

**11. The Dependabot queue.** Twelve open bot PRs. #62–#66 bump action majors and
are the vehicle for Phase 1's SHA pins. #67 proposes mypy 1.11.2 → 2.3.1; the mypy
2.0 changelog drops `--python-version 3.9`, so it cannot land while
`requires-python` is `>=3.9` (NS-6). #68–#73 are `pip` bumps opened before DEC-033
removed that ecosystem and contradict DEC-031.

### Team reflection

- **Architecture.** The package boundaries are right and the flat root is a
  recorded decision; do not relitigate it. The real edge debt is *representation*:
  the same fact (retryable statuses, policy defaults, approval categories, shell
  gate logic) exists in two or three places, and every gate that exists checks one
  representation. This round is about closing the gaps between the gates, not
  about moving files.
- **SDLC / CI.** Round 2 made the gates truthful. This round makes them
  *binding* (ruleset), *tamper-evident upstream* (SHA and hash pins) and cheaper
  (caches). A required check that cannot fail is the one truthfulness defect left.
- **QA.** Coverage at 99 % lines is not the signal; it is that a suite of 30 k
  lines has duplicated fixtures the quality gate does not scan for, and two of its
  five tiers cannot be selected. Every new gate in this plan is mutation-proved
  (NS-20) before it ships, because that loop found the last batch's own defects.
- **Product.** Two features stay parked (INV-15). The visible product debt is
  documentation that disagrees with the tree in eight places; the fix is a status
  gate, not another manual re-tick.
- **Security.** The adopter templates require what the root does not do. Fix the
  root first; a contract the author does not meet is not a contract.

### Explicitly not doing

- Regrouping `harness/shared/` (DEC-020, DEC-029 stand; C-CQ-2).
- Deleting the 20 per-stack `.py` shims (DEC-004; they are converted only where
  they are byte-copies, never removed).
- Moving the Python floor to 3.10: that is NS-6, its own spec. This plan records
  which items it unblocks (#67, the soft 3.9 audit leg).
- Annotating the test suite (`--disallow-untyped-defs`, 533 findings): a project.
- Enforcing `coverage.functions` and `coverage.statements` on the Python side:
  coverage.py emits no function metric, and CONTRACT.md already records the
  Node-only scope.

## Requirements

Phase 0 — enforcement and queue hygiene (0 code lines).

- R-CQ-1: `main` MUST carry the ruleset committed at `.github/rulesets/main.json`,
  or the decision log MUST record why a single-maintainer repository declines it;
  either outcome closes NS-1 rather than carrying it a fifth release.
- R-CQ-2: The twelve open Dependabot PRs MUST be dispositioned in one decision-log
  entry: #62–#66 superseded by the SHA-pinned refs of Phase 1; #67 closed as
  blocked on NS-6 with the mypy 2.0 `--python-version 3.9` removal cited; #68–#73
  closed under DEC-031 and DEC-033.

Phase 1 — supply chain (3 PRs; `.github/workflows/**` is protected).

- R-CQ-3: Every `uses:` in `.github/workflows/*.yml` MUST reference a full 40-hex
  commit SHA with the release tag in a trailing comment; `test_workflow_contracts.py`
  MUST fail on a tag or branch reference; Dependabot's `github-actions` ecosystem
  keeps updating the SHA.
- R-CQ-4: `requirements-lock.txt` MUST carry a `--hash` for every pin (produced by
  `make lock` with `--generate-hashes`) and both workflows MUST install it with
  `--require-hashes`; `test_workflow_contracts.py` MUST fail on an install step
  without the flag and on a lock line without a hash; `make lock-check` is unchanged.
- R-CQ-5: `Dockerfile` MUST pin its base image by digest, run the runtime stage
  under a non-root `USER`, declare a `HEALTHCHECK` for the exposed port, and obtain
  pnpm through `corepack` from `packageManager` rather than a restated version; a
  test parses the file and fails on any of the four omissions.

Phase 2 — policy single-source, round 2 (4 PRs).

- R-CQ-6 (*child spec* `retry-parity`): The retryable HTTP status set MUST be one
  policy key, `nemotron.retryable_statuses`, read by `nemotron_bridge.py` and by
  `retry.ts`; a parity test in the `sampling-parity.test.ts` pattern MUST fail when
  either stack's set differs from the policy's.
- R-CQ-7: `GraphPolicy`'s field defaults MUST derive from `policy_loader`'s
  fallback constants rather than restating them, preserving the pure no-config
  fallback that `langgraph-policy-wiring.md` decided; the equality test stays as
  the regression guard.
- R-CQ-8: `build_policy_bundle.py` MUST read `policy_id`, `schema_version` and
  `agent_defaults.human_approval_required` from `governance-policy.json`;
  `make digest-regen` MUST fail closed when any of the three keys is absent.
- R-CQ-9: `test_constant_triage.TestTheInventoryIsComplete` MUST also discover
  numeric dataclass field defaults and numeric keyword-argument defaults in source
  modules, and every constant it newly surfaces MUST be triaged: `verification.timeout`
  to `orchestrator.api_timeout_sec`; the `[:200]`/`[:80]` truncations in
  `langgraph/nodes.py` and the `[:40]`/`[:48]` pair in `plan_rules.py` to one named
  constant each; `meta_tools`' poll slack to DEC-039; `verify_repository`'s `64` to
  the existing `SHA256_HEX_LEN`; `VULTURE_MIN_CONFIDENCE` to a new
  `limits.vulture_min_confidence` policy key read by the Makefile.
- R-CQ-10: The five `python-version: "3.11"` literals across the two workflows MUST
  collapse to one workflow-level value that `test_workflow_contracts.py` requires to
  be either a matrix member or explicitly declared as the primary interpreter; the
  NVIDIA base URL and the `/chat/completions` path MUST be one named constant per
  stack with a parity test, and the secret-mask prefix and suffix widths MUST be
  named constants on the Python side as they are in `secret-masker.ts`.

Phase 3 — dead and duplicated code (4 PRs).

- R-CQ-11: `check_dedup.py` MUST cover `*.sh` as it covers `*.py`: each per-stack
  shell script is either a delegator under `dedup.max_shim_lines` that `exec`s the
  shared script, or is reported as a copy and fails the gate; the nine copies are
  converted to delegators and the "keep in sync manually" comment in
  `run_vitest.sh` is deleted.
- R-CQ-12: `_policy_is_absent`, `_decision_id_regex` and `FALLBACK_ID_PATTERN`
  MUST have one definition in a stdlib-only module under `harness/shared/gates/`
  (the location DEC-020 reserved for new gate code) imported by both standalone
  gates; the PEP 562 deprecation shim body MUST have one implementation that the
  four modules call with their names table.
- R-CQ-13: `harness/shared/langgraph/ablation.py` MUST move under
  `harness/shared/experimental/` with a deprecation shim at the old path, and
  `synthesis.lats_enabled` MUST either gain a reader or be recorded in the decision
  log as a reserved key that `validate_policy.py` checks for shape only.
- R-CQ-14: Every deprecation shim MUST declare the `pyproject.toml` version that
  removes it, and `test_deprecation_shims.py` MUST fail once the declared version
  is at or below the current one, so "one minor release" becomes a check rather
  than a promise; the removal version is the minor after the release NS-3 settles.
- R-CQ-15: Duplicated test fixtures MUST have one definition: `mock_workspace`,
  `mock_complete_chat`, `chat_response`/`tool_call`, `run_script`, the API-server
  key fixture, `_passing_outcome`, the control-plane import-purity pair and
  `_write_json` consolidate into `tests/conftest.py` or `_helpers.py`;
  `_orchestrator_helpers.py` is retired; `test_test_quality.py` MUST fail on two
  test-tree functions with the same AST body so the class cannot regrow.
- R-CQ-16: `harness/node/knip.json` MUST list real entry points rather than
  `src/**`, so knip can report an unreferenced source module; `index.ts` and
  `governance/policy-anchor.ts` are each either documented as a public entry or
  deleted, and `clampToBounds` is no longer exported.

Phase 4 — CI truthfulness and cost (2 PRs; workflows protected).

- R-CQ-17: A check MUST NOT be required while it cannot fail: `dependency-audit (3.9)`
  leaves `.github/rulesets/main.json` and the derived required-checks test until
  NS-6 removes the leg, and the decision log records that the leg is advisory.
- R-CQ-18: The `secret-scan` and `dependency-audit` jobs MUST cache the Go build
  of gitleaks and osv-scanner keyed on `GITLEAKS_VERSION` and `OSV_VERSION`, and
  every `setup-python` step in `scheduled-drift.yml` MUST enable the pip cache;
  the change is measured by workflow-run usage before and after and recorded in the
  PR.
- R-CQ-19: Every registered pytest marker MUST have at least one user and every
  test tier MUST be selectable by a marker: `regression` is applied by the tier's
  own `conftest.py`, `liveness` is applied to the gate-liveness modules, the unused
  `security` marker is removed, and a test fails on a registered marker with zero
  users or a tier directory with none.

Phase 5 — structure, size and documents (4 PRs).

- R-CQ-20 (*child spec* `control-plane-package`): `harness/control-plane` MUST
  become the importable `harness/control_plane`, deleting the bespoke path loaders,
  the duplicate `testpaths`/coverage/Makefile plumbing and the two spellings in
  `test_constant_triage.py`; or the decision log MUST record why the hyphen stays,
  and the loaders collapse to the one in `_helpers.py`.
- R-CQ-21: `nemotron-client.ts` and `plan_rules.py` MUST each be split by concern
  before further feature work touches them, landing below the 60 % watch threshold
  the `tech-debt-audit` skill applies to `limits.size_budget_lines`; the split is
  by seam (transport versus stream parsing; rule families) in the manner DEC-035
  requires, and the `make validate` headroom line proves the result.
- R-CQ-22: Documents MUST agree with the tree: the six self-declared snapshots move
  to `docs/reports/archive/` behind an index that names what superseded each;
  `god-file-decomposition.md` cites the policy key instead of a branch percentage;
  `harness/README.md` and `harness/CONTRACT.md` either join `VERSION_MIRRORS` or
  drop their version strings.
- R-CQ-23: Every spec MUST carry a `Status:` line (`PROPOSED`, `IN PROGRESS`,
  `LANDED`, `SUPERSEDED`), and `plan_rules.py` MUST report a `LANDED` spec with an
  open acceptance box as a finding, so the five specs in problem item 10 are
  re-ticked once and the class cannot recur without a red gate.

Phase 6 — coverage and gate proof.

- R-CQ-24: Every slice MUST leave the coverage gate at or above the baseline
  (lines 99.29 %, branches 97.81 %) and MUST bring arc tests for the files it
  touches; the four lowest files by lines (`check_traceability.py` 93.33 %,
  `pretooluse_guard.py`, `remotes.py`, `verify_zero_skips.py` at 93.75 %) close their
  shim-only missing arcs in Phase 3's shim PR; and every new gate this plan adds is
  mutation-proved per NS-20, with the mutation named in the PR's Validation section.

Constraints.

- C-CQ-1: No slice MUST weaken an invariant in `harness/CONTRACT.md`, add an
  `xfail`, or add a skip without a decision-log entry.
- C-CQ-2: DEC-004, DEC-020 and DEC-029 stand: no module regroup, no `.py` shim
  deletion; a future move requires a superseding entry and an acyclicity test.
- C-CQ-3: Every slice is its own PR with the `make ci` and `make lint-cold` tails
  and the `secret-scan` and `dependency-audit` job URLs in its Validation section;
  a slice touching `protected_paths` MUST carry the attestation table from
  `make attestation` and the `infra-reviewed` label.
- C-CQ-4: Every moved or deprecated public symbol MUST keep a shim that emits
  `DeprecationWarning` and declares its removal version (R-CQ-14); no removal
  before the minor after the release NS-3 settles.

## Acceptance criteria

- [ ] AC-1: The GitHub branches API reports `"protected": true` for `main`, or
      `git grep -n "NS-1" harness/node/.governance/decision-log.md` matches an
      entry that declines the ruleset; `pytest harness/shared/tests/test_ci_gate_required_checks.py`
      still passes · stage: `make test-python` (R-CQ-1)
- [ ] AC-2: `git grep -n "#67" harness/node/.governance/decision-log.md` matches an
      entry naming the mypy 2.0 `--python-version 3.9` removal and NS-6, and every
      PR in #62–#73 is closed or merged · stage: `make validate` (R-CQ-2)
- [ ] AC-3: `pytest harness/shared/tests/test_workflow_contracts.py -k sha_pinned`
      passes on the tree and fails on a `tmp_path` workflow copy with one
      `uses: actions/checkout@v5` reference; `git grep -nE "uses: [^@]+@v[0-9]" .github/workflows`
      returns nothing · stage: `make test-python` (R-CQ-3)
- [ ] AC-4: `grep -c -- "--hash=sha256" requirements-lock.txt` equals the number of
      pinned requirements; `pytest harness/shared/tests/test_workflow_contracts.py -k require_hashes`
      fails on an install line without `--require-hashes` and on a lock line
      without a hash; `make lock-check` passes · stage: `make ci` (R-CQ-4)
- [ ] AC-5: `pytest harness/shared/tests -k dockerfile` fails on a `tmp_path`
      Dockerfile missing any of `@sha256:`, `USER`, `HEALTHCHECK` or a
      `corepack` line without a restated version, and passes on the tree;
      `git grep -n "pnpm@" Dockerfile` returns nothing · stage: `make test-python` (R-CQ-5)
- [ ] AC-6: `pnpm exec vitest run tests/ai/e2e/retry-parity.test.ts` passes on the
      tree and fails when either `RETRYABLE_HTTP_STATUSES` or the Node predicate is
      reverted to its pre-change literal; `git grep -n "frozenset({429" harness/shared`
      returns nothing · stage: `make test-node` (R-CQ-6)
- [ ] AC-7: `pytest harness/shared/tests/test_policy_consistency.py -k GraphPolicy`
      passes, and `python -c "import ast,sys; t=ast.parse(open('harness/shared/langgraph/policy.py').read()); sys.exit(any(isinstance(n, ast.Constant) and isinstance(n.value,(int,float)) and not isinstance(n.value,bool) for n in ast.walk(t)))"`
      exits 0 · stage: `make test-python` (R-CQ-7)
- [ ] AC-8: `pytest harness/control-plane/tests/test_build_policy_bundle.py -k policy_sourced`
      fails when a `tmp_path` policy lacks `schema_version` and passes on the tree;
      `git grep -n '"agentic-ssd-governance"\|"2.0.0"' harness/control-plane/build_policy_bundle.py`
      returns nothing · stage: `make digest-regen` (R-CQ-8)
- [ ] AC-9: `pytest harness/shared/tests/test_constant_triage.py` fails on a
      `tmp_path` module carrying an untriaged `timeout: int = 300` dataclass field
      and passes on the tree; `git grep -nE "\[:(200|80|40|48)\]" harness/shared/langgraph/nodes.py harness/shared/plan_rules.py`
      returns nothing; `VULTURE_MIN_CONFIDENCE` in `Makefile` is derived from
      `limits.vulture_min_confidence` · stage: `make lint` (R-CQ-9)
- [ ] AC-10: `git grep -c 'python-version: "3.11"' .github/workflows` reports at
      most one site, and `pytest harness/shared/tests/test_workflow_contracts.py -k primary_interpreter`
      fails on a value outside the matrix that is not declared;
      `git grep -n "integrate.api.nvidia.com" harness` matches exactly one Python
      and one TypeScript source site · stage: `make test-python` (R-CQ-10)
- [ ] AC-11: `make check-dedup` fails on a `tmp_path` tree where a per-stack `.sh`
      is a byte copy of the shared one (`pytest harness/shared/tests/test_check_dedup.py -k shell`)
      and passes on the converted tree; `cmp harness/shared/run_vitest.sh harness/node/scripts/run_vitest.sh`
      exits 1 · stage: `make check-dedup` (R-CQ-11)
- [ ] AC-12: `git grep -n "def _policy_is_absent" harness/shared` and
      `git grep -n -e "has no attribute" --and -e "warnings.warn" harness/shared`
      each report one definition site; `make validate` passes and
      `pytest harness/shared/tests/test_check_projections.py harness/shared/tests/test_verify_zero_skips.py`
      passes · stage: `make test-python` (R-CQ-12)
- [ ] AC-13: `git grep -ln "langgraph.ablation" -- harness ':!*/tests/*'` lists
      only files under `harness/shared/experimental/` plus the shim;
      `python -W error::DeprecationWarning -c "import harness.shared.langgraph.ablation"`
      exits non-zero; `git grep -n "lats_enabled" harness --include=*.py`
      matches a reader or the decision log records the reserved key
      · stage: `make test-python` (R-CQ-13)
- [ ] AC-14: `pytest harness/shared/tests/test_deprecation_shims.py -k removal_version`
      fails when `pyproject.toml`'s version is raised in a `tmp_path` copy to a
      shim's declared removal version, and passes on the tree · stage: `make test-python` (R-CQ-14)
- [ ] AC-15: `git grep -n "def mock_workspace\|def agent_workspace\|def run_script\|def _passing_outcome" harness`
      reports one site each; `ls harness/shared/tests/_orchestrator_helpers.py`
      fails; `pytest harness/shared/tests/test_test_quality.py -k duplicate_body`
      fails on a `tmp_path` suite with two AST-identical test functions
      · stage: `make test-python` (R-CQ-15)
- [ ] AC-16: `pnpm exec knip` fails on a `src/` module no entry point reaches
      (probe: add an unreferenced file, run, restore) and passes on the tree;
      `git grep -n "export function clampToBounds" harness/node/src` returns nothing
      · stage: `make lint-node` (R-CQ-16)
- [ ] AC-17: `python -c "import json;print([c['context'] for c in json.load(open('.github/rulesets/main.json'))['rules'][3]['parameters']['required_status_checks']])"`
      omits `dependency-audit (3.9)`; `pytest harness/shared/tests/test_ci_gate_required_checks.py`
      passes with the same set; the decision log records the advisory leg
      · stage: `make test-python` (R-CQ-17)
- [ ] AC-18: `git grep -n "actions/cache" .github/workflows/python-package.yml`
      matches under both `secrets` and `audit`, keyed on the two version variables;
      `pytest harness/shared/tests/test_workflow_contracts.py -k pip_cache` fails
      on a `setup-python` step without `cache: pip`; the PR records run usage
      before and after · stage: `make test-python` (R-CQ-18)
- [ ] AC-19: `pytest -m regression --co -q harness/shared/tests | tail -1` collects
      exactly the tier directory's tests; `pytest harness/shared/tests -k marker_liveness`
      fails on a registered marker with zero users (`security` removed from
      `pyproject.toml`) and on a tier directory with none · stage: `make test-python` (R-CQ-19)
- [ ] AC-20: Either `python -c "import harness.control_plane.verify_repository"`
      exits 0 with `git grep -n "load_module_by_path" harness` reporting one
      definition and no control-plane caller, or the decision log records the
      hyphen and `git grep -n "control_plane" harness/shared/tests/test_constant_triage.py`
      returns nothing · stage: `make test-python` (R-CQ-20)
- [ ] AC-21: `make validate` prints a size-budget headroom line whose closest file
      is neither `plan_rules.py` nor `nemotron-client.ts`, and each of the two is
      below 60 % of `limits.size_budget_lines`; `pnpm exec eslint . --max-warnings=0`
      passes · stage: `make validate` (R-CQ-21)
- [ ] AC-22: `ls docs/reports/archive/README.md` succeeds and
      `ls docs/reports/TEST-REPORT.md docs/SDLC_HYGIENE_AND_GAP_ANALYSIS.md` fails;
      `git grep -n "85%" docs/specs/god-file-decomposition.md` returns nothing;
      `pytest harness/shared/tests/test_documentation_truth.py -k version` passes
      with `harness/README.md` and `harness/CONTRACT.md` either mirrored or de-versioned
      · stage: `make test-python` (R-CQ-22)
- [ ] AC-23: `make specs` fails on a `tmp_path` spec marked `Status: LANDED` with
      one `- [ ]` box (`pytest harness/shared/tests/test_plan_rules.py -k landed_open_box`)
      and passes on the tree; `git grep -c "^- \[ \]" docs/specs/node-policy-wiring.md`
      prints 0 · stage: `make specs` (R-CQ-23)
- [ ] AC-24: `python harness/shared/coverage_gate.py` reports lines and branches
      at or above the baseline on every slice and still exits 1 on a malformed
      `coverage.json`; each slice's PR names the mutation that made its new gate
      fail and the restore that made it pass · stage: `make coverage-python` (R-CQ-24)
- [ ] AC-25: `git diff 487870a..HEAD -G'pytest\.(skip|importorskip|mark\.(skipif|xfail))' --name-only -- 'harness/*/tests'`
      is empty on every slice; `make validate` passes · stage: `make validate` (C-CQ-1)
- [ ] AC-26: `ls harness/shared/{core,tooling,runtime}` fails, `make check-dedup`
      passes, and `ls harness/node/scripts/*.py harness/jvm/scripts/*.py | wc -l`
      prints 20 · stage: `make check-dedup` (C-CQ-2)
- [ ] AC-27: `make validate` exits 1 on a protected-path slice without
      `ALLOW_GITHUB_CHANGES=1`, and `make attestation-check FILE=<pr-body>` passes
      on each such PR's description · stage: `make validate` (C-CQ-3)
- [ ] AC-28: `pytest -W error::DeprecationWarning harness/shared/tests harness/api_server/tests -k "not deprecation_shims"`
      passes on every slice, and every shim's declared removal version is a
      semver above `pyproject.toml`'s · stage: `make test-python` (C-CQ-4)

## Steps

Ordered by dependency; one PR per numbered step unless stated.

### Phase 0 (0 code)

1. Apply the ruleset or record the declining entry; disposition #62–#73 in one
   decision-log entry (R-CQ-1, R-CQ-2). Protected: `**/.governance/**`.

### Phase 1 (3 PRs)

2. SHA-pin all 20 `uses:` references, taking #62–#66's majors; add the
   `sha_pinned` contract test (R-CQ-3). Protected: workflows.
3. `make lock` with `--generate-hashes`; `--require-hashes` on both install steps;
   the `require_hashes` contract test (R-CQ-4). Protected: workflows, `Makefile`.
4. Dockerfile digest, `USER`, `HEALTHCHECK`, `corepack`; the parsing test (R-CQ-5).

### Phase 2 (4 PRs)

5. `make spec NAME=retry-parity`, then the policy key, both readers and the parity
   test (R-CQ-6). Protected: `governance-policy.json`.
6. `GraphPolicy` defaults derived from `policy_loader` (R-CQ-7). Protected:
   `harness/shared/langgraph/**`, `policy_loader.py`.
7. `build_policy_bundle.py` reads the three keys; fail-closed test (R-CQ-8).
   Protected: none (the builder is not listed; `digest-regen` proves it).
8. Inventory discovery extended; the surfaced constants triaged; the workflow
   interpreter value; the URL, path and mask constants (R-CQ-9, R-CQ-10).
   Protected: `Makefile`, workflows, `governance-policy.json`.

### Phase 3 (4 PRs)

9. `check_dedup` covers `.sh`; nine copies become delegators (R-CQ-11).
   Protected: `check_dedup.py`, `install_hooks.sh`, `pre_push_scan.sh`,
   `pretooluse_guard.sh`, `validate_specs.sh`.
10. `harness/shared/gates/_policy_probe.py` and `_deprecation.py`; the four shims
    and two gates call them; the shim-only arcs in the four lowest-coverage files
    (R-CQ-12, R-CQ-24). Protected: `check_projections.py`, `governance/**`,
    `write_policy.py`.
11. `ablation.py` to `experimental/`; `lats_enabled` reader or DEC; removal
    versions on every shim and the version-keyed test (R-CQ-13, R-CQ-14).
    Protected: `harness/shared/langgraph/**`.
12. Fixture consolidation; `_orchestrator_helpers.py` retired; duplicate-body
    scan in `test_test_quality.py`; knip entry points (R-CQ-15, R-CQ-16).

### Phase 4 (2 PRs)

13. Required-checks list drops the advisory leg; decision-log entry (R-CQ-17).
    Protected: `.github/rulesets/main.json` is not listed; `test_ci_gate_required_checks.py`
    matches `harness/shared/tests/*ci_gate*.py`.
14. Go-build caches; drift-job pip caches; run-usage measurement (R-CQ-18); tier
    markers and the marker-liveness test (R-CQ-19). Protected: workflows,
    `pyproject.toml`.

### Phase 5 (4 PRs)

15. `make spec NAME=control-plane-package`, then the rename or the DEC (R-CQ-20).
    Protected: `pyproject.toml`, `Makefile`, `governance-policy.json`,
    `harness/control-plane/*.py`.
16. `nemotron-client.ts` split; `plan_rules.py` split (R-CQ-21). Protected:
    `plan_rules.py`.
17. Archive index; spec floor citation; version mirrors (R-CQ-22).
18. `Status:` line on every spec; the `LANDED`-with-open-box rule; re-tick the
    five landed specs (R-CQ-23). Protected: `plan_rules.py`.

### Phase 6

19. Rides every step: coverage at baseline, arc tests, and the mutation named in
    each PR (R-CQ-24, C-CQ-1 … C-CQ-4).

## Files touched

Protected paths are marked (P); every (P) slice needs the attestation table and
the `infra-reviewed` label.

- Phase 0: `harness/node/.governance/decision-log.md` (P), `NEXT_STEPS.md`.
- Phase 1: `.github/workflows/python-package.yml` (P),
  `.github/workflows/scheduled-drift.yml` (P), `requirements-lock.txt`,
  `Makefile` (P), `Dockerfile`, `harness/shared/tests/test_workflow_contracts.py`,
  `harness/shared/tests/test_dockerfile_contract.py` (new).
- Phase 2: `docs/specs/retry-parity.md` (new), `harness/shared/governance-policy.json` (P),
  `harness/shared/nemotron_bridge.py`, `harness/node/src/ai/nemotron/retry.ts`,
  `harness/node/src/ai/nemotron/policy.ts`, `harness/node/tests/ai/e2e/retry-parity.test.ts` (new),
  `harness/shared/langgraph/policy.py` (P), `harness/shared/policy_loader.py` (P),
  `harness/control-plane/build_policy_bundle.py`, `harness/control-plane/tests/test_build_policy_bundle.py`,
  `harness/shared/tests/test_constant_triage.py`, `harness/shared/governance/verification.py` (P),
  `harness/shared/langgraph/nodes.py` (P), `harness/shared/plan_rules.py` (P),
  `harness/shared/meta_tools.py`, `harness/control-plane/verify_repository.py`,
  `harness/shared/debug_dump.py` (P).
- Phase 3: `harness/shared/check_dedup.py` (P), `harness/node/scripts/*.sh`,
  `harness/jvm/scripts/*.sh`, `harness/shared/gates/__init__.py` (new),
  `harness/shared/gates/_policy_probe.py` (new), `harness/shared/gates/_deprecation.py` (new),
  `harness/shared/check_projections.py` (P), `harness/shared/governance/verify_zero_skips.py` (P),
  `harness/shared/write_policy.py` (P), `harness/shared/nemotron_bridge.py`,
  `harness/shared/autonomous_healing.py`, `harness/shared/lats_optimizer.py`,
  `harness/shared/tool_budget.py`, `harness/shared/langgraph/ablation.py` (P),
  `harness/shared/experimental/ablation.py` (new), `harness/shared/experimental/lats_optimizer.py`,
  `harness/shared/tests/test_deprecation_shims.py`, `harness/shared/tests/conftest.py`,
  `harness/shared/tests/_helpers.py`, `harness/shared/tests/_orchestrator_helpers.py` (deleted),
  `harness/shared/tests/regression/conftest.py`, `harness/shared/tests/test_test_quality.py`,
  `harness/api_server/tests/conftest.py`, `harness/control-plane/tests/conftest.py`,
  `harness/node/knip.json`, `harness/node/src/ai/nemotron/index.ts`,
  `harness/node/src/governance/policy-anchor.ts`, `harness/node/src/ai/nemotron/request-body.ts`.
- Phase 4: `.github/rulesets/main.json`, `harness/shared/tests/test_ci_gate_required_checks.py` (P),
  `.github/workflows/*.yml` (P), `pyproject.toml` (P),
  `harness/shared/tests/regression/conftest.py`, `harness/shared/tests/test_marker_liveness.py` (new).
- Phase 5: `docs/specs/control-plane-package.md` (new), `harness/control_plane/` (rename, P),
  `pyproject.toml` (P), `Makefile` (P), `harness/shared/governance-policy.json` (P),
  `harness/node/src/ai/nemotron/nemotron-client.ts`, `harness/node/src/ai/nemotron/stream.ts` (new),
  `harness/shared/plan_rules.py` (P), `harness/shared/plan_rules_*.py` (new),
  `docs/reports/archive/` (new), `docs/specs/god-file-decomposition.md`,
  `harness/README.md`, `harness/CONTRACT.md` (P), `harness/shared/tests/test_documentation_truth.py`,
  `docs/specs/*.md` (status lines), `harness/shared/tests/test_plan_rules.py`.
- Phase 6: `harness/shared/tests/**`, `harness/control-plane/tests/**`.

## Invariants touched

- INV-1: unchanged in scope; the `.sh` delegators (R-CQ-11) route `pre_push_scan.sh`
  through the shared kernel exactly as the `.py` shims do, and `secrets` still runs
  in its own job. Proved by `make secrets` in CI on every Phase 3 slice.
- INV-2: R-CQ-19 adds markers and removes one; no skip or waiver changes. Proved by
  `make verify-zero-skips-python` and `verify-zero-skips` on every slice (AC-25).
- INV-3: the remote checker is untouched; the `.sh` delegators call the same
  `remotes.py`. Proved by `make remotes`.
- INV-5: R-CQ-17 changes which checks are *required*, never which gates *run*;
  `test_ci_gate_coverage.py` keeps mapping every `ci_required_targets` entry to a
  reachable target. R-CQ-3 and R-CQ-4 add workflow-shape tests.
- INV-15: R-CQ-13 keeps `lats_enabled: false` as the only switch; moving
  `ablation.py` under `experimental/` narrows, not widens, the runtime surface.
- INV-16: no cognitive-signal path is touched; `pytest -m governance` runs on
  every slice.
- INV-17: this document, the two child specs and the `Status:` rule (R-CQ-23)
  are gated by `make specs`.

## Validation matrix

- `make ci` on every slice: ruff + mypy + vulture + pytest + coverage floors from
  `governance-policy.json → coverage.{lines,branches,per_file}` + lock-check +
  specs + remotes + validate + check-dedup + digest-regen (R-CQ-3 … R-CQ-24, C-CQ-1).
- `make lint-cold` on every slice; `secret-scan` and `dependency-audit` by their
  CI job URLs (C-CQ-3).
- `make test-node` and `make lint-node` for R-CQ-6, R-CQ-10, R-CQ-16, R-CQ-21.
- `make check-dedup` before and after the `.sh` conversion, with the byte-copy
  probe (R-CQ-11, C-CQ-2).
- `make validate` with and without `ALLOW_GITHUB_CHANGES=1` on every
  protected-path slice (C-CQ-3, R-CQ-1, R-CQ-2, R-CQ-21).
- `pytest -W error::DeprecationWarning` on the shim slices (C-CQ-4, R-CQ-12,
  R-CQ-13, R-CQ-14).
- `make specs` on this document, the child specs, and the re-ticked specs
  (R-CQ-20, R-CQ-23).
- Mutation proof per NS-20 on every new gate: R-CQ-3, R-CQ-4, R-CQ-5, R-CQ-8,
  R-CQ-9, R-CQ-11, R-CQ-14, R-CQ-15, R-CQ-16, R-CQ-19, R-CQ-23 (R-CQ-24).
- Coverage: floors from policy; baseline from the gate on `487870a` is lines
  99.29 %, branches 97.81 %, 76 files measured.
- CI cost: `actions_get get_workflow_run_usage` on the last green `main` run
  before Phase 4 and the first after (R-CQ-17, R-CQ-18).

## Backward compatibility

Every import path on `487870a` resolves for one minor release after its
deprecation, and every shim now says which release removes it (R-CQ-14, C-CQ-4).
`harness.shared.langgraph.ablation` keeps importing through a warning shim.
`GraphPolicy()` keeps its no-config defaults; they are derived from the same
constants they were pinned equal to, so no value changes. `RETRYABLE_HTTP_STATUSES`
stays exported from `nemotron_bridge` with the same members, now read from policy;
the Node predicate changes behaviour for 501, 505–599 and that is the point (the
child spec decides the set; the Python one is the documented intent). The per-stack
`.sh` files keep their paths and their invocation contract; only their bodies
become `exec` delegators, which is the shape `harness/shared/pretooluse_guard.sh`
already has. `requirements-lock.txt` stays the install input; `--require-hashes`
rejects only an unhashed line, and `make lock` regenerates hashes. The
`control-plane` rename, if chosen, keeps a `harness/control-plane/` shim directory
for one minor release so the per-stack `Makefile` templates that reference it keep
working. Removal of `_orchestrator_helpers.py` affects two test modules, retargeted
in the same PR. The `security` marker is removed only because nothing uses it; a
future user re-registers it.

## Open questions

1. **Ruleset.** Apply `.github/rulesets/main.json`, or record the decline. Blocks
   nothing in code; blocks the claim that any gate is enforced.
2. **Hash-verified installs.** `--require-hashes` makes every future lock
   regeneration produce a larger diff. Accept, or keep version pins only and record
   why. Blocks step 3.
3. **Where `nemotron.retryable_statuses` lives and what it contains.** Python's
   enumerated set or Node's 5xx range. Decided in the `retry-parity` child spec.
4. **`ablation.py` under `experimental/`.** Protected path; needs attestation and
   a DEC in the DEC-027 manner.
5. **`harness/control-plane` rename.** Highest-churn item; the alternative is a DEC
   that keeps the hyphen and collapses the loaders to one. Decided in the child spec.
6. **`dependency-audit (3.9)`.** Drop from the required set now (R-CQ-17) or fold
   into NS-6. Recommended: drop now; a required check that cannot fail teaches
   readers that required means nothing.
7. **Test tier markers.** Whether `liveness` is applied by file-name convention
   (a `conftest` hook) or by explicit `pytestmark` in each module.
