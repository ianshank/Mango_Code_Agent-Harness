"""Assemble INV-13 evidence entries without growing the broker or the loop.

The enforcement walk already happens once at loop start
(``VerificationRunner.snapshot_enforcement``). This module folds that map into
one digest-of-digests and names the policy, backend, and test digests the
evidence entry cites. It does not import ``broker`` (C-AEI-5) and does not call
``enforcement_digests`` (R-AEI-7).

Spec: docs/specs/attested-execution-isolation.md (R-AEI-4..7, R-AEI-10, C-AEI-2).
CONTRACT: ``harness/CONTRACT.md`` INV-13 (sandbox digest only when isolation
applied). Decisions: DEC-010 (ProcessBackend contains, does not isolate);
DEC-069 (Landlock path for INV-13 isolation). MG-E1 extends attestation to
SWE-ReX / OpenSandbox when ``capabilities().filesystem_isolation == enforced``
(R-AEI-10); payload field changes are additive only.
"""

from __future__ import annotations

import hashlib
import json
import logging
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any, cast

from harness.shared.governance.evidence_manifest import EvidenceBuilder
from harness.shared.governance.execution_backend import (
    ISOLATION_ENFORCED,
    ISOLATION_UNENFORCED,
    LANDLOCK_BACKEND_NAME,
    OPEN_SANDBOX_BACKEND_NAME,
    SWE_REX_BACKEND_NAME,
    IsolationState,
)
from harness.shared.governance.verdict import BROKER_BLOCKED
from harness.shared.policy_defaults import evidence_defaults
from harness.shared.write_policy import active_policy_path, policy_digest

logger = logging.getLogger(__name__)


