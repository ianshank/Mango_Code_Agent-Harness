# Spec: Tech-Debt Reduction & Hardening Plan

> Status: PROPOSED, revision 2 (peer-reviewed) · Date: 2026-09-02 · Base: `main` @ `2555ca0`
>
> Revision 2 is the output of the `openspec-peer-review` step: four independent
> reviewers (Architecture, SDLC/CI, QA, Product) with no part in writing
> revision 1 checked every claim against the code and the decision log. What
> they changed is recorded in **Review record** below so the next audit does
> not re-derive it. The document is a spec so the plan tier of `make specs`
> (INV-17) gates it. Slices marked *child spec* get their own `make spec`
> before implementation.

## Executive summary

| Phase | Outcome | PRs | Risk | Owner decision needed |
|---|---|---|---|---|
| 0a | Ruleset on `main`: the nine required checks and CODEOWNERS review; CI status becomes the only accepted evidence of verification | 0 code + 1 doc | low | **yes**: apply the ruleset (admin) |
| 0b | `main` green: `input_schema` regression, langgraph marker + install, shadow-planner test path, dead `.mcp_storage` rules, one version string | 1 (protected: workflow) | low | **yes**: version number |
| 0c | Reconcile five landed specs whose acceptance boxes are stale | 1 | low | no |
| 1 | Universal dependency lock; Dependabot queue (#38–#46) incl. the ruff bump; GitHub Actions on Node 24; nightly drift runs `lint` | 3 | medium | **yes**: adopt `uv` for the lock |
| 2 | Policy single-source: `ExecutionLoop` defaults, `GraphPolicy` pin, Node client, verdict constants, constant triage | 3 (1 child spec) | medium | no |
| 3 | Unused exports deprecated, `vulture` gate, LATS/healing fate, Python skip accounting | 3 | medium | **yes**: park or wire LATS/healing; adopt `vulture` |
| 4 | Structure without reopening DEC-020: test size budget, `harness/node/src/ai/nemotron/nemotron-client.ts` split, docs consolidation, bootstrap dedup or DEC | 4 | medium (protected paths) | **yes**: whether DEC-020 is ever reopened |
| 5 | Coverage lands with each slice; control-plane tests colocated | 1 + per slice | low | no |

Fourteen PRs, down from twenty-two. Highest value per line changed: Phase 0a
(zero lines; it alone would have blocked the merge that broke `main`).

## Review record

What revision 1 claimed, what the reviewers found, and what revision 2 does.
Evidence is file:line or a command that was run.

| Rev-1 item | Reviewer finding | Evidence | Rev-2 disposition |
|---|---|---|---|
| `inputSchema` break attributed to upstream `mcp` drift | Wrong. `9d38670` reverted the DEC-023 rename; the field was `input_schema` in `2ffd228` | `git log -S input_schema -- harness/shared/mcp_server.py`; decision log DEC-023 | Problem statement corrected; the lock (R-TDH-9) no longer cites this incident |
| Regroup `harness/shared/` into four packages | Reverses DEC-020 without citing it; the split is cyclic (`tooling ↔ runtime`, `tooling → gates`); eight modules unassigned | decision log line 25; `harness/shared/tool_executors.py:239` → `debug_dump`, `harness/shared/agent_prompts.py:5` → `agent_authority`, `harness/shared/write_policy.py:37` → `validate_invariants` | Dropped. DEC-020 stands (R-TDH-20). Reopening needs a superseding DEC and an acyclicity test first |
| Delete the 20 per-stack shim scripts | They are root-of-trust artefacts: listed in `harness/node/.governance/policy.json:86-96`, digested in `harness/control-plane/policy-bundle.example.json:20-31`; DEC-004 sizes removal as a rotation; two `per-file-ignores` would go dead | as cited; `pyproject.toml:110-111`; `harness/shared/tests/test_lint_config_liveness.py:92-102` | Dropped (R-TDH-21 keeps them) |
| Six required checks | Nine; already derived from the workflow by `harness/shared/tests/test_ci_gate_coverage.py::TestRequiredStatusChecksListIsAccurate` | `NEXT_STEPS.md:258-261`; DEC-018 | R-TDH-1 cites the test, restates nothing |
| `requirements.lock` via `pip-compile` | One per-interpreter lock cannot serve 3.9/3.10/3.12 with markers (`mcp` ≥3.10, `tomli` <3.11); `pip-compile` not installed; `uv 0.8.17` is | `requirements*.txt` markers; `uv pip compile --help` → `--universal` | R-TDH-9 uses `uv pip compile --universal` |
| Install `.[langgraph]` in CI | The extra drags `langgraph-checkpoint-postgres` → `psycopg`, which nothing imports and `pip-audit` never scans | `pyproject.toml:15-18`; `Makefile:173` | R-TDH-4 splits the extra and installs `langgraph` alone; audit covers it |
| Healing test "reports SKIPPED" on 3.9 | Contradicts the plan's own zero-skip requirement | QA review of AC-2 vs R-TDH-18 | Langgraph tests carry the registered `langgraph` marker; the 3.9 leg deselects (`-m "not live and not langgraph"`), which is not a skip |
| `AgentLoop` defaults from `agent_defaults()` | Class is `ExecutionLoop`; accessor is `policy_loader.max_tool_calls_per_task()`; a dataclass-style default would read the filesystem at import | `harness/shared/orchestrator/loop.py:32`; `harness/shared/policy_loader.py:138,169-182`; `harness/shared/tests/test_import_purity.py` | R-TDH-12: `None` defaults resolved at call time |
| `GraphPolicy()` reads policy at construction | Contradicts landed `langgraph-policy-wiring` R-LPW-4/5 (pure fallback; `from_governance_json()` is the policy path) | `docs/specs/langgraph-policy-wiring.md:83-93`; `harness/shared/langgraph/graph.py:69`, `harness/shared/langgraph/nodes.py:225` | R-TDH-12 pins the eleven defaults equal to `policy_loader` fallbacks by an equality test |
| `"coverage": 85.0` is a fabricated gate input | It is inert: `quality_gate_node` reads only `failed` | `harness/shared/langgraph/nodes.py:195,244-247`; `harness/shared/tests/test_langgraph_nodes.py:168-190` | R-TDH-15 removes the stub; wiring coverage floors into the gate is a separate behavioural spec (open question 5) |
| `decision_id_pattern` duplicated fallback regex | Both scripts already read the policy first and fail closed; the literal is the adopter path `policy-single-source.md` R-POL-4 requires, lockstep-pinned by `harness/shared/tests/test_policy_consistency.py:22,260` | `harness/shared/check_projections.py:66-71`; `harness/shared/governance/verify_zero_skips.py:70-75` | Dropped: checked, not a finding |
| Four "verified-dead" symbols | Zero first-party callers is correct, but two are declared compat exports and `resolve_api_key` gates three live-detection test modules | `harness/shared/write_policy.py:95-97`; `harness/shared/nemotron_bridge.py:78-81`; `harness/shared/tests/test_mango_mas_live.py:9` | R-TDH-17 treats them as a deprecation, not deletion |
| Facade keeps only constructor and `execute_agent` | `harness/shared/autonomous_healing.py:121` calls `execute_loop`; `harness/shared/langgraph/nodes.py:185` calls `_harness_verdict` | as cited | Backward compatibility section corrected |
| Coverage 97.70 % lines | That is `coverage.json`'s blended total; the gate reports lines 98.30 % / branches 95.78 %; the "six lowest" list was blended too | `python harness/shared/coverage_gate.py` | Baseline restated from the gate |
| 41 skips = langgraph | 36 langgraph cases + 4 `empty parameter set` skips + 1 live-key skip | `pytest -rs` | R-TDH-19 fixes the four parametrizations; waivers shrink to live and POSIX-only |
| `CHANGELOG.md` under 40 000 bytes | Self-defeating: after the required moves it lands at ≈48 960 bytes | 121 664 − 82 760 + 10 056 | R-TDH-24 uses a per-section line cap |
| Ruff bump justified by "rule counts change" | Counts are lower-bounded, not asserted; the real reason is 7 new findings, two in protected `harness/shared/write_policy.py` | `python -m ruff check .` under 0.16.5; `harness/shared/tests/test_deferred_rigor.py:192-200` | R-TDH-10 rationale corrected |
| Python zero-skip gate needs `pytest-json-report` | `verify_zero_skips.py` already accepts `--junit-events` TSV | `harness/shared/governance/verify_zero_skips.py:143-178` | R-TDH-19 reuses it; a `harness/shared/tests/conftest.py` hook emits the TSV |
| `make pre-pr` tail on every PR | `pre-pr` needs gitleaks, pip-audit, osv-scanner; none in the agent toolchain | `Makefile:266`; `command -v` | C-TDH-3: `make ci` + `make lint-cold` locally; `audit`/`secrets` by CI job URL |
| "Reusable code" and "enterprise" phrases of the request | Under-served: only directory moves | Product review coverage table | R-TDH-1/2 (process controls), R-TDH-21 (bootstrap dedup or DEC), R-TDH-16 (triage table) |
| Missed entirely | All five Actions run on Node 20; no `github-actions` Dependabot ecosystem; nightly drift never runs `lint`, so the mypy break was invisible nightly; `harness/api_server/main.py:13-15` imports root modules; `test_orchestrator_hooks` POSIX skips | workflow `:109`; `.github/dependabot.yml`; `.github/workflows/scheduled-drift.yml:68`; `pytest -rs` | R-TDH-10, R-TDH-11, R-TDH-19 |

Verified correct and kept: the five local failures and their causes; the three
live policy divergences (`harness/shared/orchestrator/loop.py:45-47`, `harness/node/src/ai/nemotron/nemotron-client.ts:25`, five version
strings); the 32 langgraph regression cases skipped in CI; `harness/shared/remotes.py` at 46
lines (but *not* over any budget that applies to it); nine watch-list modules,
none over budget; 920-line `harness/shared/tests/test_ci_gate_coverage.py`; 24.7 k test lines vs
10.7 k source; PR #60 merged with runs 323–325 red and a commit message
claiming `make ci` and mypy clean.

## Problem statement

All numbers measured on `2555ca0`.

**1. `main` is red, and the merge that broke it was not stopped by anything.**
Run 326 fails `build (3.9/3.10/3.12)` and `build-full`; only `secret-scan` and
the four `dependency-audit` jobs pass. PR #60's own runs 323–325 all failed
before merge. Its merge commit `9d38670` claims "`make ci` … passed" and
"mypy … clean"; on the pushed code neither was true. `main` has no ruleset
(`.github/workflows/scheduled-drift.yml:51-53`, DEC-018, `NEXT_STEPS.md:253`: "the highest-value
item on this list"). The process failure is the root cause; the four code
defects below are its symptoms.

| Job | First failing step | Cause |
|---|---|---|
| `build (3.10)`, `build (3.12)` | mypy | `harness/shared/mcp_server.py:120` passes `inputSchema=`; `9d38670` reverted the `input_schema` rename that `2ffd228` landed under DEC-023 |
| `build (3.9)` | pytest (mypy passes: `mcp` is not installed on 3.9) | the four failures below |
| `build-full` | `make test-regression` | `test_state_graph_healing_loop_recovers_from_test_failure` needs `langgraph`; no CI job installs it |

**2. Full suite on the same head, locally (Python 3.11, `mcp` 2.1.1, no
`langgraph`):** 2,437 passed, 5 failed, 41 skipped. The coverage gate reports
lines 98.30 %, branches 95.78 %, 68 files at or above the 90 % per-file floor.
The five failures: the healing test above; `test_real_mcp_tool_accepts_the_kwargs_mcp_server_passes`
(reads `tool.inputSchema`); `test_orchestrator_guard_swallows_channel_bug`
(patches `mango_mas_orchestrator.run_shadow_comparison`, moved to
`harness/shared/orchestrator/loop.py` in `9d38670`); two `test_documentation_truth` failures
on `.gitignore`/`.dockerignore` rules naming `.mcp_storage/`, which no tracked
code creates.

**3. Policy values restated as literals, three already diverged.**
`harness/shared/orchestrator/loop.py:45-47` defaults `15/30/50` vs policy `10/300/100`
(masked: the facade passes explicit values); `harness/node/src/ai/nemotron/nemotron-client.ts:25`
`maxRetries: 3` vs `nemotron.max_retries: 0`; five version strings
(`pyproject` 2.2.5, `README` 2.3.0, `Makefile`/`CHANGELOG`/`NEXT_STEPS` 2.4.0,
`package.json` 2.0.0), a drift DEC-013 already fixed once. `policy-single-source.md`
AC-1 is unchecked and still failing.

**4. Skips are invisible on the Python side.** 36 langgraph cases skip on every
CI leg (`langgraph` never installed); four parametrizations over empty waiver
lists skip silently; INV-2 is enforced for Node only.

**5. Unused surface and document sprawl.** Four exports with no first-party
caller; `harness/shared/autonomous_healing.py` and `harness/shared/lats_optimizer.py` (v2.3.0 headline
features) reachable from no runtime path; `CHANGELOG.md` at 121 KB with a
1,315-line pasted v2.2.4 section; three point-in-time reports at the root and
under `harness/`; two RCA and two C4 documents for the same subjects.

**6. Size.** No production module exceeds `limits.size_budget_lines` (500);
nine are past 60 % (`harness/shared/plan_rules.py` 428 the largest). Tests are outside the
budget; `harness/shared/tests/test_ci_gate_coverage.py` is 920 lines and the largest Python file
in the repository.

**7. Toolchain.** Every GitHub Action in the workflow runs on Node 20 (deprecated
on the runners); `.github/dependabot.yml` covers `pip` and `npm` only; nightly drift
runs `digest-regen check-dedup validate coverage-python` but not `lint`.

### Team reflection

- **Architecture.** The package boundaries that exist (`governance/`,
  `orchestrator/`, `langgraph/`) are right and DEC-020's "convention for new
  code, not a migration" is the correct call for the flat root; revision 1 was
  wrong to reopen it. The real edge debt is the Node client ignoring the
  policy and four styles of `sys.path` bootstrap.
- **SDLC / CI.** The gates are well designed and advisory. A ruleset is the
  whole fix for the last incident; a lock, Node 24 actions and `lint` in the
  nightly loop are the fixes for the next ones.
- **QA.** Coverage is high and honest. The refactor that landed with a test
  still patching the old module path shows the suite was not run on the pushed
  code. Skip accounting and a test size budget are the missing controls.
- **Product.** Two features are unreachable, the version depends on which file
  is opened, and the request's "reusable" and "enterprise" asks are answered by
  process controls and decision hygiene, not by moving files.

## Requirements

Phase 0a — the control (0 code lines).

- R-TDH-1: `main` MUST carry a repository ruleset requiring the nine status
  checks `harness/shared/tests/test_ci_gate_coverage.py::TestRequiredStatusChecksListIsAccurate`
  derives from `.github/workflows/python-package.yml` (listed in
  `NEXT_STEPS.md`), plus review from `.github/CODEOWNERS` for protected paths;
  the ruleset is recorded as a `DEC-` entry. (`dependency-audit (3.9)` is
  `continue-on-error` per DEC-017, so requiring it is harmless.)
- R-TDH-2: `CLAUDE.md` and `CONTRIBUTING.md` MUST state that a PR body's
  verification claim is not evidence and the check runs are; the PR template's
  Validation section asks for the `make ci` and `make lint-cold` tails and the
  CI job URLs for `audit`/`secrets`.

Phase 0b — green `main` (1 PR).

- R-TDH-3: `harness/shared/mcp_server.py` and `harness/shared/tests/test_mcp_server.py` MUST use
  `input_schema` (the DEC-023 rename, reverted by `9d38670`); the `mcp>=2.0.0`
  floor is unchanged because the field and its `inputSchema` alias exist in
  2.0.0.
- R-TDH-4: Tests that import `langgraph` MUST carry the registered
  `langgraph` marker; the 3.9 leg MUST deselect them (a `conftest.py`
  collection hook keyed to `MANGO_CI_DESELECT_LANGGRAPH=1`, because a `-m`
  passed through `PYTEST_ADDOPTS` is overridden by the Make recipes' own
  `-m "not live"`); the 3.10, 3.12 and `build-full` jobs MUST receive the
  `langgraph` library, declared in `requirements-langgraph.txt` (mirrored by
  the `[project.optional-dependencies]` `langgraph` extra, split so it no
  longer pulls `langgraph-checkpoint-postgres`) and carried into
  `requirements-lock.txt` behind a `>= 3.10` marker once R-TDH-9 lands, and
  `audit-python` MUST scan that file; the existing `LANGGRAPH_AVAILABLE` skip
  guards stay for local runs without the library. DEC-023's note that `mcp` and `langgraph` move to
  extras together applies once this lands and is recorded, not acted on here.
- R-TDH-5: `test_orchestrator_guard_swallows_channel_bug` MUST patch
  `harness.shared.orchestrator.loop.run_shadow_comparison`.
- R-TDH-6: `.gitignore`, `.dockerignore` and `.mango/hooks/pre-nemotron-run.sh`
  MUST NOT reference `.mcp_storage/` while no tracked code creates it.
- R-TDH-7: `pyproject.toml` `[project].version` MUST be the single version
  source; `Makefile`, `README.md`, the top `CHANGELOG.md` entry,
  `harness/node/package.json`, `docs/architecture/c4_architecture.md` and
  `NEXT_STEPS.md` are compared to it by `harness/shared/tests/test_documentation_truth.py`, which
  fails on any mismatch (extends `ci-enforcement-gaps.md` R-CEG-1). The value
  is open question 1; no git tag exists to anchor it.

Phase 0c — spec reconciliation (1 PR).

- R-TDH-8: `dependency-hygiene.md`, `gate-hardening.md`,
  `ci-enforcement-gaps.md`, `policy-single-source.md` and `remove-pong-demo.md`
  MUST have each acceptance box re-verified against the tree and ticked or
  annotated with the blocking gap; boxes whose command fails today stay open
  and are cited by the requirement here that closes them
  (`policy-single-source.md` AC-1 → R-TDH-12).

Phase 1 — toolchain (3 PRs).

- R-TDH-9: CI MUST install Python dependencies from a committed
  marker-preserving lock, `requirements-lock.txt`, produced by
  `uv pip compile --universal` from `requirements-dev.txt` (which includes
  `requirements.txt`), with the workflow `cache-dependency-path` keys updated
  and a new unprotected `harness/shared/tests/test_workflow_contracts.py` failing when an install
  step bypasses the lock; Dependabot's pip fetcher MUST be confirmed to update
  the file, else a weekly refresh workflow opens the bump PR.
- R-TDH-10: Dependabot PRs #38–#46 MUST each be merged or closed after Phase 0b,
  tooling first and the ruff bump alone in its PR (it fires 7 findings on the
  tree, two in protected `harness/shared/write_policy.py`; the `measured` values in
  `harness/shared/tests/test_deferred_rigor.py` are refreshed in the same PR); `.github/dependabot.yml`
  MUST gain the `github-actions` ecosystem and the five actions MUST move to
  the majors that run on Node 24.
- R-TDH-11: The nightly `main-drift` job MUST run `lint` and install the
  `langgraph` library, so a mypy or dependency break on `main` opens an issue
  the same night.

Phase 2 — policy single source (3 PRs).

- R-TDH-12: `ExecutionLoop.__init__` in `harness/shared/orchestrator/loop.py`
  MUST default `max_iterations`, `api_timeout` and `max_tool_calls_per_task`
  to `None` and resolve them at call time from
  `policy_loader.orchestrator_defaults()` and
  `policy_loader.max_tool_calls_per_task()`; the eleven `GraphPolicy` field
  defaults MUST be pinned equal to `policy_loader`'s built-in fallbacks by an
  equality test in the `harness/shared/tests/test_policy_consistency.py` pattern (the pure
  no-config fallback decided by `langgraph-policy-wiring.md` R-LPW-4/5 is
  kept). Closes `policy-single-source.md` AC-1.
- R-TDH-13 (*child spec* `node-policy-wiring`):
  `harness/node/src/ai/nemotron/nemotron-client.ts` and `harness/node/src/ai/nemotron/cli.ts` MUST read
  `nemotron.timeout_ms`, `nemotron.max_retries`, `nemotron.temperature` and
  `nemotron.max_tokens` from `harness/shared/governance-policy.json` the way
  `harness/node/vitest.config.ts` does, throwing on a missing key, with a Vitest liveness
  test.
- R-TDH-14: Verdict status strings in `harness/shared/governance/broker.py`,
  `harness/shared/governance/verification.py`, `harness/shared/governance/process_backend.py`,
  `harness/shared/langgraph/nodes.py`, `harness/shared/tool_executors.py` and `harness/shared/tool_result_format.py` MUST
  reference `harness/shared/governance/verdict.py` constants; an AST-based test fails on a
  raw `"BLOCKED"`/`"FAILED"`/`"VERIFIED"` string literal outside that module,
  exempting `Literal[...]` annotations.
- R-TDH-15: `harness/shared/langgraph/nodes.py` MUST NOT emit the stub `"coverage": 85.0`;
  the key is omitted until a measured value exists. Applying
  `coverage_floor_lines/branches` inside the quality gate is a behavioural
  change to protected `harness/shared/langgraph/**` and is open question 5, not this plan.
- R-TDH-16: Each constant in the audit list (`process_backend.DEFAULT_MAX_OUTPUT_BYTES`,
  `shadow_planner.DEFAULT_SHADOW_TIMEOUT_SEC`, `cognitive_signal.MAX_SIGNAL_BYTES`,
  `cognitive_signal.MAX_SINK_BYTES`, `retry_policy` backoff values, the Node
  circuit-breaker and backoff defaults) MUST resolve through a policy key or
  be named in one `DEC-` entry, enforced by a table-driven test that reads
  the policy and `harness/node/.governance/decision-log.md`.

Phase 3 — unused code, unwired features, skip accounting (3 PRs).

- R-TDH-17: `write_policy.ALWAYS_DENIED_PREFIXES`,
  `nemotron_bridge.RETRY_BACKOFF_BASE_SEC` and `ToolBudget.remaining` MUST be
  deprecated (a `DeprecationWarning` shim for one minor release).
  `nemotron_bridge.resolve_api_key`, listed in revision 2, is kept: the
  suite's `api_key` fixture and the live-detection guards call it, so by the
  tech-debt-audit skill's own rule (definition plus call sites) it is used,
  and migrating three test modules to `resolve_environment()["api_key"]`
  would buy no behaviour. The dead `RunnableConfig` fallback import in
  `harness/shared/langgraph/nodes.py` is removed, and `vulture` pinned in
  `requirements-dev.txt` and run by `make lint` as
  `python -m vulture harness/shared harness/api_server harness/control-plane vulture_whitelist.py --min-confidence 80 --exclude '*/tests/*'`.
- R-TDH-18: `harness/shared/autonomous_healing.py` and `harness/shared/lats_optimizer.py` MUST be either
  wired into a runtime path behind `synthesis.lats_enabled` and the existing
  `orchestrator.max_healing_retries` under their own spec (INV-15 governs), or
  moved to `harness/shared/experimental/` with `harness/README.md` updated;
  the test-only facade pass-throughs (`_tool_handlers`, `_run_hook`,
  `_dispatch_tool_calls`) get their tests retargeted to the facade's
  `dispatcher` and `hook_runner` and are deleted.
  `execute_sequential_thinking_loop`, listed in revision 2, stays: it is part
  of the public surface `orchestrator-tool-registry.md` R-ORCH-4 pins and
  `verdict-propagation.md` R-VP-11 requires its prose return.
- R-TDH-19: Python skips MUST be accounted for (INV-2 parity): the four
  empty-parametrize skips (`harness/shared/tests/test_ci_gate_coverage.py:526`,
  `harness/shared/tests/test_import_purity.py:174,185`, `harness/shared/tests/test_test_quality.py:120`) are fixed; a
  `harness/shared/tests/conftest.py` `pytest_runtest_logreport` hook writes
  `.governance/pytest-skips.tsv`; `make verify-zero-skips-python` calls the
  existing `verify_zero_skips.py --junit-events` with waivers for the live-key
  skip, the POSIX-only skips in `harness/shared/tests/test_orchestrator_hooks.py`/`harness/shared/tests/conftest.py`
  and the `mcp`-absent skip; the target is added to both `ci` and `ci-python`.

Phase 4 — structure without reopening DEC-020 (4 PRs).

- R-TDH-20: DEC-020 MUST stand: no regrouping of `harness/shared/`; new
  gate-like modules land under `harness/shared/gates/`; any future move
  requires a superseding `DEC-` entry and an import-acyclicity test landed
  first.
- R-TDH-21: The per-stack shim scripts MUST be retained (root-of-trust
  artefacts); the four `sys.path` bootstrap styles (root try/except import,
  unconditional `parents[2]`, stack `runpy`, stack walk-up) MUST collapse to
  one helper per style family or be accepted in one `DEC-` entry in the manner
  of DEC-019, with `harness/control-plane/` excluded (DEC-019).
- R-TDH-22: Test modules MUST be subject to `limits.test_size_budget_lines`
  via a new `validate_invariants.check_test_size_budget`;
  `harness/shared/tests/test_ci_gate_coverage.py` is split by concern first, its exact
  `protected_paths` entry becomes a glob, and `harness/shared/tests/test_protected_path_liveness.py`
  is updated in the same PR.
- R-TDH-23: The watch-list modules MUST stay under `limits.size_budget_lines`,
  and `harness/node/src/ai/nemotron/nemotron-client.ts` (454 lines) MUST have retry/backoff extracted with
  an ESLint `max-lines` rule at `error` sourced from the same policy key.
- R-TDH-24: Documentation MUST be consolidated: the v2.2.4 body moves from
  `CHANGELOG.md` to `docs/releases/v2.2.4.md`; `SDLC_HYGIENE_REPORT.md`,
  `harness/PEER-REVIEW-REMEDIATION.md`, `harness/TEST-REPORT.md` move to
  `docs/reports/`; `harness/CHANGELOG.md` folds into the root; the two RCA and
  two C4 documents each merge; `harness/shared/tests/test_documentation_truth.py` caps any
  `## [x.y.z]` section at `limits.changelog_section_lines`. `NEXT_STEPS.md`
  stays where `harness/shared/tests/test_ci_gate_coverage.py` reads it.

Phase 5 — coverage that measures what ships.

- R-TDH-25: Every Phase 2/3 slice MUST bring branch tests for the missing arcs
  in the files it touches; the baseline is the gate's own report (lines
  98.30 %, branches 95.78 %) and the lowest files by lines are
  `harness/shared/check_dedup.py` 92.7 %, `harness/shared/mango_mas_orchestrator.py` 93.8 %,
  `harness/shared/orchestrator/hook_runner.py` 93.9 %, `harness/shared/check_py_compat.py` 94.4 %,
  `harness/shared/coverage_gate.py` 94.9 %, `harness/shared/governance/verify_zero_skips.py` 95.9 %; with
  `langgraph` installed (R-TDH-4) the `langgraph/` package is measured on its
  happy path for the first time.
- R-TDH-26: `harness/control-plane/` MUST have colocated tests under
  `harness/control-plane/tests/`, added to `pyproject.toml` `testpaths` and to
  the `test-python`/`coverage-python` Make recipes, with a meta-test mapping
  each script to a test module.

Constraints.

- C-TDH-1: No slice MUST weaken an invariant in `harness/CONTRACT.md`, add an
  `xfail`, or add a skip without a decision-log entry.
- C-TDH-2: Every deprecated or moved public symbol MUST keep a shim emitting
  `DeprecationWarning` for one minor release; removals no earlier than the
  minor after the one chosen in open question 1.
- C-TDH-3: Every slice MUST be its own PR with the `make ci` and
  `make lint-cold` tails in the Validation section and the `audit`/`secrets`
  job URLs; a slice touching `protected_paths` MUST carry the attestation
  table and the `infra-reviewed` label.

## Acceptance criteria

- [ ] AC-1: the ruleset export committed as `.github/rulesets/main.json` lists
      exactly the check names `pytest harness/shared/tests/test_ci_gate_coverage.py -k TestRequiredStatusChecksListIsAccurate`
      derives, asserted by a new test in `harness/shared/tests/test_workflow_contracts.py` that
      fails on any difference · stage: `make test-python` (R-TDH-1)
- [ ] AC-2: `git grep -n "verification claim" CLAUDE.md CONTRIBUTING.md .github/PULL_REQUEST_TEMPLATE.md`
      matches in all three files, and `make validate` fails on the `CLAUDE.md`
      edit without `ALLOW_GITHUB_CHANGES=1` · stage: `make validate` (R-TDH-2)
- [ ] AC-3: `python -m mypy harness/shared harness/api_server harness/control-plane --explicit-package-bases --check-untyped-defs`
      exits 0 with `mcp` 2.1.1 installed and
      `pytest harness/shared/tests/test_mcp_server.py -k test_real_mcp_tool_accepts_the_kwargs_mcp_server_passes`
      passes · stage: `make lint` (R-TDH-3)
- [ ] AC-4: `MANGO_CI_DESELECT_LANGGRAPH=1 pytest harness/shared/tests --co -q`
      on an interpreter without `langgraph` reports the `langgraph`-marked
      tests as deselected and zero of them as skipped; with `langgraph`
      installed `pytest -k test_state_graph_healing_loop_recovers_from_test_failure`
      passes rather than skipping; `pytest harness/shared/tests/test_workflow_contracts.py`
      fails if `requirements-lock.txt` lacks `langgraph` behind a `>= 3.10`
      marker, carries the Postgres checkpointer, or the 3.9 leg lacks the
      deselect variable · stage: `make test-regression` (R-TDH-4)
- [ ] AC-5: `pytest harness/shared/tests/test_shadow_planner.py -k test_orchestrator_guard_swallows_channel_bug`
      passes · stage: `make test-python` (R-TDH-5)
- [ ] AC-6: `pytest harness/shared/tests/test_documentation_truth.py` passes
      and `git grep -n mcp_storage -- .gitignore .dockerignore .mango/hooks`
      returns nothing · stage: `make test-python` (R-TDH-6)
- [ ] AC-7: `pytest harness/shared/tests/test_documentation_truth.py -k version`
      passes on the reconciled tree and fails on a `tmp_path` copy with one
      mutated version string (a parametrised negative case) · stage: `make test-python` (R-TDH-7, extends R-CEG-1)
- [ ] AC-8: `make specs` passes with the five reconciled specs modified, and
      each acceptance box in them is either `[x]` with its command passing
      today or `[ ]` with a `(blocked by R-TDH-n)` note; a box that is `[x]`
      while its command fails is a `make specs` plan-tier failure added for
      this purpose · stage: `make specs` (R-TDH-8)
- [ ] AC-9: `make lock-check` exits 0 on the committed lock and exits 1 after
      a requirement is edited without `make lock`; every `python -m pip install -r`
      line in both workflows names `requirements-lock.txt` and every `-e .`
      carries `--no-deps` (`pytest harness/shared/tests/test_workflow_contracts.py -k Lock`
      fails otherwise) · stage: `make ci` (R-TDH-9)
- [ ] AC-10: PRs #38–#46 are each merged or closed (recorded in the `DEC-`
      entry); `make lint` exits 0 with the bumped `ruff` pin;
      `pytest harness/shared/tests/test_workflow_contracts.py -k node24`
      fails on any `uses:` action major that declares `runs.using: node20`;
      `.github/dependabot.yml` lists `github-actions` · stage: `make lint` (R-TDH-10)
