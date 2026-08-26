# Architecture decision

Use the existing `harness/control-plane/` as the authority boundary and `harness/shared/` as the transitional implementation location. Do not create a second, competing control plane.

```text
Specification / Task Request
               |
               v
+------------------------------+
| Governance Control Plane     |
| - policy bundle version      |
| - capability decision        |
| - traceability/evidence IDs  |
+--------------+---------------+
        allow / deny / blocked
               |
               v
+------------------------------+
| Synthesis Runtime            |
| - provider-neutral client    |
| - single-shot strategy       |
| - optional bounded LATS      |
| - structured critique loop   |
+--------------+---------------+
               |
               v
+------------------------------+
| Execution Broker             |
| - capability manifest        |
| - network/filesystem limits  |
| - sandbox backend adapter    |
| - result normalization       |
+--------------+---------------+
               |
               v
+------------------------------+
| Deterministic Verifiers      |
| - policy bundle              |
| - parser/type/lint/test      |
| - secrets/SAST               |
| - mutation tests on kernel   |
+--------------+---------------+
               |
               v
+------------------------------+
| Evidence + Evaluation        |
| - OpenTelemetry GenAI spans  |
| - redacted replay bundle     |
| - signed provenance          |
| - ablation report            |
+------------------------------+
```

## Core interfaces

```python
from typing import TypedDict, Literal, Protocol

class PolicyDecision(TypedDict):
    verdict: Literal["ALLOW", "DENY", "BLOCKED"]
    policy_bundle_digest: str
    violations: list[dict[str, object]]
    evidence_id: str

class ExecutionRequest(TypedDict):
    language: Literal["python", "typescript", "javascript"]
    source: str
    capability_profile: str
    timeout_ms: int
    workspace_digest: str

class SynthesisStrategy(Protocol):
    async def synthesize(
        self, request: "SynthesisRequest", policy: PolicyDecision, budget: "SearchBudget"
    ) -> "SynthesisResult": ...

class ExecutionBroker(Protocol):
    async def execute(
        self, request: ExecutionRequest,
    ) -> "ExecutionResult": ...
```

## Repository placement

```text
harness/
├── control-plane/
│   ├── policy-bundles/
│   ├── capability-profiles/
│   ├── evidence/
│   └── schemas/
├── shared/
│   ├── governance/               # extracted from current standalone scripts
│   ├── ai/
│   │   ├── protocol/
│   │   ├── resilience/
│   │   ├── security/
│   │   └── providers/
│   ├── execution/
│   │   ├── broker.py
│   │   └── backends/
│   ├── evaluation/
│   └── neurosym/
│       ├── strategies/
│       ├── critique/
│       └── telemetry/
└── node/
    └── src/
        └── ai/
            ├── protocol/
            ├── resilience/
            ├── security/
            └── providers/
```

The existing `nemotron_bridge.py`, `pretooluse_guard.py`, `verify_zero_skips.py`, `check_traceability.py`, policy JSON files, schemas, and validation scripts are the starting inventory—not duplicate implementations.