def fold_enforcement_baseline(digests: Mapping[str, str]) -> str:
    """One digest-of-digests over a path-to-sha256 map (R-AEI-6, R-AEI-7).

    Keys are sorted; encoding is canonical JSON so two equal maps hash equal
    regardless of insertion order.
    """
    payload = json.dumps(dict(sorted(digests.items())), separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def backend_capability_record(backend: Any) -> dict[str, str]:
    """Named so AC-5 can monkeypatch it; a local recomputation cannot satisfy."""
    return {"name": str(getattr(backend, "name", "")), "version": str(getattr(backend, "version", ""))}


def test_digest(command: str, node_ids: Sequence[str]) -> str:
    """Digest of the resolved verification command plus collected node ids."""
    payload = json.dumps({"command": command, "node_ids": list(node_ids)}, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def evidence_max_entries(policy_path: Path | None = None) -> int | None:
    """Policy-sourced cap via the single reader (C-AEI-2, DEC-043).

    ``None`` when the ``evidence`` block is undeclared. A present block with a
    missing or non-positive ``max_entries`` is ``PolicyError``.
    """
    return evidence_defaults(policy_path)


def current_policy_digest(policy_path: Path | None = None) -> str:
    """``write_policy.policy_digest`` over the policy file bytes (R-AEI-6).

    The default is ``active_policy_path()``, the same file
    ``write_denial_reason`` enforces. A digest of ``DEFAULT_POLICY_PATH`` while
    ``MANGO_WRITE_POLICY_PATH`` is set would attest a policy that did not
    decide the write.
    """
    path = policy_path if policy_path is not None else active_policy_path()
    return policy_digest(path.read_bytes())


def _sandbox_fields(backend: Any, outcome: str) -> dict[str, Any]:
    """Sandbox digest only when this command was isolated (DEC-069, R-AEI-10, AC-19).

    Cross-links: CONTRACT INV-13; DEC-010 (ProcessBackend never isolates);
    DEC-069 (Landlock attestation when FS+net enforced); R-AEI-10 (MG-E1
    SWE-ReX/OpenSandbox may attest when ``filesystem_isolation == enforced``;
    ``available()`` alone is never sufficient).

    ``ProcessBackend`` never qualifies, even if a test injects isolation-shaped
    probe JSON (AQA-007). Unenforced capabilities are never recorded as
    enforced. A ``BLOCKED`` outcome never claims the fifth digest: a reused
    ``LandlockBackend`` may still report enforced capabilities from an earlier
    spawn, and that must not leak onto a request that never ran confined.
    """
    if outcome == BROKER_BLOCKED:
        return {"sandbox_attested": False}
    name = str(getattr(backend, "name", ""))
    caps_fn = getattr(backend, "capabilities", None)
    filesystem: str = ISOLATION_UNENFORCED
    network: str = ISOLATION_UNENFORCED
    if callable(caps_fn):
        caps = caps_fn()
        filesystem = str(getattr(caps, "filesystem_isolation", ISOLATION_UNENFORCED))
        network = str(getattr(caps, "network_isolation", ISOLATION_UNENFORCED))
    attested = filesystem == ISOLATION_ENFORCED and (
        (name == LANDLOCK_BACKEND_NAME and network == ISOLATION_ENFORCED)
        or name in {SWE_REX_BACKEND_NAME, OPEN_SANDBOX_BACKEND_NAME}
    )
    if not attested:
        return {"sandbox_attested": False}
    payload = json.dumps(
        {
            "backend": name,
            "version": str(getattr(backend, "version", "")),
            "filesystem_isolation": filesystem,
            "network_isolation": network,
        },
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    )
    return {
        "sandbox_attested": True,
        "sandbox_digest": hashlib.sha256(payload.encode("utf-8")).hexdigest(),
    }


def build_execution_entry(
    *,
    command: str,
    outcome: str,
    action: str,
    exit_code: int,
    baseline: Mapping[str, str],
    backend: Any,
    node_ids: Sequence[str] = (),
    policy_path: Path | None = None,
) -> dict[str, Any]:
    """The four INV-13 digests, the command outcome, and optional sandbox fields.

    ``sandbox_attested`` / ``sandbox_digest`` follow ``_sandbox_fields`` (Landlock
    DEC-069 or MG-E1 enforced SWE-ReX/OpenSandbox per R-AEI-10). The four digest
    fields are always recorded. Additive MG-E1 keys: ``filesystem_isolation``
    (backend capability snapshot) and ``evidence_schema_version`` (currently 1);
    existing keys are never removed or renamed.
    """
    caps = backend_capability_record(backend)
    caps_fn = getattr(backend, "capabilities", None)
    filesystem_isolation = ISOLATION_UNENFORCED
    if callable(caps_fn):
        live = caps_fn()
        raw_fs = getattr(live, "filesystem_isolation", ISOLATION_UNENFORCED)
        filesystem_isolation = cast(
            IsolationState,
            raw_fs if raw_fs in {"enforced", "unenforced", "undetermined"} else ISOLATION_UNENFORCED,
        )
    entry: dict[str, Any] = {
        "command": command,
        "outcome": outcome,
        "action": action,
        "exit_code": exit_code,
        "policy_digest": current_policy_digest(policy_path),
        "source_digest": fold_enforcement_baseline(baseline),
        "backend_name": caps["name"],
        "backend_version": caps["version"],
        "test_digest": test_digest(command, node_ids),
        # Additive MG-E1 (Data Steward): do not mutate legacy field meanings.
        "evidence_schema_version": 1,
        "filesystem_isolation": filesystem_isolation,
    }
    entry.update(_sandbox_fields(backend, outcome))
    return entry


def append_signed_jsonl(sink: Path, builder: EvidenceBuilder) -> None:
    """Append one signed manifest line. ``sink`` is a file path, not a workspace."""
    sink.parent.mkdir(parents=True, exist_ok=True)
    line = json.dumps(builder.export(), sort_keys=True)
    with sink.open("a", encoding="utf-8") as handle:
        handle.write(line + "\n")
    logger.debug("evidence entry appended to %s", sink)


__all__ = [
    "append_signed_jsonl",
    "backend_capability_record",
    "build_execution_entry",
    "current_policy_digest",
    "evidence_max_entries",
    "fold_enforcement_baseline",
    "test_digest",
]
