"""Assemble INV-13 evidence entries without growing the broker or the loop.

The enforcement walk already happens once at loop start
(``VerificationRunner.snapshot_enforcement``). This module folds that map into
one digest-of-digests and names the policy, backend, and test digests the
evidence entry cites. It does not import ``broker`` (C-AEI-5) and does not call
``enforcement_digests`` (R-AEI-7).

Spec: docs/specs/attested-execution-isolation.md (R-AEI-4..7, C-AEI-2).
"""

from __future__ import annotations

import hashlib
import json
import logging
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from harness.shared.governance.evidence_manifest import EvidenceBuilder
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


def _sandbox_fields(backend: Any) -> dict[str, Any]:
    """Sandbox digest only when Landlock applied both FS and net (DEC-069, AC-19).

    ``ProcessBackend`` never qualifies, even if a test injects isolation-shaped
    probe JSON (AQA-007). Unenforced capabilities are never recorded as
    enforced.
    """
    name = str(getattr(backend, "name", ""))
    caps_fn = getattr(backend, "capabilities", None)
    filesystem = "unenforced"
    network = "unenforced"
    if callable(caps_fn):
        caps = caps_fn()
        filesystem = str(getattr(caps, "filesystem_isolation", "unenforced"))
        network = str(getattr(caps, "network_isolation", "unenforced"))
    attested = name == "landlock" and filesystem == "enforced" and network == "enforced"
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
    """The four INV-13 digests this phase can attest, plus the command outcome."""
    caps = backend_capability_record(backend)
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
    }
    entry.update(_sandbox_fields(backend))
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
