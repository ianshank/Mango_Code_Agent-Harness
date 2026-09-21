# Design: MG-E1 Backend Adapter Pack

## Decision

Land additive SWE-ReX and OpenSandbox `ExecutionBackend` adapters behind policy-selected `backend_id`, with fail-closed isolation grading and R-AEI-10 evidence checks. Do not change the ProcessBackend default.

## Architecture pointer

Bindings and deployment-class tables live in `docs/architecture/mg-e1-swe-rex-opensandbox.md` sections 2–7 and 10. This design restates Critic pins only; implementers follow that architecture file for API citations and mapping tables.

## Critic pins (binding)

### 1. `backend_id` protected policy + registry

- Allowed ids (e.g. `process`, `swe-rex`, `opensandbox`) live on a protected governance path.
- Unknown or unregistered id => deny (`BROKER_BLOCKED` / equivalent). No invent-on-read.
- Selecting an adapter does not enlarge role tool allowlists; Mango policy remains SoT.

### 2. Docker SWE-ReX never always-enforced

- `LocalRuntime` / host deployments => `filesystem_isolation=unenforced`.
- Containerized / remote deployments => `enforced` only after deployment-class mapping **and** successful live probe (`is_alive` / equivalent). Probe failure or unknown class => `undetermined`.
- If policy requires `enforced` and capability is not `enforced` => deny (`BROKER_BLOCKED`). No silent downgrade to ProcessBackend.

### 3. Single sync/async bridge (`SweRexBackend`)

- Broker remains synchronous. Exactly one bridge owns event-loop / async handoff for SWE-ReX `AbstractRuntime.execute` (and session path when needed).
- Do not scatter `asyncio.run` / nested-loop helpers across call sites.

### 4. R-AEI-10 evidence cross-links

- Evidence / attestation that claims filesystem isolation MUST record `capabilities().filesystem_isolation == enforced` for the backend that ran the command.
- Verification tests MUST reject `available()==True`-only isolation claims (mutation proofs).
- ProcessBackend path may record containment facts; MUST NOT claim isolation.

### 5. OpenSandbox grading

- Prefer `POST /v1/isolated/session` (+ run/delete) when policy asks for enforced; probe `GET /v1/isolated/capabilities` first.
- Non-isolated `/session` / `/command` => `unenforced` only.
- No silent fallback when isolation is unavailable.

## Component sketch

```text
ExecutionBroker (preserved)
  -> policy selects backend_id from registry
  -> ProcessBackend (default) | SweRexBackend | OpenSandboxBackend
  -> BackendCapabilities.filesystem_isolation
  -> EvidenceBuilder (R-AEI-10)
```

## Out of scope

MG-E2 native differentials, MG-E3 network profiles, MG-E4 packs, license rework, external-agent control authority.

## Failure modes (fail-closed)

| Condition | Behaviour |
|---|---|
| Unknown `backend_id` | Deny |
| `available()` false / probe raises | Deny; no host fallback |
| Required enforced + unenforced/undetermined | Deny (`BROKER_BLOCKED`) |
| Evidence isolation claim without enforced capability | Refuse / fail verification |
| Shadow agent proposes backend switch | Observation only; ignored for control |
