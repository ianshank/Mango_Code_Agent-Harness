# MG-E1 Architecture: SWE-ReX + OpenSandbox Adapter Pack

> **Package:** Mango soft-P1 / MG-E1
> **Scope:** Additive `ExecutionBackend` adapters for SWE-ReX and OpenSandbox only.
> **Audience:** Critic design gate, then Implementer handoff.
> **Status:** Draft for Critic. Not an implementation license.
> **Related:** `harness/CONTRACT.md` (INV-8, INV-9, INV-13, INV-16),
> `docs/specs/agent-containment.md` (R-AC-11, R-AC-12),
> `docs/decisions/DEC-010.md` (containment vs isolation),
> `NEXT_STEPS.md` parked item `AC-CE-1`.

This document binds Critic and Implementer for MG-E1. It does not change the
live default execution path. It describes how two external runtimes plug into
the existing `ExecutionBroker` as optional backends, how isolation claims are
graded, and what evidence may assert.

No hardcoded secrets, API keys, or model identifiers appear in this design.
Credential names stay in existing policy and redaction config.

---

## 1. Problem and intent

Today `ExecutionBroker` always constructs a `ProcessBackend` when no backend is
injected (`harness/shared/governance/broker.py`). That backend pins cwd, bounds
runtime, caps output, and filters credential env vars. Per DEC-010 and
CONTRACT INV-13, that is **containment, not isolation**: it does not confine
the filesystem or the network, and no result produced on that path may claim a
sandbox digest.

MG-E1 introduces optional adapters so a **policy-selected** backend can provide
enforced filesystem isolation when the deployment class actually provides it.
The default remains `ProcessBackend`. Soft-P1 packaging for this milestone is
the adapter pack only: SWE-ReX and OpenSandbox. Distilled, Neuroharness, and
FORGE are out of scope.

---

## 2. Critic-binding constraints (must hold)

1. **Preserve `ExecutionBroker`.** Additive `ExecutionBackend` implementations
   and additive `BackendCapabilities` fields only. Do not rewrite broker
   authority, PreToolUse, or policy decision point behaviour for MG-E1.
2. **`ProcessBackend` default UNCHANGED.** Constructor form
   `ExecutionBroker()` continues to use `ProcessBackend()`. Policy may select
   another backend; absence of selection is never reinterpreted as a sandbox.
3. **Isolation claims fail closed.** A claim of `filesystem_isolation=enforced`
   without evidence that `capabilities().filesystem_isolation == enforced` is a
   denial (R-AEI-10). Undetermined or unenforced never upgrades to enforced by
   inference.
4. **Evidence asserts capabilities, not availability.** Manifests and
   attestations that claim isolation MUST record
   `capabilities().filesystem_isolation == enforced`. They MUST NOT treat
   `backend.available()` as isolation proof. Availability is liveness only.
5. **Map isolation from deployment class.** Adapters derive
   `filesystem_isolation` as `enforced | unenforced | undetermined` from the
   concrete deployment / session class in use, not from marketing labels or
   from "the SDK imported cleanly".
6. **Shadow external agents are observation-only.** Any external agent or
   planner wired beside Mango remains INV-16 observation mode: empty tool
   schema, no control authority. Mango policy stays source of truth (SoT).
7. **License work is not in MG-E1.** E0 license / compliance packaging is
   treated as done. This doc does not reopen it.

---

## 3. Agent / component map

```text
                    +---------------------------+
                    |  Mango MAS Orchestrator   |
                    |  (tool dispatch, roles)   |
                    +-------------+-------------+
                                  |
                                  | run_command / authorize_*
                                  v
                    +---------------------------+
                    |     ExecutionBroker       |  <-- PRESERVED (INV-8)
                    |  policy_decision.decide   |
                    |  pretooluse_guard.check   |
                    +-------------+-------------+
                                  |
                    policy selects ExecutionBackend
                                  |
          +-----------------------+------------------------+
          |                       |                        |
          v                       v                        v
 +----------------+    +--------------------+    +----------------------+
 | ProcessBackend |    | SweRexBackend      |    | OpenSandboxBackend   |
 | DEFAULT        |    | (MG-E1 additive)   |    | (MG-E1 additive)     |
 | containment    |    | AbstractRuntime    |    | execd /v1/isolated   |
 | cwd/timeout/cap|    | execute + session  |    | or non-isolated API  |
 +----------------+    +--------------------+    +----------------------+
          |                       |                        |
          +-----------+-----------+------------------------+
                      |
                      v
           BackendCapabilities.filesystem_isolation
             enforced | unenforced | undetermined
                      |
                      v
              EvidenceBuilder / attestation
              (R-AEI-10: assert enforced only)
```

