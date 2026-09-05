"""Tamper-evident evidence records for agent actions and governance audit trails.

The signing key is resolved in priority order:
  1. ``signing_key`` constructor argument
  2. ``AGENT_EVIDENCE_KEY`` environment variable

This makes the class fully testable without environment mutation while preserving
backwards-compatible behaviour for callers that rely solely on the env var.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

#: Environment variable name for the HMAC signing key.
EVIDENCE_KEY_ENV = "AGENT_EVIDENCE_KEY"


@dataclass
class EvidenceBuilder:
    """Creates tamper-evident records of agent actions and outcomes.

    Args:
        project_root: Root path of the project being audited.
        signing_key: Optional HMAC key. Falls back to the ``AGENT_EVIDENCE_KEY``
            environment variable when omitted. ``export()`` raises ``ValueError``
            if neither is provided.
    """

    project_root: Path
    signing_key: str | None = field(default=None, repr=False)
    _manifest: dict[str, Any] = field(
        default_factory=lambda: {
            "timestamp": time.time(),
            "policies": [],
            "actions": [],
            "synthesis_results": [],
        }
    )

    def _resolve_key(self) -> bytes:
        """Return the HMAC signing key as bytes.

        Raises:
            ValueError: When no key is available from the constructor or env var.
        """
        key_str = self.signing_key or os.environ.get(EVIDENCE_KEY_ENV)
        if not key_str:
            raise ValueError(
                f"No signing key available. Pass ``signing_key`` to the constructor "
                f"or set the {EVIDENCE_KEY_ENV!r} environment variable."
            )
        return key_str.encode("utf-8")

    def add_policy_snapshot(self, policy_id: str, version: str, content_hash: str) -> None:
        """Record the state of a policy used during this session."""
        self._manifest["policies"].append(
            {
                "policy_id": policy_id,
                "version": version,
                "content_hash": content_hash,
                "timestamp": time.time(),
            }
        )

    def add_action(self, tool_name: str, arguments_hash: str, outcome: str, duration_ms: int) -> None:
        """Record a tool execution action."""
        self._manifest["actions"].append(
            {
                "tool_name": tool_name,
                "arguments_hash": arguments_hash,
                "outcome": outcome,
                "duration_ms": duration_ms,
                "timestamp": time.time(),
            }
        )

    def add_synthesis_result(self, run_id: str, is_accepted: bool, evaluation_score: float) -> None:
        """Record the outcome of a synthesis generation run."""
        self._manifest["synthesis_results"].append(
            {
                "run_id": run_id,
                "is_accepted": is_accepted,
                "evaluation_score": evaluation_score,
                "timestamp": time.time(),
            }
        )

    def export(self) -> dict[str, Any]:
        """Export the manifest with a tamper-evident HMAC-SHA256 signature.

        Returns:
            A copy of the manifest with a ``_signature`` field added.

        Raises:
            ValueError: When no signing key is configured.
        """
        data = self._manifest.copy()
        content_bytes = json.dumps(data, sort_keys=True).encode("utf-8")
        key = self._resolve_key()
        data["_signature"] = hmac.new(key, content_bytes, hashlib.sha256).hexdigest()
        logger.debug(
            "Evidence manifest exported: %d policies, %d actions, %d synthesis results",
            len(self._manifest.get("policies", [])),
            len(self._manifest.get("actions", [])),
            len(self._manifest.get("synthesis_results", [])),
        )
        return data
