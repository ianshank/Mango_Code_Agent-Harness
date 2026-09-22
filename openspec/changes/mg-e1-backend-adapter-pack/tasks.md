# Tasks: MG-E1 Backend Adapter Pack

## Milestone 1 — Protocol seam (additive)  [TODO]

- [ ] 1. Introduce `ExecutionBackend` + `BackendCapabilities` (`filesystem_isolation`: `enforced | unenforced | undetermined`) beside ProcessBackend; keep ProcessBackend exports stable.
- [ ] 2. Widen `ExecutionBroker` backend parameter type to `ExecutionBackend | None`; default construction remains `ProcessBackend()`.
- [ ] 3. Add protected policy/registry for `backend_id`; unknown id denies.

- **Gate:** Existing process-backend suites green; default broker path unchanged; unknown id test denies.

## Milestone 2 — SweRexBackend  [TODO]

- [ ] 4. Implement `SweRexBackend` against SWE-ReX `AbstractRuntime.execute` (optional session via create/run/close).
- [ ] 5. Single sync/async bridge owned by the adapter.
- [ ] 6. Deployment-class mapping + probe: Docker/remote never hardcodes `enforced`; fail-closed `BROKER_BLOCKED` when required enforced mismatches.
- [ ] 7. Optional SWE-ReX extra; core install without SDK still defaults to ProcessBackend.

- **Gate:** Mapping table tests (enforced / unenforced / undetermined); required-enforced deny; no default switch.

## Milestone 3 — OpenSandboxBackend  [TODO]

- [ ] 8. Implement `OpenSandboxBackend` with capabilities probe + isolated session path when policy requires enforced.
- [ ] 9. Non-isolated APIs report `unenforced` only; no silent ProcessBackend fallback.
- [ ] 10. Optional OpenSandbox extra.

- **Gate:** Isolated probe success/fail cases; non-isolated never reports enforced.

## Milestone 4 — R-AEI-10 evidence  [TODO]

- [ ] 11. Carry `filesystem_isolation` in evidence/attestation payloads.
- [ ] 12. Verification tests reject `available()`-only isolation claims; cross-link R-AEI-10.
- [ ] 13. Secret-scan clean on new modules (no model ids / credentials).

- **Gate:** Mutation proofs green; ProcessBackend path cannot claim isolation.

## Milestone 5 — Scope fence  [TODO]

- [ ] 14. Confirm no MG-E2/E3/E4 implementation in this change id (stubs/docs references only if architecture already names them).
- [ ] 15. Archive this OpenSpec change after Implementer green + Critic/Conductor clear.

- **Gate:** Diff contains no E2 classifier differentials, no E3 network profiles, no Distilled/Neuroharness/FORGE packs.