- [ ] AC-11: `pytest harness/shared/tests/test_workflow_contracts.py -k drift`
      fails if `.github/workflows/scheduled-drift.yml`'s `main-drift` loop omits `lint`
      · stage: `make test-python` (R-TDH-11)
- [ ] AC-12: `pytest harness/shared/tests -k "ExecutionLoop and defaults"`
      constructs `ExecutionLoop` with no budget arguments against a
      `tmp_path` policy carrying distinguishable values (via
      `policy_path=`) and asserts they are used;
      `pytest harness/shared/tests/test_policy_consistency.py -k GraphPolicy`
      fails when any `GraphPolicy` default differs from the `policy_loader`
      fallback; `policy-single-source.md` AC-1's grep returns nothing
      · stage: `make test-python` (R-TDH-12, preserves R-LPW-4)
- [ ] AC-13: `pnpm exec vitest run tests/ai` includes a test that rewrites
      `nemotron.max_retries` in a temp policy copy and asserts
      `DEFAULT_NEMOTRON_CONFIG.maxRetries` follows it, and that module load
      throws when the key is absent; `git grep -n "maxRetries: 3" harness/node/src`
      returns nothing · stage: `make test-node` (R-TDH-13)
- [ ] AC-14: `pytest harness/shared/tests -k verdict_literals` fails on a raw
      verdict string literal outside `harness/shared/governance/verdict.py` (negative case via
      a `tmp_path` module) and passes on the migrated tree
      · stage: `make test-python` (R-TDH-14)
