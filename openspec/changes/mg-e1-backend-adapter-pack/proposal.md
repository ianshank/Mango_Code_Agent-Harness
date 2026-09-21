# Change: MG-E1 Backend Adapter Pack (`mg-e1-backend-adapter-pack`)

> **Status: proposed.** Critic DESIGN SHIP on architecture PR #142; Conductor specify unlock.
> Architecture SoT: `docs/architecture/mg-e1-swe-rex-opensandbox.md`.
> Soft-P1 packaging: SWE-ReX + OpenSandbox adapters only.

## Why

`ExecutionBroker` still defaults to `ProcessBackend` (containment, not isolation). Soft-P1 needs optional, policy-selected backends that can honestly report `filesystem_isolation` as `enforced | unenforced | undetermined`, with evidence asserting R-AEI-10 (`capabilities().filesystem_isolation == enforced`), never `backend.available()`.

MG-E0 (MIT) is closed. This change specifies the additive adapter pack and Critic bindings so Implementer can land code without restating E2–E4 or changing the ProcessBackend default.

## What Changes

OpenSpec package under `openspec/changes/mg-e1-backend-adapter-pack/` that binds:

1. **Preserve `ExecutionBroker`.** Additive `ExecutionBackend` + `BackendCapabilities` only.
2. **`ProcessBackend` default UNCHANGED.** `ExecutionBroker()` still constructs `ProcessBackend()`.
3. **`backend_id` protected policy + registry.** Unknown id denies (fail closed). No silent host fallback.
4. **`SweRexBackend`** over SWE-ReX `AbstractRuntime` (`execute` / session APIs). Single sync/async bridge owned by the adapter. Docker / remote deployments MUST NOT hardcode `filesystem_isolation=enforced`; grade via deployment-class mapping + live probe; else `undetermined`. Required-enforced mismatch => `BROKER_BLOCKED` (or equivalent deny).
5. **`OpenSandboxBackend`** preferring `/v1/isolated/*` when policy requires enforced; probe `GET /v1/isolated/capabilities` first. Non-isolated APIs report `unenforced` only.
6. **R-AEI-10 evidence tests.** Isolation claims in evidence/attestation MUST assert `capabilities().filesystem_isolation == enforced`; `available()`-only claims fail verification.
7. Optional SDK deps as extras; core CI without them still uses `ProcessBackend` only.

## Non-Goals

- No ProcessBackend default switch.
- No MG-E2 PreToolUse / `block_dangerous` differentials (natives stay on every backend path).
- No MG-E3 network / landlock depth profiles.
- No MG-E4 Distilled / Neuroharness / FORGE packaging.
- No shadow external agents leaving observation-only (INV-16).
- No silent fallback from an unavailable isolating backend to host process.
- No hardcoded secrets, endpoints with credentials, or model IDs.

## Critic bindings (must appear in design + specs)

| Binding | Rule |
|---|---|
| `backend_id` | Protected policy + registry; deny unknown |
| Docker SWE-ReX | Never `always=enforced`; probe + fail-closed `BROKER_BLOCKED` |
| `SweRexBackend` | Single sync/async bridge |
| R-AEI-10 | Cross-link capability field with evidence tests |
| Default | ProcessBackend unchanged; additive only |
| Scope | E2–E4 stubs not in this change id |

## Affected Capabilities

- `backend-adapter-pack`

## Architecture citation

- `docs/architecture/mg-e1-swe-rex-opensandbox.md` (PR #142 / design gate SHIP)
- CONTRACT INV-8, INV-9, INV-13, INV-16; R-AEI-10; DEC-010
