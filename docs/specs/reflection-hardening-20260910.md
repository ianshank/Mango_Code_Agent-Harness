# Spec: reflection-hardening-20260910

Spec class: program-plan

> Status: IN PROGRESS · Date: 2026-09-10 · Base: `origin/main` @ `30f545d`
> (PR #102) plus hotfix `c175a83` on `cursor/restore-main-ci-green-f4b2`.
>
> **Spec class:** program-plan — requirement IDs below name scheduled work for
> this increment, so the traceability gate counts them without requiring an
> implementation citation until the work lands.
>
> Ledger increment, not a from-scratch audit. Prior program plans already ran
> the full-team reflection: `docs/specs/tech-debt-hardening-plan.md` (29/29
> ticked), `docs/specs/code-quality-tech-debt-plan.md` (CLOSED),
> `docs/specs/2026-standards-remediation-plan.md` (IN PROGRESS; Phase B Done),
> `docs/specs/reflection-hardening-increment.md` (Steps 1–5 product work landed
> on PR #124; header was stale). `.mango/skills/tech-debt-audit/SKILL.md`
> forbids re-deriving those findings. This document does **not** re-specify
> `reasoner-bridge-tool-parity`, `python-floor-310`, `gate-hardening`, or
> `god-file-decomposition`.

## Context7 disclosure

Context7 MCP `resolve-library-id` was retried once each for pytest, ruff, and
mypy at implementation time (documentation only, never product code). All three
returned `Monthly quota exceeded`. No requirement below is sourced from
Context7. Fallback URLs that actually answer the pin-specific questions:

- pytest / pytest-cov: https://docs.pytest.org/en/stable/ — this repository
  MUST NOT use `--cov-fail-under` (blended line+branch); floors are
  `coverage.lines` and `coverage.branches` in `governance-policy.json` applied
  by `coverage_gate.py` (C-RH2-5)
- ruff: https://docs.astral.sh/ruff/ — `ruff format --check` is already the
  lint gate (NS-33)
- mypy: https://mypy.readthedocs.io/ — 2.x + `warn_unused_ignores` already
  landed (DEC-064)
- GitHub Actions required checks: https://docs.github.com/en/repositories/configuring-branches-and-merges-in-your-repository/managing-rulesets
  — a required context that is never reported holds merge **only if a ruleset
  is applied**; today `GET …/rules/branches/main` is still empty (NS-1)

## Problem statement

**1. `main` was red after PR #102.** Run
[34513712396](https://github.com/ianshank/Mango_Code_Agent-Harness/actions/runs/34513712396):
11 failed, 4903 passed. All 11 were inverted NS-17 absence pins in
`test_ns17_rollback_regression.py` against the forward feature DEC-060 already
restored. PR #102 also deleted two forward `{open_gaps}` tests. The atomic
`append_locked` write is real hygiene and MUST be kept (R-RH2-1).

**2. NS-21 is documented landed and is silently off.** PR #99 added
`post-*-run.sh` + `lib/record_post_run.sh`. PR #115 (`8e58b89e`) deleted those
four files and the DEBUG / record-contract tests. `HookRunner.run_hook` no-ops
when the script is missing, so observation dies and the suite stays green.
`NEXT_STEPS.md` §6 still claims NS-21 landed on #99.

**3. `test_workflow_contracts.py` is an 8-line time bomb.** Live
`limits.test_size_budget_lines` is 700; the file is 692. The next contract pin
fails `validate_invariants.py` with no feature work.

**4. Traceability is green at the ratchet, not at a fully cited corpus.**
`make validate` on the hotfix head printed 203 uncited contract IDs against a
ratchet of 203. `R-GEA-5` stays uncited on purpose. The ratchet MUST only fall
(C-RH2-2).

**5. Stale ticks and owner P0s.** Remediation AC-23 is still `[ ]` while
`requires-python >= 3.10` is live; the written `git grep 3.9` still matches
historical comments. Reflection header still says Steps 3–5 are unstarted
while AC-2…AC-6 are `[x]`. NS-1/2/3/30 and Phase E remain owner-gated.

## Remaining-item ledger

| ID | Status at this head | Disposition this increment |
|---|---|---|
| NS-1 / R-SR-1 | ruleset export exists; `GET …/rules/branches/main` still empty | **Owner / parked.** Do not implement (C-RH2-3). |
| NS-2 / R-SR-2 | credential DEC-014; `feature/governed-run-console` | **Owner / parked.** Hard-gates Phase E (C-RH2-3). |
| NS-3 / R-SR-4 | no `v*` tags locally | **Owner / parked.** |
| NS-30 / R-SR-3 | `ls LICENSE` fails | **Owner / parked.** Apache-2.0 recommended, not chosen here. |
| NS-6 / R-SR-23 | `requires-python >= 3.10`, DEC-064, matrix 3.10/3.12/3.14 | **Landed.** Remediation AC-23 stays `[ ]` until its written grep is empty or rewritten; comments still mention historical 3.9. |
| NS-18 / R-RBT-* | PR #124 | **Landed.** Do not re-specify. |
| NS-21 | scripts deleted by #115; §6 still says landed | **Restore this increment** (R-RH2-2). |
| NS-35 | mutmut | **Parked** (needs NS-6 packaging half; out of scope). |
| NS-36 `required_signatures` | waits on NS-1 | **Owner / parked.** |
| NS-39 | ratchet 203, headroom 0 | **Lower with citations this increment** (R-RH2-4). Leave `R-GEA-5` uncited. |
| NS-9 / R-SR-27 LangGraph swallow | DEC-053 park | **Parked on NS-2.** Do not touch `graph_topology.py`. |
| R-SR-26…29 Phase E | JVM → LangGraph → openspec → mirroring | **Parked on NS-2** (C-RH2-3). |
| R-RHI-3…5 | AC-4…AC-6 `[x]` on PR #124 | **Landed.** Header MUST be corrected (R-RH2-6). |
| R-RHI-6 / AC-9 | LangGraph park | **Blocked by NS-2.** |
| Dependabot #103–#108 / #125 / #126 | fail `build*` on red `main` | **Rebase after `main` is green.** `NODE24_ACTION_MAJORS` are floors (checkout 5, setup-python 6, setup-node 5, setup-go 6, pnpm/action-setup 5); SHA pin + `# vX.Y.Z` MUST remain (R-RH2-3). |
| Production files 90%+ of 500 | `command_actions.py` 479, `meta_tools.py` 476, `write_policy.py` 475, `tool_executors.py` 459, `graph_topology.py` 454 | **Watch.** Split only when a scheduled edit would cross 500. Seams named in the planner output; not this increment. |

## Requirements

- R-RH2-1: Inverted rollback modules `test_ns17_rollback_regression.py` and
  `test_ns21_rollback_regression.py` MUST remain absent from
  `harness/shared/tests/regression/`; `test_inverted_ns17_ns21_rollback_pins_stay_absent`
  MUST fail if either filename returns. The `append_locked` `O_EXCL` write and
  the two `{open_gaps}` planner tests MUST remain. Those filenames MUST NOT be
  added to `REQUIRED_REGRESSION_MODULES` (C-RH2-4).
- R-RH2-2: The four NS-21 enablement files from PR #99 MUST be restored
  (`post-planner-run.sh`, `post-nemotron-reasoner-run.sh`,
  `post-verifier-run.sh`, `.mango/hooks/lib/record_post_run.sh`).
  `HookRunner.run_hook` MUST log DEBUG and skip when a permitted script is
  missing or is not a file. `loop.py` MUST keep constructing every
  `post-{role}-run` name in `ACTIVE_TO_CANONICAL`. A disk-liveness test MUST
  fail if any of those scripts is deleted. DEC-003 MUST stay dormant in
  `.mango/settings.json` (C-RH2-6).
- R-RH2-3: Workflow SHA/Node-24 helpers MUST live in
  `harness/shared/tests/_workflow_parse.py`. `TestActionsRunOnNode24` and
  `TestParserIsNotVacuous` MUST live in `test_workflow_pins.py`.
  `TestTheAttestationCheckRunsWhereItCanBeRead`, `TestAttestationShaBinding`,
  and `TestProtectionReport` MUST live in `test_workflow_attestation.py`.
  Public test names MUST be preserved. `job_sections` MUST remain importable
  from `test_workflow_contracts.py`. `make validate` MUST still reject a
  701-line test file. `NODE24_ACTION_MAJORS` values are floors, not pins of a
  specific patch.
- R-RH2-4: `traceability.max_uncited_contract_requirement_ids` MUST be lowered
  in the same policy edit as new both-side citations, never raised.
  `test_traceability_scope.ACCEPTED_RATCHET_CEILING` MUST move with it.
  `R-GEA-5` MUST remain uncited.
- R-RH2-5: Coverage verdicts MUST be read from `coverage_gate.py` against
  `coverage.lines` / `coverage.branches` / `coverage.per_file`. pytest-cov's
  blended `Cover` column MUST NOT be treated as the gate (C-RH2-2).
- R-RH2-6: `docs/specs/reflection-hardening-increment.md` header MUST stop
  claiming Steps 3–5 are unstarted. Reflection AC-7 / AC-8 MUST be ticked only
  after their commands succeed. `NEXT_STEPS.md` NS-21 MUST describe the #115
  deletion and this restore, not an intact #99 landing.
- C-RH2-1: This increment MUST NOT regroup `harness/shared/` (DEC-020).
- C-RH2-2: This increment MUST NOT raise or lower `coverage.lines` or
  `coverage.branches`, and MUST NOT raise the uncited ratchet.
- C-RH2-3: This increment MUST NOT implement NS-1, NS-2, NS-3, NS-30, Phase E,
  NS-36 `required_signatures`, NS-35 mutmut, HITL, LATS, licence text, or the
  LangGraph `except ImportError` swallow (NS-9).
- C-RH2-4: This increment MUST NOT revive inverted NS-17/NS-21 absence pins
  under the retired filenames without superseding DEC-060.
- C-RH2-5: Context7 MUST be used for documentation lookup only, never to
  generate product code.
- C-RH2-6: Restoring post-run scripts MUST NOT bind them in
  `.claude/settings.json` (DEC-003).

## Acceptance criteria

- [x] AC-1: `ls harness/shared/tests/regression/test_ns17_rollback_regression.py`
      and `ls harness/shared/tests/regression/test_ns21_rollback_regression.py`
      both fail (files absent); `pytest harness/shared/tests/test_agent_prompts.py -k open_gaps`
      passes the two restored tests; `pytest harness/shared/tests/regression/test_regression_tier_pin.py -k inverted_ns17`
      fails if either retired filename is restored under `REGRESSION_DIR`
      · stage: `make ci` (R-RH2-1, C-RH2-4) — **hotfix `c175a83`**. GitHub run
      [34533054925](https://github.com/ianshank/Mango_Code_Agent-Harness/actions/runs/34533054925)
      `build-full` SUCCESS. `coverage_gate.py`: lines 98.83% ≥ `coverage.lines`,
      branches 96.66% ≥ `coverage.branches`. Local `make lint-cold`:
      `Success: no issues found in 310 source files`.
- [x] AC-2: `ls .mango/hooks/post-planner-run.sh .mango/hooks/post-nemotron-reasoner-run.sh .mango/hooks/post-verifier-run.sh .mango/hooks/lib/record_post_run.sh`
      succeeds; `pytest harness/shared/tests/test_orchestrator_hooks.py -k "PermittedHookMissing or PostRunHookRecord or allowlist_covers"`
      passes; `pytest harness/shared/tests/test_agent_surface_liveness.py -k post_run_hook_exists`
      fails if any `post-{role}-run.sh` for `ACTIVE_TO_CANONICAL` is deleted;
      `ls harness/shared/tests/regression/test_ns21_rollback_regression.py`
      fails (file absent, DEC-060) · stage: `make test-python` (R-RH2-2, C-RH2-4, C-RH2-6)
- [x] AC-3: `wc -l harness/shared/tests/test_workflow_contracts.py harness/shared/tests/test_workflow_pins.py harness/shared/tests/test_workflow_attestation.py harness/shared/tests/_workflow_parse.py`
      each print a count strictly below `limits.test_size_budget_lines` (280 / 227 / 210 / 87 vs 700);
      `pytest harness/shared/tests/test_workflow_pins.py -k node24`
      and `pytest harness/shared/tests/test_workflow_attestation.py -k attestation_sha`
      collect the moved public names; `pytest harness/shared/tests/test_validate_invariants.py -k test_check_test_size_budget_fails_one_line_over`
      still fails closed on a 701-line test file · stage: `make validate` (R-RH2-3)
- [x] AC-4: `python harness/shared/governance/check_traceability.py --workspace .`
      prints an uncited count equal to the new
      `traceability.max_uncited_contract_requirement_ids` (191, headroom 0);
      `R-GEA-5` remains in the uncited list; raising the policy key above
      `ACCEPTED_RATCHET_CEILING` fails
      `pytest harness/shared/tests/test_traceability_scope.py -k ratchet_may_only_be_lowered`
      · stage: `make validate` (R-RH2-4, C-RH2-2)
- [x] AC-5: `ls LICENSE` still fails; `git tag -l v2.4.0` still prints nothing;
      `ls harness/jvm` still succeeds; no new `DEC-` parks LangGraph under
      `experimental/` · stage: `make test-python` (C-RH2-3, C-RH2-1)
- [x] AC-6 (rejection case): deleting a restored `post-*-run.sh` fails
      `pytest harness/shared/tests/test_agent_surface_liveness.py -k post_run_hook_exists`;
      a 701-line file under `harness/shared/tests/` fails `make validate`
      (`pytest harness/shared/tests/test_validate_invariants.py -k test_check_test_size_budget_fails_one_line_over`);
      restoring `test_ns17_rollback_regression.py` fails
      `pytest harness/shared/tests/regression/test_regression_tier_pin.py -k inverted_ns17`
      · stage: `make ci` (R-RH2-2, R-RH2-3, C-RH2-4)

## Steps

1. Hotfix on `30f545d` — keep `memory_store.append_locked`, delete inverted
   pins, restore `{open_gaps}` tests, pin filenames absent — produces `c175a83`;
   consumes DEC-060.
2. This spec — produces `docs/specs/reflection-hardening-20260910.md`; consumes
   the planner ledger.
3. NS-21 restore from `b1722713` plus DEBUG skip paths plus liveness — produces
   the four hook files and hook tests; consumes PR #99 contents.
4. Split `test_workflow_contracts.py` via `_workflow_parse.py` — produces the
   three test modules; consumes the live 692-line file.
5. NS-39 citations + ratchet lower + stale AC ticks + `NEXT_STEPS.md` NS-21
   truth — produces policy/digest edits; consumes `check_traceability.py`
   output on the green head.
6. Record owner P0s / Phase E / Dependabot rebase — produces the ledger table
   above; consumes nothing new.

## Files touched

Protected paths are marked (P). Each (P) slice carries the attestation table
and needs `infra-reviewed` / `ALLOW_GITHUB_CHANGES=1`.

- Hotfix (landed): `harness/shared/memory_store.py`,
  `harness/shared/tests/test_hypothesis_revision.py`,
  `harness/shared/tests/test_agent_prompts.py`,
  `harness/shared/tests/regression/test_regression_tier_pin.py`,
  deleted inverted modules, `CHANGELOG.md`
- This spec: `docs/specs/reflection-hardening-20260910.md`
- NS-21: `.mango/hooks/post-planner-run.sh` (P),
  `.mango/hooks/post-nemotron-reasoner-run.sh` (P),
  `.mango/hooks/post-verifier-run.sh` (P),
  `.mango/hooks/lib/record_post_run.sh` (P),
  `harness/shared/orchestrator/hook_runner.py` (P),
  `harness/shared/tests/test_orchestrator_hooks.py`,
  `harness/shared/tests/test_agent_surface_liveness.py`
- Split: `harness/shared/tests/_workflow_parse.py`,
  `harness/shared/tests/test_workflow_pins.py`,
  `harness/shared/tests/test_workflow_attestation.py`,
  `harness/shared/tests/test_workflow_contracts.py`,
  ticked selectors in `docs/specs/tech-debt-hardening-plan.md`,
  `docs/specs/code-quality-tech-debt-plan.md`,
  `docs/specs/2026-standards-remediation-plan.md`,
  `docs/specs/reflection-hardening-increment.md`
- NS-39 / doc truth: `harness/shared/contract_citations.py`,
  `harness/shared/tests/test_contract_citations.py`,
  `harness/shared/tests/test_traceability_scope.py`,
  `harness/shared/governance-policy.json` (P),
  `NEXT_STEPS.md`, `CHANGELOG.md`

## Invariants touched

- INV-2: NS-21 restore adds no skips; POSIX-only post-run record tests keep
  the existing DEC-026 waiver shape. Proved by `verify-zero-skips`.
- INV-5: no Make target added or removed from `ci`.
- INV-6: `.mango/hooks/**` and `orchestrator/hook_runner.py` stay protected;
  attestation names each hunk.
- INV-8 / INV-9: HookRunner still refuses unlisted names; missing permitted
  scripts skip rather than spawn bash on a directory.

## Validation matrix

- `make ci` — ruff + mypy + pytest + coverage (≥ `coverage.lines` and
  `coverage.branches` from `governance-policy.json`) + check-dedup +
  `validate_invariants` (R-RH2-5)
- coverage target: `governance-policy.json → coverage.lines` (lines) and
  `coverage.branches` (branches); `coverage.per_file` remains true;
  pytest-cov's blended `Cover` column is not the gate
- Context7 is documentation lookup only, never product code (C-RH2-5)
- `make lint-cold` on the pushed head
- `make validate` with `ALLOW_GITHUB_CHANGES=1` for protected-path commits
- Negative tests: AC-6 (missing post-run script, 701-line test file, revived
  inverted pin)
- Doc truth: reflection-hardening-increment header / AC-7 / AC-8 and
  `NEXT_STEPS.md` NS-21 row (R-RH2-6)

## Backward compatibility

No public Python API change. `job_sections` / `PINNED_USES` /
`NODE24_ACTION_MAJORS` remain importable from `test_workflow_contracts.py`.
Post-run JSONL under `.mango/.state/post-run.jsonl` is additive observation.
DEC-003 stays dormant. Dependabot majors above the Node 24 floors remain
allowed; the SHA-pin comment form does not change.

## Open questions

1. **Licence text (NS-30).** Still the owner's choice (MIT / Apache-2.0 /
   proprietary). This increment does not write a `LICENSE`.
2. **Python 3.11 floor trigger.** Inherited from
   `reflection-hardening-increment.md` open question 1 / NS-6 dated trigger
   before 2026-10-31. Not scheduled here.
3. **Remediation AC-23 grep.** The floor is `>=3.10`; the written
   `git grep 3.9` still matches comments. Correct the selector in a later
   doc pass rather than rewriting history in this increment.

## openspec-peer-review

- **Architecture.** Package boundaries (`governance/`, `orchestrator/`,
  `langgraph/`) stay. DEC-020 stands. Facade re-exports on the workflow-test
  split. No regroup of `harness/shared/`. Sign-off: proceed.
- **SDLC / CI.** Gates remain advisory until NS-1. The hotfix is the
  DEC-024 answer to PR #102 merging red. Protected-path attestation is
  required for hooks + `hook_runner.py` + policy. Sign-off: proceed with
  `infra-reviewed`.
- **QA.** Coverage from `coverage_gate.py`, not the blended `Cover` column.
  NS-21 liveness is the test that would have failed #115. Size-budget
  rejection stays in `test_validate_invariants.py`. Sign-off: proceed.
- **Product.** Owner P0s and Phase E stay parked. NS-21 restore is a product
  observation hole, not ceremony. Sign-off: proceed.

## repo-invariant-review

Predicted collisions this change will trip if attestation/`infra-reviewed`
is omitted: `[FAIL] Protected Paths` on `.mango/hooks/**`,
`harness/shared/orchestrator/hook_runner.py`,
`harness/shared/governance-policy.json`. Size-budget: the split is the
remedy for `test_workflow_contracts.py` at 692/700. Coverage: restored hook
DEBUG branches need the restored tests or `hook_runner.py` misses
`coverage.per_file`.

## Re-measure on this head

Live ceilings from `governance-policy.json`: `limits.size_budget_lines` 500,
`limits.test_size_budget_lines` 700. `coverage.lines` 90, `coverage.branches`
80, `coverage.per_file` true. Do not read pytest-cov's blended `Cover` column.

**Production watch (≥90% of 500, split only when an edit would cross):**
`command_actions.py` 479, `meta_tools.py` 476, `write_policy.py` 475,
`tool_executors.py` 459, `graph_topology.py` 454. Next: `authority_call_analysis.py`
443, `code_symbols.py` 440, `check_traceability.py` 437, `plan_rules.py` 426,
`broker.py` 424, `loop.py` 412.

**Test watch after the workflow split:** closest is now
`test_agent_surface_liveness.py` 678/700 (post-run liveness added here).
Then `test_code_safety.py` 664, `test_hypothesis_revision.py` 651,
`test_authority_call_sites.py` 644, `test_command_actions.py` 630.
`test_workflow_contracts.py` is 280 after the split (was 692).

`_LOG_COMMAND_CHARS = 200` remains a private log truncation; `test_constant_triage`
skips `_`-prefixed names. vulture stays on `make lint-python` against
`vulture_whitelist.py`. Remeasure coverage via `coverage_gate.py` on the
pushed head, not from this table.