- [ ] AC-15: `git grep -n '"coverage": 85.0' harness/shared/langgraph` returns
      nothing and `pytest harness/shared/tests/test_langgraph_nodes.py`
      passes · stage: `make test-langgraph` (R-TDH-15)
- [ ] AC-16: `pytest harness/shared/tests -k constant_triage` fails for any
      listed constant with neither a resolving policy key nor a `DEC-` id in
      `harness/node/.governance/decision-log.md`, and passes on the tree
      · stage: `make test-python` (R-TDH-16)
- [ ] AC-17: `make lint` runs `vulture` and exits 0;
      `python -W error::DeprecationWarning -c "from harness.shared.write_policy import ALWAYS_DENIED_PREFIXES"`
      exits non-zero; `pytest harness/shared/tests -k deprecation_shims`
      asserts each of the four shims warns · stage: `make lint` (R-TDH-17)
- [ ] AC-18: `git grep -ln "autonomous_healing\|lats_optimizer" -- harness ':!*/tests/*'`
      lists only files under `harness/shared/experimental/` (park) or a
      runtime caller gated on `synthesis.lats_enabled` (wire), per open
      question 3; `pytest harness/shared/tests -k orchestrator` passes with
      the three test-only facade pass-throughs deleted and
      `execute_sequential_thinking_loop` still present
      · stage: `make test-python` (R-TDH-18; preserves R-ORCH-4, R-VP-11)
