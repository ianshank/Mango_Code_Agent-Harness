# Architecture Decision Record — Governed Neuro-Symbolic Synthesis

> **Change:** `add-neurosym-governed-synthesis`
> **Version:** 1.0.0-draft
> **Decision log:** DEC-NS-001 (sync-first), DEC-NS-002 (critique schema), DEC-GCP-002 (canonical digest), DEC-CE-002 (network namespace)
> **Status:** DRAFT

---

## Core Decision

Use the existing `harness/control-plane/` as the authority boundary and `harness/shared/` as the implementation location. **Do not create a second, competing control plane.** The existing `ExecutionBroker` at `harness/shared/governance/broker.py` is the canonical broker — the synthesis layer wraps it, does not replace it.

---

## C4 Architecture

### Context (Level 1)

```text
┌─────────────────────────────────────────────────────────────────┐
│ Developer / CI / Agent                                          │
│   submits a SynthesisRequest (task spec + capability profile)   │
└─────────────────────────┬───────────────────────────────────────┘
                          │ SynthesisRequest
                          ▼
┌─────────────────────────────────────────────────────────────────┐
│ Mango Code Agent Harness                                        │
│  harness/shared/ — Python                                       │
│  harness/node/   — TypeScript (model client layer only)         │
└─────────────────────────────────────────────────────────────────┘
                          │ SynthesisResult + EvidenceBundle
                          ▼
┌─────────────────────────────────────────────────────────────────┐
│ External Root of Trust                                          │
│  harness/control-plane/ (policy bundles, capability profiles,   │
│  evidence store, schemas)                                       │
│  Administered independently of the governed repository.         │
└─────────────────────────────────────────────────────────────────┘
```

### Container (Level 2)

```text
SynthesisRequest
       │
       ▼
┌──────────────────────────┐
│ Governance Control Plane │  harness/shared/governance/
│  • policy_bundle_digest  │  control_plane.py (NEW)
│  • candidate_digest      │  ← wraps evidence_manifest.py
│  • ALLOW / DENY / BLOCK  │  ← reads governance-policy.json
│  • evidence_id           │
└────────┬─────────────────┘
  ALLOW only
         │
         ▼
┌──────────────────────────┐
│ Synthesis Runtime        │  harness/shared/neurosym/
│  • SingleShotStrategy    │  strategies/single_shot.py  (NEW)
│  • BoundedLatsStrategy   │  strategies/bounded_lats.py (NEW, default-off)
│  • Critique normalizer   │  critique/normalizer.py     (NEW)
│  • Repair loop (≤ budget)│  ← budget from governance-policy.json
└────────┬─────────────────┘
         │ ExecutionRequest
         ▼
┌──────────────────────────┐
│ Execution Broker         │  harness/shared/governance/broker.py (EXISTS)
│  • pretooluse_guard gate │  ← INV-8
│  • sandbox_available     │  ← INV-9 (no host fallback)
│  • capability_profile    │  capability-profiles/*.json (NEW)
│  • SandboxViolation      │
└────────┬─────────────────┘
         │ ExecutionResult
         ▼
┌──────────────────────────┐
│ Deterministic Verifiers  │  harness/shared/governance/ (EXISTS)
│  • policy bundle         │  validate_policy.py
│  • parser/type/lint/test │  validate_invariants.py
│  • secrets / SAST        │  pretooluse_guard.py
│  • mutation test (kernel)│  (mutation config NEW)
└────────┬─────────────────┘
         │ VerificationResult
         ▼
┌──────────────────────────┐
│ Evidence + Evaluation    │  harness/shared/evaluation/  (NEW)
│  • EvidenceBuilder       │  governance/evidence_manifest.py (EXISTS)
│  • OTel GenAI spans      │  evaluation/telemetry.py    (NEW)
│  • redacted replay bundle│  evaluation/replay.py       (NEW)
│  • EvaluationReport      │  evaluation/report.py       (NEW)
│  • ablation comparison   │  evaluation/ablation.py     (NEW)
└──────────────────────────┘
```

---

## Core Interfaces (Sync-First — DEC-NS-001)

> **DEC-NS-001:** Synthesis strategies are synchronous in Milestones 1–5. An `async` interface is deferred until the strategy API is stable. A `run_sync()` compatibility wrapper will be provided if an async caller needs it.

