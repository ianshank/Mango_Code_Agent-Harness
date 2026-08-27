# Spec: Code Execution Broker

> **Change:** `add-neurosym-governed-synthesis`
> **Version:** 1.0.0-draft
> **Authors:** Dev Lead · DevOps · SQE Lead
> **Status:** DRAFT

---

## Problem Statement

`harness/shared/governance/broker.py` implements `ExecutionBroker` with sandbox blocking (INV-9), but it has no versioned capability profiles, no adversarial escape coverage, and no structured `SandboxViolation` result schema. The broker passes `check_command()` as a gate but does not enforce network isolation, filesystem constraints, or output-size limits on the executed process. **Evidence:** `test_governance_broker.py` covers the gate logic but none of the in-process capability enforcement — because that enforcement does not yet exist.

---

## Acceptance Criteria

- [ ] **AC-CE-1:** When a candidate executing under the `unit-test` capability profile makes an outbound network call (socket/HTTP), the broker denies it and returns `ExecutionResult(status="BLOCKED", stderr=<SandboxViolation>)`. The host network is not contacted.
  _Verified by:_ `pytest -k test_unit_test_profile_blocks_network` · stage: `make test-neurosym`

- [ ] **AC-CE-2:** When the configured sandbox backend cannot start (mock: `BackendUnavailableError`), the broker returns `ExecutionResult(status="BLOCKED")` and does NOT attempt host-process fallback.
  _Verified by:_ `pytest -k test_blocked_when_sandbox_unavailable` · stage: `make test-governance`

- [ ] **AC-CE-3:** Every adversarial escape fixture is denied with a structured `SandboxViolation` record containing `violation_type`, `evidence_id`, and `capability_profile`. Fixtures covered: `find -delete`, `git clean -fdx`, Python `shutil.rmtree("/")`, `curl`-pipe-shell, encoded shell payloads.
  _Verified by:_ `pytest -k test_adversarial_escape_*` (parametrized) · stage: `make test-neurosym`

- [ ] **AC-CE-4:** Capability profiles are declared as versioned JSON schemas under `harness/control-plane/capability-profiles/`. Profiles: `policy-only`, `unit-test`, `build-test`, `network-isolated`, `human-approved`. Each has a `profile_version` field and a `schema_version` field.
  _Verified by:_ `pytest -k test_capability_profiles_are_valid_against_schema` · stage: `make test-governance`

- [ ] **AC-CE-5:** `ExecutionResult` includes `capability_profile_version` and `sandbox_backend_version` in every response. These appear in the evidence bundle.
  _Verified by:_ `pytest -k test_result_includes_capability_and_backend_versions` · stage: `make test-neurosym`

- [ ] **AC-CE-6:** `make ci` passes on all 4 Python matrix versions.
  _Verified by:_ CI matrix · stage: `make ci`

---

## Invariants Touched

- **INV-8** (approved execution broker): All code execution goes through `ExecutionBroker`. No direct subprocess calls outside the broker are permitted in synthesis paths. Verified by: `make check-dedup` + `pytest -k test_no_direct_subprocess_in_synthesis`.
- **INV-9** (no host-process fallback): Sandbox unavailable → BLOCKED, never direct host execution. Verified by: AC-CE-2.
- **INV-13** (verified result digests): `ExecutionResult` records `capability_profile_version` and `sandbox_backend_version`. These are included in `SynthesisResult.digests`. Verified by: AC-CE-5.

---

## Validation Matrix

| Stage | Make Target | Pass Criteria |
|-------|-------------|---------------|
| Governance tests | `make test-governance` | AC-CE-2, AC-CE-4 pass |
| Neurosym/execution tests | `make test-neurosym` | AC-CE-1, AC-CE-3, AC-CE-5 pass |
| Coverage | `make coverage-python` | `governance/broker.py` ≥ `coverage.lines` |
| Full CI | `make ci` | All above on 4 Python versions |

---

## Backward Compatibility

- `ExecutionBroker(sandbox_available: bool)` constructor signature is preserved. The new `capability_profile` parameter is optional with default `"policy-only"` so existing callers are unaffected.
- `ExecutionResult` gains `capability_profile_version: str | None` and `sandbox_backend_version: str | None`. Existing code reading `result.status`, `result.stdout`, `result.stderr`, `result.exit_code` is unaffected.
- Capability profile JSON files are additive. No existing schema is removed.

---

## Open Questions

> [!IMPORTANT]
> **DEC-CE-001 (BLOCKING):** WASM sandbox backend. `tasks.md` M3 specifies a "WASM backend proof-of-concept". WASM alone is explicitly listed as a non-goal for sufficient isolation (`proposal.md`). Decision needed: is WASM a supplementary backend (alongside a process-based sandbox like `seccomp`/`bubblewrap`) or deferred entirely? Resolve before Milestone 3 gate.

> [!NOTE]
> **DEC-CE-002:** Network interception mechanism. Options: (a) `ptrace`-based syscall filter, (b) network namespace, (c) `iptables` rules. Option (b) (network namespace via `unshare`) is portable across Linux CI and does not require root if user namespaces are enabled. Resolve before AC-CE-1 implementation.