- [ ] AC-19: `make verify-zero-skips-python` exits 1 on a suite containing an
      unwaived `pytest.skip` (fixture) and exits 0 on the tree;
      `pytest harness/shared/tests -rs -q | grep -c "empty parameter set"`
      prints 0; `pytest harness/shared/tests/test_makefile_contracts.py -k ci_and_ci_python`
      passes · stage: `make ci` (R-TDH-19)
- [ ] AC-20: `git grep -n "DEC-020" docs/specs/tech-debt-hardening-plan.md harness/node/.governance/decision-log.md`
      matches, `ls harness/shared/{core,tooling,runtime}` reports no such
      directory, and `make check-dedup` passes · stage: `make check-dedup` (R-TDH-20)
- [ ] AC-21: `ls harness/node/scripts/*.py harness/jvm/scripts/*.py | wc -l`
      prints 20, and either `git grep -c "sys.path.insert" -- harness/shared harness/node/scripts harness/jvm/scripts`
      reports at most two distinct implementation sites or the decision log
      carries the accepting `DEC-` entry · stage: `make check-dedup` (R-TDH-21)
- [ ] AC-22: `python harness/shared/validate_invariants.py` fails on a
      `tmp_path` tree with a test file one line over
      `limits.test_size_budget_lines` (`pytest harness/shared/tests/test_validate_invariants.py -k test_size_budget`)
      and passes on the split tree; `pytest harness/shared/tests/test_protected_path_liveness.py`
      passes · stage: `make validate` (R-TDH-22)
