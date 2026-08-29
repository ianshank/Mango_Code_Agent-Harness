# Spec: Neuro-Symbolic Synthesis Runtime

> **Change:** `add-neurosym-governed-synthesis`
> **Version:** 1.0.0-draft
> **Authors:** Architect · Dev Lead · SQE Lead
> **Status:** DRAFT — pending decision log entries DEC-NS-001 (async strategy), DEC-NS-002 (critique schema version)

---

## Problem Statement

The repository contains reusable governance primitives (`EvidenceBuilder`, `ExecutionBroker`, `pretooluse_guard`), a resilient model client (`nemotron_bridge.py`), and deterministic verifiers, but they are not wired into a coherent synthesis loop. There is no bounded search strategy, no structured critique normalization, and no evidence-backed failure mode. **Evidence:** `mango_mas_orchestrator.py` has no critique normalization and no repair loop — there is no occurrence of `repair` or `critique` in it — so INV-11 and INV-12 govern nothing that exists, and both are declared dormant in `test_invariant_liveness.py`. (Corrected 2026-08-29: this line previously also claimed the orchestrator "runs unbounded multi-agent loops without policy verdicts" and violated INV-9. Both were true when drafted and are false on `main` since DEC-011: `ExecutionBroker` is imported and used, and the loop is bounded by `max_iterations` plus `ToolBudget`. Nothing caught the drift because `openspec/` is outside every CI gate — `SPEC_DIR` defaults to `docs/specs` and no target points at `openspec/`.)

---

## Acceptance Criteria

- [ ] **AC-NS-1:** A `SynthesisRequest` submitted to any `SynthesisStrategy` implementation is rejected at the `GovernanceControlPlane` before execution if the candidate AST violates a prohibited-import rule.
  _Verified by:_ `pytest -k test_policy_denies_prohibited_import` · stage: `make test-governance`

- [ ] **AC-NS-2:** When a synthesis search reaches its configured inference budget without a verified candidate, the runtime returns `SynthesisResult(status="FAILED")` with a non-empty `evidence_id` and `best_candidate_summary`. The runtime MUST NOT attempt further expansions.
  _Verified by:_ `pytest -k test_budget_exhaustion_returns_failed_with_evidence` · stage: `make test-neurosym`

- [ ] **AC-NS-3:** Every failed policy, parser, compiler, test, and sandbox outcome is normalized into a `Critique` object pinned to `critique_schema_version` before a repair attempt is triggered. Raw error strings MUST NOT be passed to the next attempt.
  _Verified by:_ `pytest -k test_critique_normalization_*` (parametrized over all failure types) · stage: `make test-neurosym`

- [ ] **AC-NS-4:** A DENY verdict for a specific candidate digest is terminal. Re-submitting the same candidate digest — including after a repair that produces identical output — MUST return DENY without re-evaluation.
  _Verified by:_ `pytest -k test_deny_is_terminal_for_same_digest` · stage: `make test-governance`

- [ ] **AC-NS-5:** The repair loop MUST stop after `synthesis.max_repair_cycles` from `governance-policy.json` (default: 3). Exceeding the budget MUST produce `status="FAILED"` with `termination_reason="repair_budget_exhausted"`.
  _Verified by:_ `pytest -k test_repair_loop_respects_budget` · stage: `make test-neurosym`

- [ ] **AC-NS-6:** `make ci` passes on all 4 Python matrix versions (3.9, 3.10, 3.11, 3.12) with ≥ `governance-policy.json → coverage.lines` total coverage and no per-file violations.
  _Verified by:_ CI matrix run · stage: `make ci`

---

## Invariants Touched