### 3.1 Preserved components

| Component | Role in MG-E1 |
|---|---|
| `ExecutionBroker` | Sole governed execution entry (INV-8). Still runs classify, PreToolUse, policy decide, then `backend.run(...)`. |
| `ProcessBackend` | Default backend. Unchanged behaviour and default construction. |
| `pretooluse_guard` | Host-side dangerous-command fast path. Unchanged in MG-E1. |
| `policy_decision` | Authority model SoT. Unchanged. |
| `EvidenceBuilder` | Gains additive capability fields in evidence payloads; signing rules unchanged. |
| Shadow planner / external cognitive producers | Observation-only (INV-16). No backend selection authority. |

### 3.2 New components (MG-E1)

| Component | Responsibility |
|---|---|
| `ExecutionBackend` (protocol / ABC) | Common seam: `name`, `version`, `available()`, `capabilities()`, `run(...)`. `ProcessBackend` conforms without behaviour change. |
| `BackendCapabilities` (frozen dataclass) | Additive capability report. MG-E1 introduces `filesystem_isolation` enum (below). Further fields may be added later without removing this one. |
| `SweRexBackend` | Adapter over SWE-ReX `AbstractRuntime` (see section 5). |
| `OpenSandboxBackend` | Adapter over OpenSandbox execd isolated and non-isolated session APIs (see section 6). |
| Backend registry / policy key | Policy-selected backend id (e.g. `process`, `swe-rex`, `opensandbox`). Illegal or unknown id denies (fail closed). |

### 3.3 Out-of-scope stubs (agent map only)

Named so Critic can see package boundaries. No design depth in MG-E1:

| Milestone | Stub only |
|---|---|
| MG-E2 | Differentials against PreToolUse / `block_dangerous` native families. Native host guards stay authoritative for those shapes; adapters do not replace them. |
| MG-E3 | Additional isolation profiles (network, landlock depth, etc.) beyond filesystem enum. |
| MG-E4 | Distilled / Neuroharness / FORGE packaging. |

---

## 4. `ExecutionBackend` and `BackendCapabilities`

### 4.1 Protocol (additive)

Implementers introduce a typing seam that `ProcessBackend` already satisfies in
spirit. Suggested shape (names may match repo style; behaviour is binding):

```text
ExecutionBackend:
  name: str
  version: str
  available() -> bool
  capabilities() -> BackendCapabilities
  run(command, cwd, timeout, max_output_bytes) -> ExecutionResult
```

`ExecutionBroker` typing widens from `ProcessBackend | None` to
`ExecutionBackend | None` with default still `ProcessBackend()`. No change to
`execute_command` policy / guard ordering.

### 4.2 `filesystem_isolation` enum

| Value | Meaning | When to report |
|---|---|---|
| `enforced` | Filesystem confinement is actively enforced by the selected deployment / session class, and the adapter verified the enforcement surface for this run. | Only when deployment class mapping + live probe both support it. |
| `unenforced` | Backend runs commands without FS isolation (containment or weaker). | `ProcessBackend`; SWE-ReX local non-container runtimes; OpenSandbox non-isolated `/session` paths. |
| `undetermined` | Adapter cannot honestly grade isolation (probe failed, unknown deployment class, mixed mode, missing capability endpoint). | Default when uncertain. Fail-closed for any `enforced` claim. |

### 4.3 Deployment-class mapping (binding)

Adapters MUST map from concrete class / mode, not from product name:

