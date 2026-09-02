# Spec: Tech-Debt Reduction & Hardening Plan (v2.4.0 → v2.5.0)

> Status: PROPOSED · Date: 2026-09-02 · Base: `main` @ `2555ca0` (merge of PR #60)
>
> This is the self-reflection the team asked for before the next feature
> sprint. It is written as a spec so `make specs` (structural + plan tiers,
> INV-17) can hold it to the same bar as any other plan: every requirement
> below is cited by an acceptance criterion that names the command proving it.
> Each phase below is a separate PR slice; the larger slices (Phase 2 Node
> client, Phase 4 regrouping) get their own child spec via `make spec` before
> implementation, per CLAUDE.md.

## Problem statement

The harness has strong gates and weak enforcement of them. Every number below
was measured on `2555ca0`, not recalled.

**1. CI on `main` is red, and the PR that broke it merged red.** Run 326
(`push` to `main`, 2026-09-02 11:59 UTC) fails on all three `build` legs and on
`build-full`; only `secret-scan` and the `dependency-audit` jobs pass. The
three CI runs for PR #60's head (`1292376`, runs 323-325) all failed before
the merge, and the merge commit `9d38670` claims "`make ci` … passed over 2300+
assertions" and "`mypy --check-untyped-defs harness/` clean". Neither was true
on the code as pushed. Nothing stopped the merge: `main` has no ruleset
requiring the checks, a gap `scheduled-drift.yml` already documents in its own
comments.

| CI job (run 326) | Result | First failing step / cause |
|---|---|---|
| `build (3.9)`, `build (3.10)`, `build (3.12)` | fail | `make ci-python` → mypy: `mcp_server.py:120` passes `inputSchema=` to `types.Tool`; the field is `input_schema` in every `mcp>=2.0.0` (alias accepted at runtime, rejected by mypy) |
| `build-full` | fail | `make test-regression` → `test_state_graph_healing_loop_recovers_from_test_failure` raises `RuntimeError: langgraph library is required`; no CI job installs the `langgraph` extra |
| `secret-scan`, `dependency-audit` (×4) | pass | — |

**2. The full suite on the same head, run locally with the pinned toolchain
(Python 3.11, `mcp` 2.1.1, `langgraph` absent):** 2,437 passed, **5 failed**,
41 skipped; coverage 97.70 % lines / 95.78 % branches over 70 files. The three
failures CI has not yet reached (its pytest step dies at mypy first) are:

| Failing test | Cause | Introduced |
|---|---|---|
| `test_mcp_server.py::test_real_mcp_tool_accepts_the_kwargs_mcp_server_passes` | reads `tool.inputSchema`; attribute is `input_schema` | dependency drift inside `mcp>=2.0.0,<3.0` |
| `test_shadow_planner.py::TestContainment::test_orchestrator_guard_swallows_channel_bug` | patches `mango_mas_orchestrator.run_shadow_comparison`; the symbol moved to `orchestrator/loop.py` | `9d38670` (decomposition) |
| `test_documentation_truth.py` ×2 (`.gitignore`, `.dockerignore`) | both name `.mcp_storage/`, which no tracked code creates | `9d38670` |

**3. Policy values are restated as literals, and some have already diverged.**
`governance-policy.json` is the declared single source; 58 literal sites were
catalogued (see Phase 2). The live divergences: `orchestrator/loop.py:45-47`
defaults `15 / 30 / 50` against policy `10 / 300 / 100` (masked only because the
facade always passes explicit values); `nemotron-client.ts:25` `maxRetries: 3`
against policy `nemotron.max_retries: 0`; `langgraph/nodes.py:195` reports a
fabricated `"coverage": 85.0` from the quality gate; five different version
strings (`pyproject` 2.2.5, `README` 2.3.0, `Makefile`/`CHANGELOG` 2.4.0,
`package.json` 2.0.0).

**4. A whole subsystem is unmeasured in CI.** 18 distinct langgraph tests (32
parametrised cases in the regression tier alone) skip on every CI leg because
the extra is never installed. Node has a zero-skip gate (INV-2); Python has
none, so these skips are invisible.

**5. Shipped-but-unwired code and document sprawl.** `autonomous_healing.py`
and `lats_optimizer.py` (v2.3.0 headline features) have zero non-test callers.
`CHANGELOG.md` is 120 KB, 1,315 lines of it one pasted v2.2.4 report; three
point-in-time reports sit at the repo root and under `harness/`; two RCA docs
and two C4 docs describe the same things.

**6. God files.** No production module exceeds the 500-line budget
(`limits.size_budget_lines`); nine are past the 60 % watch threshold
(`plan_rules.py` 428 is the largest). The largest Python file in the
repository is a test, `test_ci_gate_coverage.py` at 920 lines, and tests are
outside the budget. Test code is 24.7 k lines against 10.7 k of source.

### Team reflection (one paragraph per perspective)

- **Architecture.** The orchestrator decomposition and the `governance/`,
  `orchestrator/`, `langgraph/` packages are the right shape. The debt is at
  the edges: a 40-module flat root in `harness/shared/`, four generations of
  the same `sys.path` bootstrap snippet, and a Node client that never reads
  the policy the rest of the repo treats as law.
- **SDLC / CI.** Gate design is better than most enterprise repos (fail-closed,
  policy-driven thresholds, liveness tests on the config itself). The gate is
  advisory because no ruleset requires it, and the last merge proves an
  advisory gate is no gate. Dependency ranges without a lock let an upstream
  minor release turn `main` red with no change in this repository.
- **QA.** Coverage is high and mostly honest, but a refactor landed with a
  test still patching the old module path, which means the suite was not run
  on the pushed code. Python skips are unaccounted for. Meta-tests are a large
  fraction of the suite; that is a deliberate design, but the biggest of them
  needs splitting.
- **Product.** Two headline features are not reachable from any runtime path,
  the version number depends on which file you open, and the changelog is
  unreadable at its current size. Release claims are only as credible as the
  smallest of these.

## Requirements

Phase 0 — restore a green `main` (blocking; land first, one PR).

- R-TDH-1: `harness/shared/mcp_server.py` MUST construct `types.Tool` with
  `input_schema=`, and `test_mcp_server.py` MUST read `tool.input_schema`; the
  `mcp>=2.0.0` floor is kept because the field and its `inputSchema` alias
  exist in 2.0.0.
- R-TDH-2: `test_state_graph_healing_loop_recovers_from_test_failure` MUST
  carry the same `LANGGRAPH_AVAILABLE` skip guard as its siblings in
  `test_langgraph_regression.py`, AND the `build-full`, `build (3.10)` and
  `build (3.12)` jobs MUST install the `langgraph` extra so the guarded tests
  run in CI (langgraph 1.0.10 declares `Requires-Python >=3.10`, so the 3.9
  leg keeps the skip).
- R-TDH-3: `test_orchestrator_guard_swallows_channel_bug` MUST patch
  `harness.shared.orchestrator.loop.run_shadow_comparison`, the module that
  calls it since `9d38670`.
- R-TDH-4: `.gitignore`, `.dockerignore` and `.mango/hooks/pre-nemotron-run.sh`
  MUST NOT reference `.mcp_storage/` while no tracked code creates it.
- R-TDH-5: `main` MUST be protected by a repository ruleset requiring the
  `build (3.9)`, `build (3.10)`, `build (3.12)`, `build-full`, `secret-scan`
  and `dependency-audit` checks, using the list `test_ci_gate_coverage.py`
  already pins from `NEXT_STEPS.md` as the source; this is an admin action
  recorded in the decision log, not a code change.

Phase 1 — dependency and toolchain hygiene.

- R-TDH-6: Python dependencies MUST be installed in CI from a committed lock
  (`requirements.lock`, generated by `pip-compile` from `requirements.txt` +
  `requirements-dev.txt`), so an upstream release cannot change what CI runs
  without a diff in this repository; Dependabot bumps the lock.
- R-TDH-7: The nine open Dependabot PRs (#38-#46) MUST be resolved after
  Phase 0 lands, tooling first (`ruff` 0.6.9→0.16.x as its own change because
  new rules will fire, then `mypy`, `pytest-mock`, `tomli`, the Node
  dev-deps), runtime ranges last (`fastapi`, `pydantic`).
- R-TDH-8: The project version MUST have one source, `pyproject.toml`
  `[project].version`; `Makefile` header, `README.md`, the top `CHANGELOG.md`
  entry and `harness/node/package.json` are checked against it by
  `test_documentation_truth.py`, which fails on any mismatch.

Phase 2 — hard-coded values back to policy.

- R-TDH-9: `AgentLoop.__init__` in `harness/shared/orchestrator/loop.py` MUST
  default `max_iterations`, `api_timeout` and `max_tool_calls_per_task` from
  `policy_loader.orchestrator_defaults()` / `agent_defaults`, not from the
  literals `15`, `30`, `50`.
- R-TDH-10: `GraphPolicy` field defaults in `harness/shared/langgraph/policy.py`
  MUST be derived from the `policy_loader` fallbacks rather than restating all
  eleven numbers a third time.
- R-TDH-11: `harness/node/src/ai/nemotron/nemotron-client.ts` and `cli.ts`
  MUST read `nemotron.timeout_ms`, `nemotron.max_retries`,
  `nemotron.temperature` and `nemotron.max_tokens` from
  `harness/shared/governance-policy.json` the way `vitest.config.ts` does,
  failing closed on a missing key, with a Vitest liveness test mirroring
  `test_node_coverage_thresholds.py`.
- R-TDH-12: `check_projections.py` and `governance/verify_zero_skips.py` MUST
  read `decision_id_pattern` from the policy instead of each carrying the same
  fallback regex.
- R-TDH-13: The quality-gate path in `harness/shared/langgraph/nodes.py` MUST
  NOT emit a fabricated `"coverage": 85.0`; it reports a measured value or
  omits the key, and the gate rejects a report with no measured value.
- R-TDH-14: Verdict status strings in `governance/broker.py`,
  `governance/verification.py`, `governance/process_backend.py`,
  `langgraph/nodes.py`, `tool_executors.py` and `tool_result_format.py` MUST
  reference the constants in `governance/verdict.py`; a test fails on a raw
  `"BLOCKED"`/`"FAILED"`/`"VERIFIED"` literal outside that module.
- R-TDH-15: Every remaining unlinked numeric constant catalogued in the audit
  (`process_backend.DEFAULT_MAX_OUTPUT_BYTES`, `shadow_planner.DEFAULT_SHADOW_TIMEOUT_SEC`,
  `cognitive_signal.MAX_SIGNAL_BYTES`/`MAX_SINK_BYTES`, `retry_policy` backoff
  values, the Node circuit-breaker and backoff defaults) MUST either gain a
  policy key or be recorded as a true constant in one `DEC-` entry; no third
  state.

Phase 3 — dead code, unwired features, skip accounting.

- R-TDH-16: The verified-dead symbols `write_policy.ALWAYS_DENIED_PREFIXES`,
  `nemotron_bridge.RETRY_BACKOFF_BASE_SEC`, `nemotron_bridge.resolve_api_key`
  and `ToolBudget.remaining` MUST be removed behind a `DeprecationWarning`
  shim for one minor release, and `vulture` MUST join `make lint` with a
  whitelist for framework-registered symbols (FastAPI routes, MCP handlers,
  dataclass fields) so the gate fails on new dead code.
- R-TDH-17: `autonomous_healing.py` and `lats_optimizer.py` MUST be either
  wired into a runtime path behind `synthesis.lats_enabled` (and a new healing
  key) under their own spec, or moved to `harness/shared/experimental/` and
  removed from the documented surface; the test-only facade pass-throughs in
  `mango_mas_orchestrator.py` (`_tool_handlers`, `_run_hook`,
  `_dispatch_tool_calls`, `execute_sequential_thinking_loop`) get their tests
  retargeted to `harness/shared/orchestrator/` and are then deleted.
- R-TDH-18: Python skips MUST be accounted for like Node's (INV-2 parity): a
  `verify_zero_skips`-style gate reads pytest's report and fails on any skip
  without a waiver in a decision-backed `skip-waivers.json`; the langgraph
  skips on the 3.9 leg and the `NVIDIA_API_KEY` live skip are the initial
  waivers.

Phase 4 — structure, god files, enterprise layout.

- R-TDH-19: The 40 top-level modules in `harness/shared/` MUST be regrouped
  into `gates/` (`check_*`, `validate_*`, `coverage_gate`, `plan_rules`,
  `ast_visitors`), `tooling/` (`tool_*`, `meta_tools`, `read_policy`,
  `write_policy`, `agent_authority`), `runtime/` (`nemotron_bridge`,
  `retry_policy`, `agent_prompts`, `debug_dump`, the orchestrator facade) and
  `core/` (`policy_loader`, `json_logging`, `governance_json`), one subpackage
  per PR, each leaving a root re-export shim; `protected_paths` and
  `check_dedup.py` are updated in the same PR, and `check_dedup.py` MUST also
  police root→subpackage shims against `dedup.max_shim_lines` (the existing
  `harness/shared/remotes.py` shim is 46 lines against a budget of 40).
- R-TDH-20: The twenty per-stack shim scripts under `harness/node/scripts/`
  and `harness/jvm/scripts/` MUST collapse to one console entry point
  (`python -m harness.shared.gates <name>`) invoked by the per-stack
  Makefiles; the shim files are deleted once nothing calls them.
- R-TDH-21: Test modules MUST be subject to a size budget, a new policy key
  `limits.test_size_budget_lines` enforced by
  `validate_invariants.check_size_budget`; `test_ci_gate_coverage.py` (920
  lines) is split by concern before the key is enabled so the gate lands green.
- R-TDH-22: The watch-list modules (`plan_rules.py` 428, `write_policy.py`
  363, `langgraph/nodes.py` 343, `governance/pretooluse_guard.py` 341,
  `governance/command_actions.py` 339, `nemotron_bridge.py` 333,
  `check_dedup.py` 313, `cognitive_signal.py` 312,
  `control-plane/publish_policy_artifact.py` 300) MUST stay under
  `limits.size_budget_lines`, and `nemotron-client.ts` (454 lines, no Node
  size gate today) MUST have its retry/backoff logic extracted with an ESLint
  `max-lines` rule sourced from the same policy key.
- R-TDH-23: Documentation MUST be consolidated: the 1,315-line v2.2.4 body
  moves from `CHANGELOG.md` to `docs/releases/v2.2.4.md`;
  `SDLC_HYGIENE_REPORT.md`, `harness/PEER-REVIEW-REMEDIATION.md` and
  `harness/TEST-REPORT.md` move to `docs/reports/`; `harness/CHANGELOG.md`
  (stalled at 2.1.5) folds into the root changelog; the two RCA documents and
  the two C4 documents each merge into one. `NEXT_STEPS.md` stays where it is
  because `test_ci_gate_coverage.py` parses it.

Phase 5 — coverage that measures what ships.

- R-TDH-24: The coverage gate MUST measure `harness/shared/langgraph/` with
  the extra installed on at least one leg (R-TDH-2 provides it), and the six
  lowest files (`check_dedup.py` 92.4 %, `regenerate_bundle_digests.py` 93.5 %,
  `nemotron_bridge.py` 93.7 %, `mango_mas_orchestrator.py` 93.8 %,
  `langgraph/nodes.py` 94.3 %, `coverage_gate.py` 94.4 %) MUST gain tests for
  their named missing branch arcs rather than aggregate padding.
- R-TDH-25: `harness/control-plane/` MUST have colocated tests under
  `harness/control-plane/tests/` listed in `pyproject.toml` `testpaths`; today
  it is covered only indirectly from `harness/shared/tests/`.

Constraints.

- C-TDH-1: No slice MUST weaken an invariant in `harness/CONTRACT.md`, add an
  `xfail`, or add a skip without a decision-log entry (CLAUDE.md).
- C-TDH-2: Every moved or removed public symbol MUST keep a re-export shim
  that emits `DeprecationWarning` for one minor release; removals land no
  earlier than v2.6.0.
- C-TDH-3: Every slice MUST be its own PR with the `make pre-pr` tail pasted
  into the Validation section, and any slice touching `protected_paths` MUST
  carry the attestation table and the `infra-reviewed` label.

## Acceptance criteria

- [ ] AC-1: `python -m mypy harness/shared harness/api_server harness/control-plane --explicit-package-bases --check-untyped-defs`
      exits 0 with `mcp` 2.1.1 installed, and
      `pytest harness/shared/tests/test_mcp_server.py -k test_real_mcp_tool_accepts_the_kwargs_mcp_server_passes`
      passes · stage: `make lint` (R-TDH-1)
- [ ] AC-2: `make test-regression` exits 0 on a runner without `langgraph`
      (the healing test reports SKIPPED) and, on a runner with the extra,
      `pytest -k test_state_graph_healing_loop_recovers_from_test_failure`
      passes rather than skipping; the `build-full` job log shows
      `pip install -e ".[langgraph]"` · stage: `make test-regression` (R-TDH-2)
- [ ] AC-3: `pytest harness/shared/tests/test_shadow_planner.py -k test_orchestrator_guard_swallows_channel_bug`
      passes, and `git grep -n "mango_mas_orchestrator.*run_shadow_comparison" harness/shared/tests`
      returns nothing · stage: `make test-python` (R-TDH-3)
- [ ] AC-4: `pytest harness/shared/tests/test_documentation_truth.py` passes
      and `git grep -n mcp_storage -- .gitignore .dockerignore .mango/hooks`
      returns nothing · stage: `make test-python` (R-TDH-4)
- [ ] AC-5: A PR whose `build-full` check is red is refused by the merge
      button; the ruleset's required-check list equals the set pinned by
      `pytest harness/shared/tests/test_ci_gate_coverage.py -k required`, and
      the decision log carries a `DEC-` entry naming the ruleset
      · stage: `make validate` (R-TDH-5)
- [ ] AC-6: `.github/workflows/python-package.yml` installs from
      `requirements.lock`, and `pip-compile --dry-run` against the lock exits
      0 with no changes; a test in `test_ci_gate_coverage.py` fails if a
      workflow step installs from `requirements-dev.txt` directly
      · stage: `make ci` (R-TDH-6)
- [ ] AC-7: `gh pr list --state open --author app/dependabot` (or the GitHub
      PR list) shows zero PRs older than 14 days, and `make lint` exits 0 with
      the bumped `ruff` pin · stage: `make lint` (R-TDH-7)
- [ ] AC-8: `pytest harness/shared/tests/test_documentation_truth.py -k version`
      fails when any of `Makefile`, `README.md`, `CHANGELOG.md` or
      `harness/node/package.json` disagrees with `pyproject.toml`, and passes
      on the reconciled tree · stage: `make test-python` (R-TDH-8)
- [ ] AC-9: `pytest harness/shared/tests -k "AgentLoop and defaults"`
      constructs `AgentLoop` with no budget arguments and asserts the values
      equal `orchestrator.max_iterations`, `orchestrator.api_timeout_sec` and
      `agent_defaults.max_tool_calls_per_task` read from
      `governance-policy.json`; `git grep -nE "= (15|30|50)," harness/shared/orchestrator/loop.py`
      returns nothing · stage: `make test-python` (R-TDH-9)
- [ ] AC-10: `pytest harness/shared/tests/test_langgraph_policy.py` includes a
      distinguishable-value test in which a temporary policy with
      `recursion_limit: 77` yields `GraphPolicy().recursion_limit == 77`, and
      fails when the dataclass restates the literal · stage: `make test-python` (R-TDH-10)
- [ ] AC-11: `pnpm exec vitest run tests/ai` includes a liveness test that
      rewrites `nemotron.max_retries` in a temp copy of the policy and asserts
      `DEFAULT_NEMOTRON_CONFIG.maxRetries` follows it, and that the client
      throws when the policy lacks the key; `git grep -n "maxRetries: 3" harness/node/src`
      returns nothing · stage: `make test-node` (R-TDH-11)
- [ ] AC-12: `git grep -n "DEC-\[0-9\]" harness/shared/check_projections.py harness/shared/governance/verify_zero_skips.py`
      returns nothing, and both scripts exit 1 when `decision_id_pattern` is
      missing from the policy · stage: `make validate` (R-TDH-12)
- [ ] AC-13: `git grep -n '"coverage": 85.0' harness/shared/langgraph` returns
      nothing, and `pytest harness/shared/tests/test_langgraph_nodes.py -k quality_gate`
      asserts the gate returns a non-pass verdict when no measured coverage is
      present · stage: `make test-langgraph` (R-TDH-13)
- [ ] AC-14: `pytest harness/shared/tests -k verdict_literals` fails on any
      raw `"BLOCKED"`, `"FAILED"` or `"VERIFIED"` string literal in a
      first-party module other than `governance/verdict.py`, and passes on the
      migrated tree · stage: `make test-python` (R-TDH-14)
- [ ] AC-15: Every constant in the R-TDH-15 list either resolves through
      `policy_loader` (covered by `pytest -k policy_liveness`) or is named in
      one `DEC-` entry in `harness/node/.governance/decision-log.md`;
      `make validate` fails if the decision-log entry is absent from
      `GOVERNANCE_SKILL.md` · stage: `make validate` (R-TDH-15)
- [ ] AC-16: `python -m vulture harness/shared harness/api_server harness/control-plane --min-confidence 80 --exclude '*/tests/*' --config vulture_whitelist.py`
      exits 0 and is a prerequisite of `make lint`; importing
      `ALWAYS_DENIED_PREFIXES` from `harness.shared.write_policy` emits
      `DeprecationWarning` (checked by `pytest -k deprecation_shims`)
      · stage: `make lint` (R-TDH-16)
- [ ] AC-17: `git grep -ln "autonomous_healing\|lats_optimizer" harness --  ':!*/tests/*'`
      lists either a runtime caller gated on `synthesis.lats_enabled` or only
      files under `harness/shared/experimental/`; `pytest harness/shared/tests -k orchestrator`
      passes with the facade pass-throughs deleted · stage: `make test-python` (R-TDH-17)
- [ ] AC-18: `make verify-zero-skips-python` exits 1 on a suite containing an
      unwaived `pytest.skip` and exits 0 on the current tree with the two
      initial waivers, and it is a prerequisite of `make ci`
      · stage: `make ci` (R-TDH-18)
- [ ] AC-19: For each new subpackage, `python -c "import harness.shared.<old_name>"`
      still succeeds (emitting `DeprecationWarning`),
      `make check-dedup` fails when a root shim exceeds `dedup.max_shim_lines`,
      and `pytest harness/shared/tests/test_protected_path_liveness.py`
      passes with the updated `protected_paths` · stage: `make ci` (R-TDH-19)
- [ ] AC-20: `ls harness/node/scripts/*.py harness/jvm/scripts/*.py` returns
      nothing, `make -C harness/node validate` exits 0 through the console
      entry point, and `python -m harness.shared.gates nonexistent` exits 2
      · stage: `make check-dedup` (R-TDH-20)
- [ ] AC-21: `python harness/shared/validate_invariants.py` fails on a test
      file one line over `limits.test_size_budget_lines` and passes on the
      tree after `test_ci_gate_coverage.py` is split; `wc -l harness/shared/tests/test_ci_gate_coverage*.py`
      shows no file above the key · stage: `make validate` (R-TDH-21)
- [ ] AC-22: `python harness/shared/validate_invariants.py` passes with every
      watch-list module under `limits.size_budget_lines`, and
      `pnpm exec eslint . --max-warnings=0` fails on a source file over the
      policy-sourced `max-lines` value · stage: `make lint-node` (R-TDH-22)
- [ ] AC-23: `wc -c CHANGELOG.md` is under 40 000 bytes,
      `ls SDLC_HYGIENE_REPORT.md harness/PEER-REVIEW-REMEDIATION.md harness/TEST-REPORT.md harness/CHANGELOG.md`
      reports no such file, `ls docs/releases/v2.2.4.md docs/reports/` succeeds,
      and `pytest harness/shared/tests/test_documentation_truth.py` passes
      · stage: `make test-python` (R-TDH-23)
- [ ] AC-24: `python harness/shared/coverage_gate.py` passes with the
      `langgraph` extra installed and reports every file in the R-TDH-24 list
      at or above its current percentage plus the named missing arcs closed;
      it still exits 1 on a malformed `coverage.json` · stage: `make coverage-python` (R-TDH-24)
- [ ] AC-25: `pytest harness/control-plane/tests` collects at least one test
      per script in `harness/control-plane/*.py`, and `pyproject.toml`
      `testpaths` lists the directory · stage: `make test-python` (R-TDH-25)
- [ ] AC-26: `git grep -n "xfail\|pytest.skip" harness/shared/tests harness/api_server/tests`
      shows no new occurrence relative to `2555ca0` without a matching
      `DEC-` entry, and `make validate` passes on every slice · stage: `make validate` (C-TDH-1)
- [ ] AC-27: `pytest -W error::DeprecationWarning harness/shared/tests -k not deprecation_shims`
      passes (first-party code does not import through the shims) while
      `pytest -k deprecation_shims` asserts each shim warns · stage: `make test-python` (C-TDH-2)
- [ ] AC-28: Every PR in this plan has `make pre-pr` output in its Validation
      section and, where `make validate` reports a protected path, the
      attestation table; `make validate` exits 1 on a protected-path slice
      without `ALLOW_GITHUB_CHANGES=1` · stage: `make pre-pr` (C-TDH-3)

## Steps

Ordered by dependency. Sizes are changed-line estimates for review planning;
each numbered step is one PR unless noted.

### Phase 0 — green `main` (1 PR, ~60 lines, this week)

1. Rename the `Tool` kwarg and attribute to `input_schema` in
   `mcp_server.py` and `test_mcp_server.py` — produces a passing `make lint`
   on 3.10+ (R-TDH-1).
2. Add the `LANGGRAPH_AVAILABLE` guard to the healing E2E test; add
   `python -m pip install -e ".[langgraph]"` to the `build-full` job and to
   the 3.10/3.12 matrix legs (conditional on `matrix.python-version != '3.9'`)
   — produces a `build-full` log in which the guarded tests run (R-TDH-2).
   This touches `.github/workflows/**`, so the PR carries the attestation
   table and needs the `infra-reviewed` label.
3. Retarget the shadow-planner containment test's patch to
   `harness.shared.orchestrator.loop` (R-TDH-3).
4. Delete the `.mcp_storage` rules from `.gitignore`/`.dockerignore` and the
   hook warning (R-TDH-4).
5. Open the ruleset on `main` (admin), record `DEC-` entry, and add the
   required-check names to `NEXT_STEPS.md` where `test_ci_gate_coverage.py`
   reads them (R-TDH-5).

### Phase 1 — dependencies (3 PRs)

6. Introduce `requirements.lock` via `pip-compile`; switch the four install
   steps in both workflows to it; add the workflow-parsing test (R-TDH-6).
   Protected path.
7. Land the Dependabot queue in the order given by R-TDH-7; the `ruff` bump is
   its own PR because `test_deferred_rigor.py` records rule counts that will
   change (R-TDH-7).
8. Add the version-consistency test and reconcile the five files to 2.4.0
   (the highest claimed) or to the next release number, decided in the PR
   (R-TDH-8).

### Phase 2 — hard-coded values (5 PRs; Node slice gets `make spec NAME=node-policy-wiring`)

9. `AgentLoop` defaults and `GraphPolicy` defaults from `policy_loader`
   (R-TDH-9, R-TDH-10). Protected path (`harness/shared/langgraph/**`).
10. Node client policy wiring + liveness test (R-TDH-11).
11. `decision_id_pattern` single source; remove the fabricated coverage value
    and make the quality gate fail closed (R-TDH-12, R-TDH-13).
12. Verdict-constant migration and the literal-scan test (R-TDH-14).
13. Constant triage: one PR that adds keys or one `DEC-` entry per constant
    (R-TDH-15).

### Phase 3 — dead code and skips (3 PRs)

14. Remove the four dead symbols behind shims; add `vulture` and the
    whitelist to `make lint` (R-TDH-16).
15. Decide and execute the fate of `autonomous_healing.py` /
    `lats_optimizer.py`; retarget facade tests and delete the pass-throughs
    (R-TDH-17). Requires its own spec if the "wire it in" branch is chosen.
16. Python zero-skip gate with the two initial waivers; add to `make ci`
    (R-TDH-18). Protected path (`Makefile`).

### Phase 4 — structure (6 PRs, one per subpackage plus docs)

17. `core/` first (fewest dependents), then `gates/`, `tooling/`, `runtime/`;
    each PR moves modules, leaves shims, updates `protected_paths` and
    `check_dedup.py`, and extends `check_dedup` to police root shims on the
    first slice (R-TDH-19). Every slice is a protected-path change.
18. Console entry point and per-stack shim removal (R-TDH-20).
19. Split `test_ci_gate_coverage.py`, then enable
    `limits.test_size_budget_lines` (R-TDH-21); extract retry/backoff from
    `nemotron-client.ts` and add the ESLint `max-lines` rule (R-TDH-22).
20. Documentation consolidation (R-TDH-23).

### Phase 5 — coverage (2 PRs)

21. Branch-arc tests for the six lowest files; confirm langgraph measured in
    CI (R-TDH-24).
22. Colocated control-plane tests and `testpaths` update (R-TDH-25).
    Protected path (`pyproject.toml`).

## Files touched

Phase 0: `harness/shared/mcp_server.py`, `harness/shared/tests/test_mcp_server.py`,
`harness/shared/tests/regression/test_e2e_nemotron_triage_regression.py`,
`harness/shared/tests/test_shadow_planner.py`, `.gitignore`, `.dockerignore`,
`.mango/hooks/pre-nemotron-run.sh`, `.github/workflows/python-package.yml`
(protected), `NEXT_STEPS.md`, `harness/node/.governance/decision-log.md`,
`harness/node/agents/GOVERNANCE_SKILL.md`.

Phase 1: `requirements.lock` (new), `.github/workflows/python-package.yml`,
`.github/workflows/scheduled-drift.yml` (protected), `requirements-dev.txt`
(protected), `harness/shared/tests/test_ci_gate_coverage.py` (protected),
`harness/shared/tests/test_documentation_truth.py`, `Makefile` (protected),
`README.md`, `CHANGELOG.md`, `harness/node/package.json`.

Phase 2: `harness/shared/orchestrator/loop.py`, `harness/shared/langgraph/policy.py`
(protected), `harness/shared/langgraph/nodes.py` (protected),
`harness/node/src/ai/nemotron/nemotron-client.ts`, `harness/node/src/ai/nemotron/cli.ts`,
`harness/node/tests/**`, `harness/shared/check_projections.py` (protected),
`harness/shared/governance/verify_zero_skips.py` (protected),
`harness/shared/governance/{broker,verification,process_backend}.py` (protected),
`harness/shared/tool_executors.py`, `harness/shared/tool_result_format.py`,
`harness/shared/governance-policy.json` (protected).

Phase 3: `harness/shared/write_policy.py` (protected), `harness/shared/nemotron_bridge.py`,
`harness/shared/tool_budget.py`, `vulture_whitelist.py` (new), `Makefile` (protected),
`harness/shared/autonomous_healing.py`, `harness/shared/lats_optimizer.py`,
`harness/shared/mango_mas_orchestrator.py` (protected),
`harness/shared/governance/verify_zero_skips.py` (protected),
`harness/shared/tests/skip-waivers.json` (new).

Phase 4: `harness/shared/{core,gates,tooling,runtime}/` (new), root shims,
`harness/shared/check_dedup.py` (protected), `harness/shared/governance-policy.json`
(protected), `harness/node/scripts/*`, `harness/jvm/scripts/*`, `harness/node/Makefile`,
`harness/jvm/Makefile` (protected), `harness/shared/validate_invariants.py` (protected),
`harness/shared/tests/test_ci_gate_coverage*.py` (protected),
`harness/node/eslint.config.*`, `CHANGELOG.md`, `docs/releases/`, `docs/reports/`.

Phase 5: `harness/shared/tests/**` additions, `harness/control-plane/tests/` (new),
`pyproject.toml` (protected).

## Invariants touched

- INV-2: extended to Python by R-TDH-18; the Node half is untouched.
- INV-5: R-TDH-5 makes the required-gate list a real merge requirement rather
  than an aspiration; R-TDH-6 adds the lock-install check to
  `test_ci_gate_coverage.py`.
- INV-8, INV-9, INV-10: unchanged; verdict-constant migration (R-TDH-14) is a
  representation change, pinned by the existing broker and verdict suites.
- INV-15: R-TDH-17 keeps `lats_enabled: false` as the only switch that can
  reach the optimizer.
- INV-16: the Node client wiring (R-TDH-11) and constant triage (R-TDH-15)
  touch no cognitive-signal path; the boundary suite (`pytest -m governance`)
  runs on every slice.
- INV-17: this document is itself gated by `make specs`.

## Validation matrix

- `make ci` on every slice — ruff + mypy + pytest + coverage floors from
  `governance-policy.json → coverage.{lines,branches,per_file}` + specs +
  check-dedup + validate_invariants (R-TDH-1 … R-TDH-25, C-TDH-1).
- `make pre-pr` before each PR opens; tail pasted into the PR (C-TDH-3).
- `make test-regression` on a runner with and without the `langgraph` extra
  (R-TDH-2, R-TDH-24).
- `make test-node` and `make lint-node` for the Node slices (R-TDH-11,
  R-TDH-22).
- `make validate` after every protected-path slice, with and without
  `ALLOW_GITHUB_CHANGES=1` to confirm it still fails closed (C-TDH-3).
- `pytest -W error::DeprecationWarning` on the shim slices (C-TDH-2).
- Coverage target: `governance-policy.json → coverage.lines` (90) and
  `coverage.branches` (80), measured baseline 97.70 / 95.78 on `2555ca0`
  with the extra absent; the Phase 5 exit criterion is no file below its
  baseline once langgraph is measured.

## Backward compatibility

Every import path that exists on `2555ca0` continues to resolve for one minor
release: moved modules leave a root shim that re-exports every public name and
emits `DeprecationWarning`; removed symbols do the same. The `MangoMASOrchestrator`
facade keeps its public constructor and `execute_agent`; only the private
test-only pass-throughs go (after their tests are retargeted). The Node client
keeps `DEFAULT_NEMOTRON_CONFIG` as its export; the values now come from the
policy file at module load. `requirements.txt` keeps its ranges as the
human-edited input; the lock is derived. The version reconciliation changes
strings only. Removal of shims is scheduled for v2.6.0 and recorded in the
decision log when each shim lands.

## Open questions

1. Version number after reconciliation: adopt 2.4.0 (already claimed in the
   changelog and Makefile) or cut 2.5.0 with this plan's Phase 0 as its first
   entry? Blocks step 8 only.
2. `autonomous_healing.py` / `lats_optimizer.py`: wire in behind policy or
   park under `experimental/`? Product call; blocks step 15 only. The
   evidence (zero runtime callers, `lats_enabled: false` with no reader)
   favours parking until an ablation gate exists (INV-15).
3. Whether the `harness/jvm/` adopter template stays in this repository at
   all, given nothing executes it (CONTRACT.md already says so). Out of scope
   here; raised because R-TDH-20 touches its scripts.
4. Mutation testing (`mutmut`) on `harness/shared/governance/` as a Phase 5
   stretch: the branch numbers are high enough that mutation score is the
   next honest signal, but it is slow and no CI budget is allocated. Not
   blocking.