- [ ] AC-23: `python harness/shared/validate_invariants.py` passes with every
      watch-list module under `limits.size_budget_lines`;
      `pnpm exec eslint . --max-warnings=0` fails on a source file over the
      policy-sourced `max-lines` value · stage: `make lint-node` (R-TDH-23)
- [ ] AC-24: `pytest harness/shared/tests/test_documentation_truth.py -k changelog_section`
      fails on a `## [x.y.z]` section longer than `limits.changelog_section_lines`
      and passes on the tree; `ls SDLC_HYGIENE_REPORT.md harness/PEER-REVIEW-REMEDIATION.md harness/TEST-REPORT.md harness/CHANGELOG.md`
      reports no such file; `ls docs/releases/v2.2.4.md` succeeds
      · stage: `make test-python` (R-TDH-24)
- [ ] AC-25: `python harness/shared/coverage_gate.py` passes on every slice
      and still exits 1 on a malformed `coverage.json`; each Phase 2/3 PR's
      Validation section shows the per-file line for every file it touched at
      or above its baseline value · stage: `make coverage-python` (R-TDH-25)
- [ ] AC-26: `pytest harness/control-plane/tests` collects at least one test
      per `harness/control-plane/*.py` (asserted by a meta-test), and
      `make test-python` exits 1 if that directory is dropped from the recipe
      (`harness/shared/tests/test_makefile_contracts.py`) · stage: `make test-python` (R-TDH-26)
