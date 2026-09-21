# Spec delta: execution-backend (MG-E1)

## ADDED Requirements

### Requirement: Policy-selected backend registry
The system SHALL resolve `execution_backend.backend_id` from protected governance policy and SHALL deny unknown ids. Agents and environment variables SHALL NOT select backends.

### Requirement: R-AEI-10 isolation evidence
Isolation claims SHALL assert `capabilities().filesystem_isolation == enforced` and MUST NOT treat `available()` as isolation proof.

### Requirement: SWE-ReX docker grading
Docker-class SWE-ReX deployments SHALL report `undetermined` until a live probe succeeds; they MUST NOT always report `enforced`.