- **INV-8** (approved execution broker): All synthesis candidates execute through `ExecutionBroker`. The broker is the only permitted code-execution path. Verified by: `test_synthesis_does_not_bypass_broker`.
- **INV-9** (deterministic policy verdict before execution): `GovernanceControlPlane.evaluate()` is called and returns a verdict before `ExecutionBroker.execute()` is called. Verdict is deterministic for a given `(candidate_digest, policy_bundle_digest)` pair. Verified by: AC-NS-1.
- **INV-10** (DENY is terminal): A DENY verdict cannot be overridden by reflection, voting, or repair on the same candidate digest. Verified by: AC-NS-4.
- **INV-11** (critique + evidence ID): Every repair attempt references a normalized `Critique` with an immutable `evidence_id`. Verified by: AC-NS-3.
- **INV-12** (bounded repair budget): Repair loops stop at `synthesis.max_repair_cycles`; budget is config-driven from `governance-policy.json`, not hardcoded. Verified by: AC-NS-5.
- **INV-15** (LATS default-off): `BoundedLatsStrategy` is not activated unless `synthesis.lats_enabled: true` in policy AND the ablation gate in `tasks.md §Evaluation Gate` is passed. Verified by: `test_lats_is_disabled_by_default`.

---

## Validation Matrix

Thresholds are read from `harness/shared/governance-policy.json` — values below are current policy, not hardcoded.

| Stage | Make Target | Pass Criteria |
|-------|-------------|---------------|
| Lint + types | `make lint` | ruff 0 errors, mypy 0 errors, check_py_compat 0 violations |
| Coverage | `make coverage-python` | ≥ `coverage.lines` (currently 90%) total; no per-file below threshold |
| Governance tests | `make test-governance` | AC-NS-1, AC-NS-4; all INV-8..INV-12 markers pass |
| Neurosym unit tests | `make test-neurosym` | AC-NS-2, AC-NS-3, AC-NS-5, AC-NS-6 |
| Zero-skip invariant | `make verify-zero-skips` | INV-2: no unapproved skips |
| Drift gate | `make check-dedup` | No per-stack copies of shared logic |
| Digest sync | `make digest-regen` | Protected-file digests match committed bundle |
| Full CI | `make ci` | All above; all 4 Python versions |

---

## Backward Compatibility

- `harness/shared/governance/broker.py` public API (`ExecutionBroker`, `ExecutionResult`) is **not broken**. The synthesis layer wraps it; it does not replace it.
- `EvidenceBuilder` gains two new optional fields (`candidate_digest`, `policy_bundle_digest`) with `None` defaults. Existing callers that do not set them continue to work but receive a deprecation warning at export time.
- `governance-policy.json` gains a new `synthesis` section. Existing callers that do not read it are unaffected.
- **Breaking change (documented):** `EvidenceBuilder.export()` previously raised `OSError` for a missing key. It now raises `ValueError`. Any callers catching `OSError` must update their exception handler. Migration: replace `except OSError` → `except (OSError, ValueError)` during the transition period (v2.1.7–v2.2.0).

---

## Open Questions

> [!IMPORTANT]
> **DEC-NS-001 (BLOCKING):** Async vs sync synthesis strategy. `design.md` defines `SynthesisStrategy.synthesize()` as `async def`. The existing stack is fully synchronous. Adopting async requires `asyncio` event loop management and changes to the test harness. Decision: sync-first with a `run_sync()` wrapper, defer async to Milestone 5 once the strategy interface is stable.

> [!IMPORTANT]
> **DEC-NS-002 (BLOCKING):** Critique schema version. The versioned critique schema must be declared before the repair loop is implemented. Proposed: `critique_schema_version: "1.0"` in `governance-policy.json → synthesis.critique_schema_version`. Fields: `schema_version`, `failure_type`, `evidence_id`, `location`, `normalized_message`, `redacted: bool`.

> [!NOTE]
> **DEC-NS-003:** `SynthesisStrategy` as Protocol vs ABC. Protocol allows structural subtyping; ABC enforces registration. Given the governance context (fail-closed), ABC is preferred so unregistered strategies cannot accidentally satisfy the interface. Resolve before Milestone 5.