- [ ] AC-27: `git diff 2555ca0..HEAD -G'pytest\.(skip|importorskip|mark\.(skipif|xfail))' --name-only -- 'harness/*/tests'`
      is empty on every slice except R-TDH-19's, whose additions are waived;
      `make validate` passes · stage: `make validate` (C-TDH-1)
- [ ] AC-28: `pytest -W error::DeprecationWarning harness/shared/tests harness/api_server/tests -k "not deprecation_shims"`
      passes (first-party code does not import through a shim), with shim
      tests importing inside the test body · stage: `make test-python` (C-TDH-2)
- [ ] AC-29: `make validate` exits 1 on a protected-path slice without
      `ALLOW_GITHUB_CHANGES=1`, and the PR template's Validation checklist
      names `make ci`, `make lint-cold` and the two job URLs
      · stage: `make validate` (C-TDH-3)

## Steps

Ordered by dependency; one PR per numbered step unless stated.

### Phase 0a (0 code)

1. Apply the ruleset from the nine names (admin); commit its export; add the
   `DEC-` entry to `harness/node/.governance/decision-log.md` and
   `harness/node/agents/GOVERNANCE_SKILL.md`; add the "claims are not evidence" rule to
   `CLAUDE.md`, `CONTRIBUTING.md` and the PR template (R-TDH-1, R-TDH-2).
   Protected: `CLAUDE.md`, `**/.governance/**`, `harness/*/agents/**`.

