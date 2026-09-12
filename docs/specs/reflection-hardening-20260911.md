# Spec: reflection-hardening-20260911

Spec class: program-plan

> Status: IN PROGRESS · Date: 2026-09-12 · Base: `origin/main` @ `51abdfd`
> (PR #131 merged). Branch `cursor/c-plr2-failclosed-tests-f4b2`.
>
> **Spec class:** program-plan — requirement IDs below name scheduled work for
> this increment, so the traceability gate counts them without requiring an
> implementation citation until the work lands.
>
> Ledger follow-up, not a from-scratch audit. PR #131 already restored CI,
> NS-21, the workflow-test split, and the NS-39 ratchet. `.mango/skills/tech-debt-audit`
> forbids re-deriving those findings. This document does **not** re-specify
> `reasoner-bridge-tool-parity`, `python-floor-310`, `gate-hardening`,
> `god-file-decomposition`, or NS-21.

## Context7 disclosure

Context7 MCP `resolve-library-id` was retried once for pytest at implementation
time (documentation only). It returned `Monthly quota exceeded`. No requirement
below is sourced from Context7. Fallback: https://docs.pytest.org/en/stable/
(`pytest.raises`); floors remain `coverage.lines` / `coverage.branches` in
`governance-policy.json` via `coverage_gate.py`.

`/agents-deploy` does not apply: this repository has no `agentcore.json`, no
`agentcore` CLI, and no AWS caller identity in this environment.

## Problem statement

PR #131's adversarial sweep recorded three leftovers without scheduling them:

1. **C-PLR-2.** `plan_rules.REQ_PATTERN` and `check_traceability.REQ` compiled
   the same body. `validate_specs` already imports `REQ_PATTERN`; the
   traceability gate did not, so the two matchers can drift.
2. **Fail-closed arms untested.** `denial_rate._load_json_object` /
   `load_corpus` reject malformed JSON, a non-object root, and a missing
   `commands` list; `context_policy` rejects `chars_per_token <= 0`,
   `budget_tokens < 0`, and bool `prompt_tokens`. None of those branches had
   a test. `coverage.per_file` still held.
3. **Remediation AC-23.** `requires-python` is `>=3.10` but the written
   `git grep 3.9` still matches historical comments. The selector MUST ignore
   comment-only hits so the box can be ticked without rewriting DEC-017
   comments in protected files.

## Requirements

- R-RH3-1: `harness.shared.governance.check_traceability.REQ` MUST be
  `harness.shared.plan_rules.REQ_PATTERN` (same object when the package
  loads). The gate MUST keep constructing `REQ` after the repo root is on
  `sys.path` so `cd harness/node && python ../shared/governance/check_traceability.py`
  still imports (C-PLR-2).
- R-RH3-2: `denial_rate._load_json_object` MUST exit on unreadable/malformed
  JSON, a directory path, and a non-object root; `load_corpus` MUST exit when
  `commands` is missing or not a list. `estimate_tokens` MUST raise
  `ValueError` when `chars_per_token <= 0`; `apply_context_policy` MUST raise
  when `budget_tokens < 0`; `measure_tokens` MUST ignore a bool
  `usage.prompt_tokens` and fall back to the estimate.
- R-RH3-3: Remediation AC-23 MUST judge uncommented `3.9` / `target-version`
  hits only; comment-only historical mentions MUST NOT fail the criterion.
- C-RH3-1: This increment MUST NOT implement NS-1, NS-2, NS-3, NS-30, Phase E,
  NS-36 signatures, NS-35, HITL, LATS, or the LangGraph swallow (NS-9).
- C-RH3-2: This increment MUST NOT raise `traceability.max_uncited_contract_requirement_ids`
  or change coverage floors.
- C-RH3-3: This increment MUST NOT bind restored hooks in `.claude/settings.json`
  (DEC-003) or add a new skill.

## Acceptance criteria

- [x] AC-1: `pytest harness/shared/tests/test_traceability_scope.py -k requirement_id_matcher`
      passes; replacing `REQ` with a second `re.compile` of a different body
      fails that test · stage: `make test-python` (R-RH3-1, C-PLR-2)
- [x] AC-2: `pytest harness/shared/tests/test_denial_rate.py -k "malformed_json or non_object_root or without_a_commands_list"`
      and `pytest harness/shared/tests/test_context_policy.py -k "non_positive_chars_per_token or negative_budget or bool_prompt_tokens"`
      pass · stage: `make test-python` (R-RH3-2)
- [x] AC-3: `pytest harness/shared/tests/test_ci_gate_required_checks.py -k non_comment`
      passes; putting uncommented `3.9` in `pyproject.toml` would fail it ·
      stage: `make test-python` (R-RH3-3)
- [x] AC-4 (rejection): `pytest harness/shared/tests/test_context_policy.py -k negative_budget`
      fails closed on `budget_tokens=-1`; `pytest harness/shared/tests/test_denial_rate.py -k non_object_root`
      fails closed on a JSON array corpus/policy object · stage: `make test-python`
      (R-RH3-2)
- [x] AC-5: `ls LICENSE` still fails; `pytest harness/shared/tests/test_traceability_scope.py -k ratchet_may_only_be_lowered`
      still fails if the uncited ratchet is raised; `pytest harness/shared/tests/test_agent_surface_liveness.py -k mango_hooks_stay_dormant`
      still fails if `.mango/settings.json` is copied into `.claude/settings.json`
      · stage: `make test-python` (C-RH3-1, C-RH3-2, C-RH3-3)

## Steps

1. Import `REQ_PATTERN as REQ` after `_gate_logger` — produces
   `harness/shared/governance/check_traceability.py` (protected)
2. Pin identity and fail-closed arms — produces tests listed above
3. Rewrite remediation AC-23 to the uncommented pin test — produces
   `docs/specs/2026-standards-remediation-plan.md`

## Files touched

- `harness/shared/governance/check_traceability.py` (P)
- `harness/shared/tests/test_traceability_scope.py`
- `harness/shared/tests/test_denial_rate.py`
- `harness/shared/tests/test_context_policy.py`
- `harness/shared/tests/test_ci_gate_required_checks.py`
- `docs/specs/reflection-hardening-20260911.md`
- `docs/specs/2026-standards-remediation-plan.md`
- `CHANGELOG.md`
- `NEXT_STEPS.md`

## Invariants touched

- INV-5: gates still invoked by Makefile targets; no new target.
- INV-2: no skips or xfails added.
- Size budget: `check_traceability.py` stays under `limits.size_budget_lines`.

## Validation matrix

- `ALLOW_GITHUB_CHANGES=1 make ci` and `make lint-cold`
- coverage from `coverage_gate.py` against `governance-policy.json`
- `make attestation-check` for `check_traceability.py`

## Backward compatibility

`REQ.findall` / `REQ.search` call sites keep the `REQ` name. No public API
change. Dependabot PRs stay separate; `NODE24_ACTION_MAJORS` remain floors.

## Open questions

None. Owner P0s stay parked (C-RH3-1).

## openspec-peer-review

- **Architecture.** Import, do not regroup `harness/shared/` (DEC-020). Sign-off.
- **SDLC.** One protected file; attestation required. Sign-off.
- **QA.** Named fail-closed branches only. Sign-off.
- **Product.** No new skill; `/agents-deploy` N/A. Sign-off.

## repo-invariant-review

Predicted collision: `[FAIL] Protected Paths` on
`harness/shared/governance/check_traceability.py` without
`infra-reviewed` / `ALLOW_GITHUB_CHANGES=1`.