```python
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal, Protocol
from pathlib import Path


# -----------------------------------------------------------------
# Policy layer (Governance Control Plane)
# -----------------------------------------------------------------


@dataclass(frozen=True)
class PolicyDecision:
    verdict: Literal["ALLOW", "DENY", "BLOCKED"]
    policy_bundle_digest: str
    candidate_digest: str  # SHA-256 of candidate source
    timestamp: str  # ISO-8601 UTC
    evidence_id: str  # immutable; links to EvidenceBuilder record
    violations: list[dict[str, object]] = field(default_factory=list)


# -----------------------------------------------------------------
# Critique layer (DEC-NS-002: versioned critique schema)
# -----------------------------------------------------------------


@dataclass(frozen=True)
class Critique:
    schema_version: str  # from governance-policy.json → synthesis.critique_schema_version
    failure_type: Literal["policy", "parser", "compiler", "test", "sandbox", "secret"]
    evidence_id: str
    location: str | None  # file:line if applicable
    normalized_message: str  # redacted; no raw paths or secrets
    redacted: bool = True


# -----------------------------------------------------------------
# Execution layer (wraps existing ExecutionBroker)
# -----------------------------------------------------------------


@dataclass(frozen=True)
class ExecutionRequest:
    language: Literal["python", "typescript", "javascript"]
    source: str
    capability_profile: str  # references capability-profiles/<name>.json
    timeout_ms: int
    workspace_digest: str  # SHA-256 of workspace snapshot


@dataclass
class SandboxViolation:
    violation_type: str
    evidence_id: str
    capability_profile: str
    capability_profile_version: str


# -----------------------------------------------------------------
# Synthesis layer
# -----------------------------------------------------------------


@dataclass(frozen=True)
class SearchBudget:
    max_depth: int
    max_branching_factor: int
    max_inference_count: int
    max_wall_clock_ms: int
    max_cost_usd: float
    max_repair_cycles: int  # from governance-policy.json → synthesis.max_repair_cycles


@dataclass
class SynthesisRequest:
    task_spec: str
    language: Literal["python", "typescript", "javascript"]
    capability_profile: str
    budget: SearchBudget


@dataclass
class SynthesisResult:
    status: Literal["VERIFIED", "FAILED", "BLOCKED"]
    evidence_id: str
    policy_bundle_digest: str
    termination_reason: str | None = None  # "budget_exhausted", "deny_terminal", etc.
    best_candidate_summary: str | None = None
    digests: dict[str, str] = field(default_factory=dict)  # policy, test, sandbox, source, tool_versions


class SynthesisStrategy(Protocol):
    """Sync-first protocol. Async variant deferred to post-M5."""

    def synthesize(
        self,
        request: SynthesisRequest,
        policy: PolicyDecision,
        budget: SearchBudget,
    ) -> SynthesisResult: ...
```

---

## Repository Layout (Corrected)

```text
harness/
├── control-plane/
│   ├── policy-bundles/             ← EXISTS (policy-bundle.example.json)
│   ├── capability-profiles/        ← NEW: policy-only.json, unit-test.json, …
│   ├── evidence/                   ← NEW: signed evidence bundles (write-protected)
│   └── schemas/                    ← NEW: critique.schema.json, policy_decision.schema.json
├── shared/
│   ├── governance/                 ← EXISTS
│   │   ├── broker.py               ← EXISTS (ExecutionBroker — sync, canonical)
│   │   ├── evidence_manifest.py    ← EXISTS (EvidenceBuilder — gains candidate_digest, policy_bundle_digest)
│   │   └── control_plane.py        ← NEW (GovernanceControlPlane wrapping broker + evidence)
│   ├── neurosym/                   ← NEW
│   │   ├── strategies/
│   │   │   ├── __init__.py
│   │   │   ├── single_shot.py      ← Milestone 5
│   │   │   └── bounded_lats.py     ← Milestone 5 (default-off, INV-15)
│   │   └── critique/
│   │       ├── __init__.py
│   │       └── normalizer.py       ← Milestone 5
│   ├── evaluation/                 ← NEW (Milestone 4)
│   │   ├── __init__.py
│   │   ├── report.py
│   │   ├── ablation.py
│   │   ├── replay.py
│   │   ├── telemetry.py
│   │   └── fixtures/
│   │       ├── seed_tasks/         ← 30 JSON fixtures
│   │       └── pong/               ← 3–5 deterministic fault fixtures
│   └── tests/
│       ├── test_governance_broker.py       ← EXISTS
│       ├── test_evidence_manifest.py       ← EXISTS
│       ├── test_validate_invariants.py     ← EXISTS
│       ├── test_control_plane.py           ← NEW (Milestone 1)
│       ├── test_execution_profiles.py      ← NEW (Milestone 3)
│       ├── test_adversarial_escapes.py     ← NEW (Milestone 3)
│       ├── test_critique_normalizer.py     ← NEW (Milestone 5)
│       ├── test_synthesis_strategies.py    ← NEW (Milestone 5)
│       └── test_evaluation_harness.py      ← NEW (Milestone 4)
└── node/
    └── src/
        └── ai/                             ← EXISTS (nemotron client layer only)
```

---

## Existing Inventory (Starting Point, Not Duplicates)

The following files are the implementation inventory for Milestone 1 extraction — **not** new implementations:

| File | Role in synthesis |
|------|-------------------|
| `governance/broker.py` | Canonical execution broker (INV-8, INV-9) |
| `governance/evidence_manifest.py` | Evidence builder; gains `candidate_digest`, `policy_bundle_digest` |
| `pretooluse_guard.py` | PreToolUse gate called by broker |
| `verify_zero_skips.py` | INV-2 enforcement |
| `check_traceability.py` | Traceability gate |
| `remotes.py` | INV-3 remote normalizer |
| `governance-policy.json` | Policy source of truth; gains `synthesis.*` section |
| `policy-bundle.example.json` | Digest anchor for control plane |

---

## Milestone Sequencing and Gates

| Milestone | Deliverable | Gate |
|-----------|-------------|------|
| M1 | `GovernanceControlPlane`, `PolicyDecision`, evidence field alignment | AC-GCP-1..5; `make test-governance` green |
| M2 | Provider-neutral model runtime (OpenAI-compatible + Nvidia) | Provider contract tests, SSE replay, circuit-breaker |
| M3 | Capability profiles, adversarial escapes, `SandboxViolation` | AC-CE-1..5; every escape fixture denied with evidence |
| M4 | Seed task suite (30), baseline runs, `EvaluationReport` | AC-AE-1..3, AC-AE-5; reproducible from evidence bundle |
| M5 | `BoundedLatsStrategy`, critique normalizer, repair loop | AC-NS-1..5; LATS threshold from M4 ablation (DEC-AE-001) |
| M6 | `neurosym-synthesis` Mango skill, FastAPI service, dataset export | `openspec validate`, full `make pre-pr`, Tier 6 sandbox tests |