### Phase 0b (1 PR, ≈80 lines)

2. `input_schema` rename; `langgraph` marker on the healing test and the
   `LANGGRAPH_AVAILABLE`-guarded suites; split the extra; install `langgraph`
   on 3.10/3.12/`build-full` and set the 3.9 `PYTEST_ADDOPTS`; extend
   `audit-python`; retarget the shadow-planner patch; remove `.mcp_storage`
   rules and the hook warning; reconcile the version strings and extend the
   documentation-truth test (R-TDH-3 … R-TDH-7). Protected:
   `.github/workflows/**`, `pyproject.toml`, `Makefile`, `.mango/hooks/**`.

### Phase 0c (1 PR)

3. Re-verify and tick the five landed specs; note blocked boxes (R-TDH-8).

### Phase 1 (3 PRs)

4. `uv pip compile --universal` lock; workflow install and cache keys;
   `harness/shared/tests/test_workflow_contracts.py` (R-TDH-9). Protected: workflows.
5. Dependabot queue in order; ruff bump alone; `github-actions` ecosystem;
   Node 24 action majors (R-TDH-10). Protected: `requirements-dev.txt`,
   `harness/shared/write_policy.py`, workflows.
6. `lint` and `langgraph` into `main-drift` (R-TDH-11). Protected: workflow.

### Phase 2 (3 PRs)

7. `ExecutionLoop` call-time defaults; `GraphPolicy` equality pin
   (R-TDH-12). Protected: `harness/shared/langgraph/**`, `harness/shared/policy_loader.py`.
8. `make spec NAME=node-policy-wiring`, then the Node client (R-TDH-13).
9. Verdict constants and AST test; remove the coverage stub; constant triage
   table test with keys or one `DEC-` entry (R-TDH-14 … R-TDH-16).
   Protected: `harness/shared/governance/**`, `harness/shared/governance-policy.json`.

### Phase 3 (3 PRs)

10. Deprecation shims, `RunnableConfig` removal, `vulture` in `make lint`
    (R-TDH-17). Protected: `harness/shared/write_policy.py`, `Makefile`,
    `requirements-dev.txt`.
11. LATS/healing per open question 3; retarget facade tests; delete
    pass-throughs (R-TDH-18). Protected: `harness/shared/mango_mas_orchestrator.py`.
12. Empty-parametrize fixes; skip TSV hook; `verify-zero-skips-python` in
    `ci` and `ci-python`; waivers (R-TDH-19). Protected: `Makefile`,
    `harness/shared/tests/test_ci_gate_coverage.py`.

### Phase 4 (4 PRs)

13. Record R-TDH-20 in the decision log; bootstrap helper or accepting `DEC-`
    (R-TDH-20, R-TDH-21).
14. Split `harness/shared/tests/test_ci_gate_coverage.py`; `check_test_size_budget` and key; glob
    the protected entry (R-TDH-22). Protected: `harness/shared/validate_invariants.py`,
    `harness/shared/governance-policy.json`, `harness/shared/tests/test_ci_gate_coverage.py`.
15. `harness/node/src/ai/nemotron/nemotron-client.ts` split and ESLint `max-lines` (R-TDH-23).
16. Documentation consolidation and the section-cap test (R-TDH-24).

### Phase 5

17. Arc tests ride each Phase 2/3 slice (R-TDH-25); one PR for control-plane
    tests, `testpaths` and the Make recipes (R-TDH-26). Protected:
    `pyproject.toml`, `Makefile`.

## Files touched

Protected paths are marked (P); every (P) slice needs the attestation table
and the `infra-reviewed` label.

- Phase 0a: `.github/rulesets/main.json` (new), `CLAUDE.md` (P),
  `CONTRIBUTING.md`, `.github/PULL_REQUEST_TEMPLATE.md`,
  `harness/node/.governance/decision-log.md` (P),
  `harness/node/agents/GOVERNANCE_SKILL.md` (P).
- Phase 0b: `harness/shared/mcp_server.py`, `harness/shared/tests/test_mcp_server.py`,
  `harness/shared/tests/regression/test_e2e_nemotron_triage_regression.py`,
  `harness/shared/tests/test_langgraph_*.py`, `harness/shared/tests/test_shadow_planner.py`,
  `.github/workflows/python-package.yml` (P), `pyproject.toml` (P),
  `Makefile` (P), `.gitignore`, `.dockerignore`,
  `.mango/hooks/pre-nemotron-run.sh` (P), `README.md`, `CHANGELOG.md`,
  `harness/node/package.json`, `docs/architecture/c4_architecture.md`,
  `NEXT_STEPS.md`, `harness/shared/tests/test_documentation_truth.py`.
- Phase 0c: `docs/specs/{dependency-hygiene,gate-hardening,ci-enforcement-gaps,policy-single-source,remove-pong-demo}.md`.
- Phase 1: `requirements-lock.txt` (new), `.github/workflows/*.yml` (P),
  `.github/dependabot.yml`, `requirements-dev.txt` (P),
  `harness/shared/tests/test_workflow_contracts.py` (new),
  `harness/shared/tests/test_deferred_rigor.py`, `harness/shared/write_policy.py` (P).
- Phase 2: `harness/shared/orchestrator/loop.py`, `harness/shared/policy_loader.py` (P),
  `harness/shared/langgraph/{policy,nodes}.py` (P),
  `harness/shared/tests/test_policy_consistency.py`,
  `harness/node/src/ai/nemotron/{nemotron-client,cli}.ts`, `harness/node/tests/**`,
  `harness/shared/governance/{broker,verification,process_backend}.py` (P),
  `harness/shared/tool_executors.py`, `harness/shared/tool_result_format.py`,
  `harness/shared/governance-policy.json` (P), `harness/node/.governance/decision-log.md` (P).
