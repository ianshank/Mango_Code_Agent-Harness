---
name: evidence-signing
Reviewed: 2026-09-09
description: >
  Reusable skill for creating tamper-evident, HMAC-signed audit trails using
  EvidenceBuilder. Use when an agent action requires an immutable evidence bundle
  linking policy verdicts, tool calls, and synthesis results to a signed manifest.
  Covers: key resolution, adding policy snapshots / actions / synthesis results,
  export with signature verification, error handling for missing keys, and the
  governed broker path (key injected at construction; keyless evidence-enabled
  brokers BLOCK before spawn).
version: "1.1"
validator_version: "2.1"
compatibility: "harness/shared/governance/evidence_manifest.py >= 2.1.7"
skill_max_age_days: 90
---

# Evidence Signing Skill

## Purpose

Generate, populate, and export a **signed evidence manifest** that links governance
verdicts to agent actions. The manifest is HMAC-SHA256 signed; the signature is
verifiable without access to the signing runtime.

## Required Environment

| Variable             | Required                             | Description                        |
|----------------------|--------------------------------------|------------------------------------|
| `AGENT_EVIDENCE_KEY` | **Yes** (or inject via constructor) | HMAC signing key; never hard-code. |

> **Control-plane / `EvidenceBuilder.export()`:** if `AGENT_EVIDENCE_KEY` is unset
> and no `signing_key` is injected, `export()` raises `ValueError`. Treat this as a
> blocking configuration error for `publish_policy_artifact.py`.
>
> **Broker path:** an evidence-enabled `ExecutionBroker` with no constructor key and
> no `AGENT_EVIDENCE_KEY` returns `BLOCKED` naming that env var **before spawn**
> (R-AEI-4 / AC-7). The resolved key is injected into `EvidenceBuilder`; that path
> does not read the environment at `export()`. A refuse `execution.routing` BLOCKED
> is still recorded when a key is present.

## Usage Pattern

```python
from pathlib import Path
import os
import logging
from harness.shared.governance.evidence_manifest import EvidenceBuilder

logger = logging.getLogger(__name__)

# 1. Construct — inject key or rely on env var
builder = EvidenceBuilder(
    project_root=Path("."),
    signing_key=os.getenv("AGENT_EVIDENCE_KEY"),  # None → falls back to env var
)

# 2. Record policy snapshot before execution
builder.add_policy_snapshot(
    policy_id="agentic-ssd-governance",
    version="2.0.0",
    content_hash="<sha256-of-policy-bundle>",
)

# 3. Record each agent tool call
builder.add_action(
    tool_name="write_file",
    arguments_hash="sha256:<hash-of-redacted-args>",
    outcome="success",
    duration_ms=42,
)

# 4. Record synthesis result (if applicable)
builder.add_synthesis_result(
    run_id="run-<uuid>",
    is_accepted=True,
    evaluation_score=0.87,
)

# 5. Export — returns dict with _signature field
try:
    manifest = builder.export()
    logger.info("Evidence manifest exported with %d actions", len(manifest["actions"]))
except ValueError as exc:
    logger.warning("Evidence export skipped — signing key unavailable: %s", exc)
    manifest = None
```

## Verification

To verify a manifest independently (without the agent runtime):

```python
import hashlib, hmac, json


def verify_manifest(manifest: dict, key: str) -> bool:
    sig = manifest.pop("_signature")
    payload = json.dumps(manifest, sort_keys=True).encode("utf-8")
    expected = hmac.new(key.encode("utf-8"), payload, hashlib.sha256).hexdigest()
    return hmac.compare_digest(sig, expected)
```

## Key Rules

1. **Never hard-code a signing key.** Use `AGENT_EVIDENCE_KEY` from the secret store.
2. **Never swallow `ValueError`** from a missing key without logging at WARNING level.
3. **`export()` is non-destructive** — the internal manifest is not mutated; you may call it multiple times.
4. **Redact arguments** before hashing: strip file paths, secrets, and PII before passing `arguments_hash`.
5. **One builder per synthesis session.** Do not share a builder instance across unrelated tasks.

## Consumers

- `harness/control-plane/publish_policy_artifact.py --attest` signs the versioned
  policy artifact. Its final `add_policy_snapshot` entry binds the canonical
  digest of the artifact core (the artifact minus its attestation), so the HMAC
  transitively covers the artifact identity and every pinned file digest — a
  digest edited after signing fails verification. The same key resolution rules
  apply: constructor argument, then `AGENT_EVIDENCE_KEY`, then fail closed. A
  missing key is a `DENY`, never a silently unsigned artifact.
- `ExecutionBroker` (when evidence is enabled) records INV-13 digests through
  `harness/shared/governance/evidence_record.py` after a governed result. The
  sink must lie outside the agent workspace and `protected_paths`.

## Non-Goals

- This skill does not manage secret storage or rotation.
- This skill does not provide replay/reconstruction from an evidence bundle — see `harness/shared/evaluation/replay.py` (planned Milestone 4).
- Host inventory of isolation primitives is `capability_probe.py` (AC-12), not HMAC evidence. Do not treat probe JSON as an evidence digest or a `BackendCapabilities` record.

## Validation

```bash
make test-governance
# pytest harness/shared/tests/test_evidence_manifest.py
# pytest harness/shared/tests/test_evidence_record.py
```

Expected: both modules collect and pass; do not restate a test count here.
