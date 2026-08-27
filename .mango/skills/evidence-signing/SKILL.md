---
name: evidence-signing
description: >
  Reusable skill for creating tamper-evident, HMAC-signed audit trails using
  EvidenceBuilder. Use when an agent action requires an immutable evidence bundle
  linking policy verdicts, tool calls, and synthesis results to a signed manifest.
  Covers: key resolution, adding policy snapshots / actions / synthesis results,
  export with signature verification, and error handling for missing keys.
version: "1.0"
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

| Variable | Required | Description |
|----------|----------|-------------|
| `AGENT_EVIDENCE_KEY` | **Yes** (or inject via constructor) | HMAC signing key; never hard-code. |

> **If `AGENT_EVIDENCE_KEY` is unset and no `signing_key` is injected, `export()` raises
> `ValueError`. The agent MUST skip evidence export gracefully rather than failing the
> entire task — log a warning and record the skip.**

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

## Non-Goals

- This skill does not manage secret storage or rotation.
- This skill does not provide replay/reconstruction from an evidence bundle — see `harness/shared/evaluation/replay.py` (planned Milestone 4).

## Validation

```bash
make test-governance   # pytest harness/shared/tests/test_evidence_manifest.py
```

Expected: **17 tests passing**, 0 failures.
