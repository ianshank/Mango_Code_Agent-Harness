# Spec: Agent Evaluation Harness

> **Change:** `add-neurosym-governed-synthesis`
> **Version:** 1.0.0-draft
> **Authors:** SQE Lead · AIOps Lead · Product Manager
> **Status:** DRAFT

---

## Problem Statement

The repository has no evaluation harness that compares synthesis strategies against a shared benchmark. `mango_mas_orchestrator.py` runs multi-agent loops but produces no ablation data, no reproducible evidence bundle, and no cost/latency/quality accounting. There is no mechanism to gate LATS rollout on measurable thresholds. **Evidence:** `governance-policy.json` has INV-15 (`LATS MUST remain disabled by default until its cost-adjusted evaluation threshold is met`) but no policy field defines what "threshold" means numerically, and no code enforces it.

---

## Acceptance Criteria

- [ ] **AC-AE-1:** The evaluation harness runs all 30 seed tasks against three strategies — `SingleShotStrategy`, `DeterministicVerifierStrategy`, `BoundedLatsStrategy` — and produces a structured `EvaluationReport` with per-strategy results for each task.
  _Verified by:_ `pytest -k test_evaluation_report_covers_all_strategies_and_tasks` · stage: `make test-neurosym`

- [ ] **AC-AE-2:** Every `BenchmarkResult` includes: `task_version`, `model_id`, `provider`, `policy_bundle_digest`, `execution_backend_version`, `random_seed` (where used), `cost_usd`, `latency_ms`, `outcome`. No field may be empty or `None`.
  _Verified by:_ `pytest -k test_benchmark_result_fields_are_complete` · stage: `make test-neurosym`

- [ ] **AC-AE-3:** Re-running the evaluation harness from a committed evidence bundle (replay mode) produces identical `outcome` and `policy_bundle_digest` fields. `cost_usd` and `latency_ms` are excluded from the replay equality check.
  _Verified by:_ `pytest -k test_evaluation_replay_is_reproducible` · stage: `make test-neurosym`

- [ ] **AC-AE-4:** `BoundedLatsStrategy` is disabled by default. It activates only when `synthesis.lats_enabled: true` is present in `governance-policy.json` AND `EvaluationReport.lats_quality_per_dollar` exceeds `synthesis.lats_quality_threshold` from policy. Hardcoded enable is not permitted.
  _Verified by:_ `pytest -k test_lats_is_disabled_by_default` + `pytest -k test_lats_activates_only_above_threshold` · stage: `make test-neurosym`

- [ ] **AC-AE-5:** Seed tasks cover all required failure modes: repository-local maintenance (5), policy violation (5), parser failure (5), compiler failure (5), test failure (5), secret exposure (3), sandbox denial (2). Total: 30 tasks, all deterministic (fixed inputs, no random unless `random_seed` is recorded).
  _Verified by:_ `pytest -k test_seed_task_suite_coverage` · stage: `make test-neurosym`

- [ ] **AC-AE-6:** Trace export for training datasets is prohibited unless `EvaluationReport.redaction_verified: true` and `export_approved_by` is non-empty. Attempting export without these fields raises `TraceExportForbiddenError`.
  _Verified by:_ `pytest -k test_unapproved_trace_export_is_blocked` · stage: `make test-governance`

- [ ] **AC-AE-7:** `make ci` passes on all 4 Python matrix versions.
  _Verified by:_ CI matrix · stage: `make ci`

---

## Invariants Touched

- **INV-2** (no unapproved skips): The evaluation harness produces a Vitest/pytest result JSON; `make verify-zero-skips` enforces no unapproved skips on benchmark fixtures. Verified by: `make verify-zero-skips`.
- **INV-5** (CI invokes every gate): A new `make test-neurosym` target is added and wired into `make ci`. Verified by: `make ci` dry-run.
- **INV-13** (verified result digests): `BenchmarkResult` carries `policy_bundle_digest` and `execution_backend_version`. Verified by: AC-AE-2.
- **INV-14** (redacted traces before export): `TraceExportForbiddenError` is raised for unredacted/unapproved traces. Verified by: AC-AE-6.
- **INV-15** (LATS default-off): `BoundedLatsStrategy` requires explicit policy opt-in + threshold satisfaction. Verified by: AC-AE-4.

---

## Validation Matrix

| Stage | Make Target | Pass Criteria |
|-------|-------------|---------------|
| Neurosym tests | `make test-neurosym` | AC-AE-1..5 pass |
| Governance tests | `make test-governance` | AC-AE-6 passes |
| Zero-skip | `make verify-zero-skips` | INV-2 holds for benchmark fixtures |
| Coverage | `make coverage-python` | `evaluation/` package ≥ `coverage.lines` |
| Full CI | `make ci` | All above on 4 Python versions |

---

## Backward Compatibility

- The evaluation harness is entirely new (`harness/shared/evaluation/`). No existing module is modified.
- `governance-policy.json` gains `synthesis.lats_enabled: false`, `synthesis.lats_quality_threshold: 0.0`, and `synthesis.seed_task_suite_version: "1.0"`. Existing readers unaffected.
- The `make test-neurosym` target is additive. Existing `make test-python` target is unchanged.

---

## Open Questions

> [!IMPORTANT]
> **DEC-AE-001 (BLOCKING):** LATS quality-per-dollar threshold value. The policy declares `lats_quality_threshold` but its value must be established by the M4 baseline run before M5 begins. Placeholder value of `0.0` means LATS is always eligible once enabled — this is incorrect. Threshold must be set from M4 ablation results. Block M5 on this.

> [!IMPORTANT]
> **DEC-AE-002 (BLOCKING):** Seed task fixture format. Are seed tasks: (a) plain Python files with a docstring describing the task + expected output, (b) structured JSON with task spec + oracle, (c) pytest parametrize fixtures? Option (b) (structured JSON) is recommended for reproducibility and replay. Resolve before Milestone 4 gate.

> [!NOTE]
> **DEC-AE-003:** Pong deterministic faults (`tasks.md` M4: "fixed subset of Pong deterministic faults as simulation fixtures, not product features"). Scope: 3–5 faults maximum, each a self-contained file under `harness/shared/evaluation/fixtures/pong/`. No Pong game logic is added to the evaluation harness.