| Backend | Deployment / mode | `filesystem_isolation` |
|---|---|---|
| `ProcessBackend` | Host `bash -c` subprocess | `unenforced` |
| `SweRexBackend` | `LocalRuntime` / `LocalDeployment` (host) | `unenforced` |
| `SweRexBackend` | Containerized / remote deployment where the runtime executes inside an isolating boundary the adapter can attest (e.g. Docker-backed `RemoteRuntime`) | **Never auto-`enforced` from Docker alone.** `enforced` only after successful alive + deployment-class attestation probe; else `undetermined` |
| `SweRexBackend` | Unknown or custom deployment | `undetermined` |
| `OpenSandboxBackend` | `POST /v1/isolated/session` with isolation capabilities available (`GET /v1/isolated/capabilities` reports usable isolation) | `enforced` when session create + capability probe succeed; else `undetermined` |
| `OpenSandboxBackend` | Non-isolated session / command APIs | `unenforced` |
| Either adapter | `available() == false` or probe error | `undetermined` (and broker already denies unavailable backends per INV-9) |

**Fail-closed rule:** if policy or caller requests `enforced` and
`capabilities().filesystem_isolation != enforced`, the broker returns
`BROKER_BLOCKED` (or equivalent denial). No silent downgrade to host
`ProcessBackend`.

### 4.4 Tool / backend allowlists

- Backend ids permitted for a deployment are declared in governance policy
  (protected path). Unknown id -> deny.
- Role tool allowlists (`agent-policy.json`, `agent_authority`) stay SoT for
  which tools may be offered. Selecting `swe-rex` or `opensandbox` does not
  enlarge role actions.
- Credential env filtering remains on every backend path (parity with
  `ProcessBackend`).
- Adapters do not bypass PreToolUse or `authorize_action`. Broker still calls
  them before `run`.

### 4.5 Capability fields: additive only

MG-E1 adds `filesystem_isolation`. Do not remove or reinterpret existing
containment fields. Future milestones may add e.g. `network_isolation` without
breaking MG-E1 consumers.

---

## 5. SWE-ReX adapter (`SweRexBackend`)

### 5.1 External API citation