- Phase 3: `harness/shared/write_policy.py` (P), `harness/shared/nemotron_bridge.py`,
  `harness/shared/tool_budget.py`, `harness/shared/langgraph/nodes.py` (P),
  `vulture_whitelist.py` (new), `Makefile` (P), `requirements-dev.txt` (P),
  `harness/shared/autonomous_healing.py`, `harness/shared/lats_optimizer.py`,
  `harness/shared/mango_mas_orchestrator.py` (P), `harness/README.md`,
  `harness/shared/tests/conftest.py`, `harness/shared/tests/test_ci_gate_coverage.py` (P),
  `harness/shared/tests/test_import_purity.py`, `harness/shared/tests/test_test_quality.py`,
  `.governance/skip-waivers.json` (new, root; see open question 6).
- Phase 4: `harness/node/.governance/decision-log.md` (P),
  `harness/shared/_bootstrap.py` (new, if chosen), root gate scripts (P),
  `harness/shared/validate_invariants.py` (P), `harness/shared/governance-policy.json` (P),
  `harness/shared/tests/test_ci_gate_coverage*.py` (P),
  `harness/shared/tests/test_validate_invariants.py`,
  `harness/shared/tests/test_protected_path_liveness.py` (P),
  `harness/node/src/ai/nemotron/*.ts`, `harness/node/eslint.config.*`,
  `CHANGELOG.md`, `harness/CHANGELOG.md`, `docs/releases/` (new), `docs/reports/` (new),
  `docs/rca/*`, `docs/architecture/*`, `harness/docs/*`.
- Phase 5: `harness/shared/tests/**`, `harness/control-plane/tests/` (new),
  `pyproject.toml` (P), `Makefile` (P).

## Invariants touched

- INV-2: extended to Python by R-TDH-19; the Node half unchanged.
- INV-5: R-TDH-1 turns the required-gate list into a merge requirement;
  R-TDH-9 and R-TDH-11 add workflow-shape tests.
- INV-8, INV-9, INV-10: unchanged; R-TDH-14 is a representation change pinned
  by the existing broker and verdict suites.
- INV-15: R-TDH-18 keeps `lats_enabled: false` as the only switch reaching the
  optimizer.
- INV-16: no cognitive-signal path is touched; `pytest -m governance` runs on
  every slice.
- INV-17: this document and the reconciled specs are gated by `make specs`.

## Validation matrix

- `make ci` on every slice: ruff + mypy + pytest + coverage floors from
  `governance-policy.json → coverage.{lines,branches,per_file}` + specs +
  check-dedup + validate_invariants (R-TDH-3 … R-TDH-26, C-TDH-1).
- `make lint-cold` on every slice; `audit`/`secrets` by their CI job URLs
  (C-TDH-3, R-TDH-2).
- `make test-regression` with and without `langgraph` installed (R-TDH-4,
  R-TDH-25).
- `make test-node` and `make lint-node` for R-TDH-13 and R-TDH-23.
- `make validate` with and without `ALLOW_GITHUB_CHANGES=1` on every
  protected-path slice (C-TDH-3, R-TDH-1).
- `pytest -W error::DeprecationWarning` on the shim slices (C-TDH-2,
  R-TDH-17, R-TDH-18).
- `make specs` on this document and on the reconciled specs (R-TDH-8,
  R-TDH-20).
- Coverage: floors from policy (lines 90, branches 80, per-file); baseline
  from the gate on `2555ca0` is lines 98.30 %, branches 95.78 %.

## Backward compatibility

Every import path on `2555ca0` resolves for one minor release after its
deprecation: the four exports in R-TDH-17 warn and still work; the
`MangoMASOrchestrator` facade keeps its constructor, `execute_agent`,
`execute_loop` (used by `harness/shared/autonomous_healing.py:121`) and `_harness_verdict`
(used by `harness/shared/langgraph/nodes.py:185`), and only the four test-only pass-throughs
go after their tests are retargeted. No module moves (R-TDH-20). `ExecutionLoop`
callers passing explicit budgets are unaffected; only the no-argument path
changes, from three literals to the policy values. `GraphPolicy()` keeps its
built-in defaults; they are pinned, not re-sourced. The Node client keeps
`DEFAULT_NEMOTRON_CONFIG` as its export with values from the policy file.
`requirements.txt`/`requirements-dev.txt` remain the human-edited inputs; the
lock is derived. The version reconciliation changes strings only. Removal of
shims is recorded in the decision log when each lands.

## Open questions

1. **Version number.** No git tag exists. `CHANGELOG.md` and `Makefile` already
   claim 2.4.0; `pyproject.toml` says 2.2.5. Adopt 2.4.0 everywhere now and
   start 2.5.0 with Phase 1, or renumber? Blocks step 2's last item only.
2. **Adopt `uv`** as the lock tool (it is on the runners and in this
   environment; `pip-tools` is in neither). Blocks step 4.
3. **LATS and healing:** park under `experimental/` (recommended: zero runtime
   callers, `lats_enabled` has no reader, INV-15 wants an ablation gate first)
   or wire behind policy under a new spec. Blocks step 11.
4. **DEC-020:** this plan keeps it. If the owner wants the regroup, it needs a
   superseding entry answering DEC-020's three reasons and an acyclicity test
   landed first; the reviewers' import-graph evidence says the revision-1 split
   would not have compiled as a layering.
5. **Quality-gate coverage floors** (`coverage_floor_lines/branches` are
   declared in `GraphPolicy` and applied nowhere): own spec, behavioural change
   to protected node code, same reasoning as DEC-022's decorator deferral.
6. **Root `.governance/`:** R-TDH-19's waiver file wants a root
   `skip-waivers.json`, but DEC-005 keeps `.governance/**` dormant at the root.
   Either the waivers live under `harness/shared/tests/` (recommended) or a
   `DEC-` entry revisits DEC-005 for this one file.
7. **`harness/jvm/`:** stays as an adopter template per CONTRACT.md; nothing
   here removes it. Raised because R-TDH-21 keeps its scripts.
8. **Mutation testing** on `governance/` (`mutmut`) as a Phase 5 stretch: no
   CI budget allocated; not blocking.
