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
from harness.shared.write_policy import DEFAULT_POLICY_PATH, policy_digest

logger = logging.getLogger(__name__)

POLICY_BLOCK = "evidence"


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
    """Policy-sourced cap, or None when the block is undeclared (adopter path).

    Read here rather than through ``policy_loader`` so step 3 does not grow
    that module (499/500). A present block with a missing or non-positive
    ``max_entries`` fails closed.
    """
    path = policy_path or DEFAULT_POLICY_PATH
    try:
        loaded = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None
    except (OSError, ValueError) as exc:
        raise ValueError(f"governance policy at {path} is unreadable: {exc}") from exc
    if not isinstance(loaded, dict):
        raise ValueError(f"governance policy at {path} is not a JSON object")
    if POLICY_BLOCK not in loaded:
        return None
    block = loaded[POLICY_BLOCK]
    if not isinstance(block, dict):
        raise ValueError(f"policy {POLICY_BLOCK} is not an object")
    value = block.get("max_entries")
    if not isinstance(value, int) or isinstance(value, bool) or value < 1:
        raise ValueError(f"policy {POLICY_BLOCK}.max_entries must be a positive integer, got {value!r}")
    return value


def current_policy_digest(policy_path: Path | None = None) -> str:
    """``write_policy.policy_digest`` over the policy file bytes (R-AEI-6)."""
    path = policy_path or DEFAULT_POLICY_PATH
    return policy_digest(path.read_bytes())


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
    return {
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


def append_signed_jsonl(sink: Path, builder: EvidenceBuilder) -> None:
    """Append one signed manifest line. ``sink`` is a file path, not a workspace."""
    sink.parent.mkdir(parents=True, exist_ok=True)
    line = json.dumps(builder.export(), sort_keys=True)
    with sink.open("a", encoding="utf-8") as handle:
        handle.write(line + "\n")
    logger.debug("evidence entry appended to %s", sink)


__all__ = [
    "POLICY_BLOCK",
    "append_signed_jsonl",
    "backend_capability_record",
    "build_execution_entry",
    "current_policy_digest",
    "evidence_max_entries",
    "fold_enforcement_baseline",
    "test_digest",
]
