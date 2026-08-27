# Spec: Governance Control Plane

> **Change:** `add-neurosym-governed-synthesis`
> **Version:** 1.0.0-draft
> **Authors:** Architect · SQE Lead
> **Status:** DRAFT

---

## Problem Statement

The existing `ExecutionBroker` enforces INV-8 (pretooluse_guard) and INV-9 (no host fallback), but it does not issue a structured `PolicyDecision` record. Synthesis candidates can enter the execution path without a verifiable, evidence-linked verdict. **Evidence:** `governance/broker.py` returns `ExecutionResult` but produces no `policy_bundle_digest`, `candidate_digest`, or `evidence_id` — making it impossible for a reviewer to trace which policy evaluated a given candidate. `EvidenceBuilder.export()` similarly does not capture these fields.

---

## Acceptance Criteria

- [ ] **AC-GCP-1:** `GovernanceControlPlane.evaluate(candidate)` returns a `PolicyDecision` containing `verdict`, `policy_bundle_digest`, `candidate_digest`, `timestamp`, and `evidence_id` for every call. No field may be empty or `None`.
  _Verified by:_ `pytest -k test_evaluate_returns_complete_policy_decision` · stage: `make test-governance`

- [ ] **AC-GCP-2:** A candidate whose AST contains a prohibited import (as listed in `governance-policy.json → synthesis.prohibited_imports`) receives `verdict="DENY"`. The `ExecutionBroker` MUST NOT be called for that candidate.
  _Verified by:_ `pytest -k test_policy_denies_prohibited_import` · stage: `make test-governance`

- [ ] **AC-GCP-3:** `PolicyDecision.verdict` is deterministic: evaluating the same `(candidate_digest, policy_bundle_digest)` pair twice returns identical verdicts. The control plane is stateless with respect to verdict computation.
  _Verified by:_ `pytest -k test_verdict_is_deterministic` · stage: `make test-governance`

- [ ] **AC-GCP-4:** `EvidenceBuilder.export()` output includes `policy_bundle_digest` and `candidate_digest` when a synthesis session is active. Existing callers without these fields receive a deprecation warning (not an error) at export time.
  _Verified by:_ `pytest -k test_evidence_includes_policy_and_candidate_digests` · stage: `make test-governance`

- [ ] **AC-GCP-5:** A reviewer given only the `evidence_id` from a DENY verdict can retrieve the exact `policy_bundle_digest` and `candidate_digest` that produced it. This does not require access to the synthesis runtime.
  _Verified by:_ `pytest -k test_evidence_id_is_sufficient_for_reviewer_reconstruction` · stage: `make test-governance`

- [ ] **AC-GCP-6:** `make ci` passes on all 4 Python matrix versions.
  _Verified by:_ CI matrix · stage: `make ci`

---

## Invariants Touched

- **INV-6** (external root of trust): `policy_bundle_digest` is derived from the externally-committed bundle in `harness/control-plane/policy-bundle.example.json`. The control plane cannot self-issue a digest. Verified by: AC-GCP-1, `make digest-regen`.
- **INV-7** (bounded delegation with evidence): Every `PolicyDecision` includes `evidence_id` linking actor, policy, and candidate. Verified by: AC-GCP-1.
- **INV-9** (deterministic verdict before execution): `GovernanceControlPlane.evaluate()` is invoked and returns before `ExecutionBroker.execute()` is called. Verified by: AC-GCP-2.
- **INV-10** (DENY is terminal): A DENY verdict with a given `candidate_digest` is cached and returned immediately for any re-submission of the same digest. Verified by: `pytest -k test_deny_cached_for_same_digest`.
- **INV-13** (verified result digests): `PolicyDecision` carries `policy_bundle_digest`; `SynthesisResult` carries `policy`, `test`, `sandbox`, `source`, and `tool_version` digests. Verified by: AC-GCP-4, AC-GCP-5.

---

## Validation Matrix

| Stage | Make Target | Pass Criteria |
|-------|-------------|---------------|
| Governance tests | `make test-governance` | AC-GCP-1..5 pass |
| Coverage | `make coverage-python` | `governance/` package ≥ `coverage.lines` |
| Digest sync | `make digest-regen` | Bundle digest consistent after any policy change |
| Full CI | `make ci` | All above on 4 Python versions |

---

## Backward Compatibility

- `ExecutionBroker.execute_command()` signature is unchanged. The new `GovernanceControlPlane` wraps it; existing callers of `execute_command()` directly are unaffected but receive no `PolicyDecision`.
- `EvidenceBuilder` gains `candidate_digest: str | None = None` and `policy_bundle_digest: str | None = None`. Existing construction `EvidenceBuilder(project_root=p, signing_key=k)` continues to work.
- `governance-policy.json` gains `synthesis.prohibited_imports: list[str]` and `synthesis.max_repair_cycles: int`. Existing readers that do not access `synthesis` key are unaffected.

---

## Open Questions

> [!IMPORTANT]
> **DEC-GCP-001 (BLOCKING):** Where is the DENY cache persisted? Options: (a) in-memory per synthesis session (no cross-session protection), (b) append-only file under `harness/control-plane/evidence/` (persistent, protected). Option (b) is preferred for INV-10 compliance but requires write-protection policy. Resolve before Milestone 1 gate.

> [!NOTE]
> **DEC-GCP-002:** Should `policy_bundle_digest` be SHA-256 of the raw JSON or of a canonical serialization? Canonical serialization (sorted keys, no whitespace) is recommended for determinism. Align with `EvidenceBuilder.export()` which already uses `json.dumps(data, sort_keys=True)`.
