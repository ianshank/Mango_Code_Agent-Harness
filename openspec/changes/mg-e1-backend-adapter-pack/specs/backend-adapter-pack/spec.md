# Capability: Backend Adapter Pack

## ADDED Requirements

### Requirement: Additive backends preserve broker and default

The harness SHALL keep `ExecutionBroker` as the governed execution entry and SHALL keep `ProcessBackend` as the constructed default when no backend is selected.

#### Scenario: Default construction unchanged

- **WHEN** `ExecutionBroker()` is constructed without an injected backend
- **THEN** the backend in use is `ProcessBackend`
- **AND** MG-E1 adapter modules do not alter that default

#### Scenario: Additive seam only

- **WHEN** MG-E1 lands
- **THEN** `ExecutionBackend` and `BackendCapabilities` exist as additive surfaces
- **AND** PreToolUse / policy decide still run before every `backend.run`

### Requirement: Protected backend_id registry

Backend selection SHALL use a protected policy registry of known `backend_id` values.

#### Scenario: Unknown backend_id denied

- **WHEN** policy or caller selects a `backend_id` absent from the registry
- **THEN** the broker denies execution (fail closed)
- **AND** does not fall back to `ProcessBackend`

### Requirement: Fail-closed filesystem isolation grading

Adapters SHALL report `filesystem_isolation` as `enforced`, `unenforced`, or `undetermined` from deployment class plus live probe, never from availability alone.

#### Scenario: Docker SWE-ReX is not always enforced

- **WHEN** `SweRexBackend` runs on a containerized or remote deployment
- **THEN** it reports `enforced` only after deployment-class mapping and a successful live probe
- **AND** otherwise reports `undetermined` (or `unenforced` for host/local class)

#### Scenario: Required enforced mismatch blocks

- **WHEN** policy requires `filesystem_isolation=enforced`
- **AND** `capabilities().filesystem_isolation` is not `enforced`
- **THEN** the broker returns `BROKER_BLOCKED` (or equivalent denial)
- **AND** does not silently downgrade to host process execution

#### Scenario: OpenSandbox non-isolated path

- **WHEN** `OpenSandboxBackend` uses non-isolated session or command APIs
- **THEN** `filesystem_isolation` is `unenforced`
- **AND** evidence MUST NOT claim isolation for that run

### Requirement: Single SweRex sync/async bridge

`SweRexBackend` SHALL own exactly one sync-to-async bridge for SWE-ReX runtime calls.

#### Scenario: One bridge

- **WHEN** broker invokes `SweRexBackend.run`
- **THEN** async handoff goes through the adapter's single bridge
- **AND** call sites do not each open nested event loops

### Requirement: R-AEI-10 evidence honesty

Isolation claims in evidence or attestation SHALL assert `capabilities().filesystem_isolation == enforced` for the executing backend.

#### Scenario: available() is not isolation proof

- **WHEN** verification runs against an evidence record that claims filesystem isolation
- **AND** the record only proves `backend.available() == true`
- **THEN** verification fails

#### Scenario: Enforced claim matches capability

- **WHEN** evidence claims filesystem isolation
- **THEN** it records `filesystem_isolation=enforced` from `capabilities()` for that run
- **AND** ProcessBackend containment evidence does not claim isolation

### Requirement: Soft-P1 scope fence

This change id SHALL NOT implement MG-E2, MG-E3, or MG-E4 work.

#### Scenario: No E2–E4 implementation in this change

- **WHEN** the MG-E1 change package is reviewed
- **THEN** it does not replace PreToolUse / `block_dangerous` natives
- **AND** it does not add network-isolation profiles or Distilled/Neuroharness/FORGE packs under this change id