SWE-ReX entry point is `swerex.runtime.abstract.AbstractRuntime`
([docs](https://swe-rex.com/latest/api/runtimes/abstract/)). Binding methods for
MG-E1:

| Method | Role in adapter |
|---|---|
| `async execute(command: Command) -> CommandResponse` | One-off command, analogous to `subprocess.run`. Primary mapping for broker `run()`. |
| `async create_session(request: CreateSessionRequest) -> CreateSessionResponse` | Open a persistent shell session when a multi-step tool sequence needs shared env state. |
| `async run_in_session(action: Action) -> Observation` | Run inside an existing session (e.g. `BashAction`). |
| `async close_session(...)` / `async close()` | Lifecycle cleanup; must run on broker teardown / failure paths. |
| `async is_alive(...)` | Feeds `available()`; never feeds isolation evidence. |

Deployments (`LocalDeployment`, Docker / remote deployments, etc.) produce a
runtime. The adapter records the **deployment class name** used to start the
runtime and uses section 4.3 to grade `filesystem_isolation`.

### 5.2 Sync broker bridge

`ExecutionBroker` is synchronous today. `SweRexBackend.run` owns the async
bridge (dedicated loop or existing project pattern) and normalises
`CommandResponse` / session `Observation` into `ExecutionResult`
(`status`, `stdout`, `stderr`, `exit_code`, `reason`, `action`). Timeouts map
to existing broker timeout semantics; overflow still capped by
`max_output_bytes`.

### 5.3 What SWE-ReX must not do in MG-E1

- Must not become default backend.
- Must not claim `enforced` for `LocalRuntime` / host deployments.
- Must not skip Mango PreToolUse or policy decide.
- Must not embed model IDs, API keys, or SWE-bench dataset credentials in
  source; configuration is env / policy references only.

---

## 6. OpenSandbox adapter (`OpenSandboxBackend`)

### 6.1 External API surface

OpenSandbox execd exposes command and session execution, plus isolated
sessions under `/v1/isolated/*` (bubblewrap namespaces; see OpenSandbox
isolation-session guides and OSEP-0013). Binding points for MG-E1:

| Surface | Role |
|---|---|
| `GET /v1/isolated/capabilities` | Probe whether isolated execution is actually available. Failures => `undetermined` / unavailable. |
| `POST /v1/isolated/session` | Create isolated bash session when policy requests enforced FS isolation. |
| `POST /v1/isolated/session/{id}/run` | Execute within isolated session (SSE or foreground complete). |
| `DELETE /v1/isolated/session/{id}` | Destroy session; required on success and failure cleanup. |
| Non-isolated `/session`, `/command` | Allowed only when policy accepts `unenforced`; must not be reported as `enforced`. |
| Session filesystem proxy under `/v1/isolated/session/{id}/files/*` | Optional for artifact staging; still subject to Mango write policy when reflecting into the workspace. |

SDK does not silently fall back when isolation is unavailable (OpenSandbox
guidance). Mango mirrors that: no silent fall back to `ProcessBackend`.

### 6.2 Grading rules

- Isolated session path + successful capabilities probe => may report
  `enforced`.
- Capabilities `available: false`, missing bwrap / namespace support, or create
  failure => do not report `enforced`; broker denies if policy required it.
- Non-isolated APIs => `unenforced`.

### 6.3 What OpenSandbox must not do in MG-E1

- Must not become default backend.
- Must not treat lifecycle "sandbox created" alone as FS isolation evidence.
- Must not grant external OpenSandbox agents write authority into Mango control
  plane paths.

---

## 7. Evidence and R-AEI-10

### 7.1 Requirement

**R-AEI-10:** Any evidence record, attestation, or digest that claims filesystem
isolation for a run MUST assert
`capabilities().filesystem_isolation == enforced` for the backend that executed
the command. Citing `backend.available() == True`, deployment marketing names,
or "adapter imported" is non-conforming and MUST fail verification.

### 7.2 Failure modes (fail-closed)

| Condition | Required behaviour |
|---|---|
| Policy selects backend id unknown to registry | Deny (`BROKER_BLOCKED`). |
| Selected backend `available()` false / probe raises | Deny (INV-9). No host fallback. |
| Policy requires `enforced` but capabilities report `unenforced` or `undetermined` | Deny. |
| Evidence builder asked to mark isolation without `enforced` capability | Refuse to emit isolation claim; fail export / attestation for that claim. |
| Adapter cannot map deployment class | Report `undetermined`; deny if enforced required. |
| Shadow / external agent proposes backend switch | Ignored for control. Observation channel only (INV-16). |
| SWE-ReX / OpenSandbox SDK raises mid-run | Map to `BROKER_FAILED` with reason; cleanup sessions; no partial isolation claim. |

### 7.3 What evidence may still say on `ProcessBackend`

Containment facts (cwd pin, timeout, output cap, credential filter) may be
recorded. Isolation MUST NOT be claimed. INV-13 remains unsatisfiable on that
path until an `enforced` backend is selected and attested.

---

## 8. Non-goals (MG-E1)

- Changing `ProcessBackend` default or making sandboxes mandatory on CI runners
  that cannot exercise isolation primitives.
- Replacing PreToolUse / dangerous-command natives (MG-E2 differential scope).
- Network isolation profiles, landlock depth tooling, or full INV-13 sandbox
  digest finalisation beyond the filesystem capability field (MG-E3+).
- Distilled, Neuroharness, FORGE, or other soft-P1 packs beyond this adapter
  pair (MG-E4).
- License / compliance rework (E0 done).
- Letting external agents become SoT for policy or backend selection.
- Hardcoding secrets, endpoints with embedded credentials, or model IDs in
  adapter code or this document.
- Silent fallback from an unavailable isolating backend to host process
  execution.

---

## 9. Boundary note: MG-E2 (out of scope, pinned)

MG-E2 will differential-test adapter behaviour against the existing PreToolUse
and dangerous-command native families (`pretooluse_guard`, CONTRACT native
guards). Until then:

- Natives remain on the broker path for every backend.
- Adapters MUST NOT weaken or short-circuit those checks.
- Critic should reject MG-E1 designs that move dangerous-command authority into
  the external runtime.

---

## 10. Handoff pins for Implementer

1. Land `ExecutionBackend` + `BackendCapabilities` beside
   `harness/shared/governance/process_backend.py` (or split modules if size
   budget requires). Keep `ProcessBackend` public exports stable.
2. Widen `ExecutionBroker` backend parameter type only; default construction
   remains `ProcessBackend()`.
3. Implement `SweRexBackend` against `AbstractRuntime.execute` for one-shot
   `run`, with optional session path via `create_session` /
   `run_in_session` when a single brokered command needs session semantics.
   Record deployment class for capability grading.
4. Implement `OpenSandboxBackend` preferring `/v1/isolated/*` when policy asks
   for `enforced`; probe `GET /v1/isolated/capabilities` first.
5. Wire policy key for backend selection (protected path). Unknown / missing
   required isolation => deny.
6. Extend evidence / attestation to carry `filesystem_isolation` and enforce
   R-AEI-10 in verification tests (mutation proofs on false `enforced` claims).
7. Tests required before merge:
   - Default broker path unchanged (existing process-backend suites green).
   - Capability mapping table cases (enforced / unenforced / undetermined).
   - Fail-closed: required enforced + undetermined => blocked.
   - Evidence rejects `available()`-only isolation claims.
   - No secret / model-id literals in new modules (secret-scan clean).
8. Do not implement MG-E2 native differentials, MG-E3 network profiles, or
   MG-E4 packs in the same PR train without a new architecture gate.
9. Optional deps for SWE-ReX / OpenSandbox SDKs stay extras; core harness
   installs and CI without them continue to use `ProcessBackend` only.
10. Update CONTRACT / DEC only when behaviour lands; this architecture file is
    not a substitute for DEC-024-grade evidence.

---

## 11. Validation expectations (design gate)

Critic should confirm:

- [ ] Broker preserved; default still `ProcessBackend`.
- [ ] Only additive backend + capability surface.
- [ ] R-AEI-10 wording present and fail-closed.
- [ ] SWE-ReX `AbstractRuntime` execute/session APIs cited.
- [ ] OpenSandbox isolated vs non-isolated grading explicit.
- [ ] Shadow agents observation-only; Mango policy SoT.
- [ ] MG-E2/E3/E4 and E0 license called out as non-goals / stubs.
- [ ] No Distilled / Neuroharness / FORGE scope creep.
- [ ] No emojis, no hardcoded secrets or model IDs.

---


---

## 11a. Critic DESIGN SHIP bindings (2026-09-21)

Critic DESIGN SHIP on PR #142 sealed the soft gaps as **bindings** (not HOLD). Implementer and Spec Writer treat these as normative:

| Binding | Rule |
|---|---|
| **backend_id policy** | Backend selection is a protected policy key (registry of allowlisted ids such as `process`, `swe-rex`, `opensandbox`). Unknown or disallowed `backend_id` denies fail-closed. Absence of selection keeps `ProcessBackend` default; never reinterpret absence as a sandbox. |
| **Docker never always-enforced** | Presence of Docker / container tooling is not evidence. `filesystem_isolation=enforced` requires deployment-class mapping **and** a successful live attestation probe for that run. Otherwise report `undetermined` (or `unenforced` for known host classes). |
| **Single sync/async bridge** | Exactly one bridge owns async SWE-ReX / OpenSandbox SDK calls inside the sync `ExecutionBroker` path (adapter-owned loop or the repo's existing async bridge helper). Do not invent a second concurrent bridge pattern in MG-E1. |
| **R-AEI-10 cross-links** | When code lands, evidence / CONTRACT / INV docs cross-link R-AEI-10: assert `capabilities().filesystem_isolation == enforced`; never `backend.available()`. Architecture alone is not a substitute for DEC-grade evidence, but Implementer PRs must land the cross-links with behaviour. |

These bindings supersede any softer "gap" wording earlier in this file.

## 12. Document control

| Field | Value |
|---|---|
| Path | `docs/architecture/mg-e1-swe-rex-opensandbox.md` |
| Package | soft-P1 / MG-E1 |
| Supersedes | None (new). Relates to DEC-010, AC-CE-1 parked item. |
| Next | Critic DESIGN SHIP (bindings in §11a). Spec Writer OpenSpec + Implementer PRs for protocol + adapters. |
