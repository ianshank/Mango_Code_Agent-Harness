import hashlib
import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class EvidenceBuilder:
    """Creates tamper-evident records of agent actions and outcomes."""
    project_root: Path
    _manifest: dict[str, Any] = field(default_factory=lambda: {
        "timestamp": time.time(),
        "policies": [],
        "actions": [],
        "synthesis_results": [],
    })

    def add_policy_snapshot(self, policy_id: str, version: str, content_hash: str) -> None:
        """Record the state of a policy used during this session."""
        self._manifest["policies"].append({
            "policy_id": policy_id,
            "version": version,
            "content_hash": content_hash,
            "timestamp": time.time()
        })

    def add_action(self, tool_name: str, arguments_hash: str, outcome: str, duration_ms: int) -> None:
        """Record a tool execution action."""
        self._manifest["actions"].append({
            "tool_name": tool_name,
            "arguments_hash": arguments_hash,
            "outcome": outcome,
            "duration_ms": duration_ms,
            "timestamp": time.time()
        })

    def add_synthesis_result(self, run_id: str, is_accepted: bool, evaluation_score: float) -> None:
        """Record the outcome of a synthesis generation run."""
        self._manifest["synthesis_results"].append({
            "run_id": run_id,
            "is_accepted": is_accepted,
            "evaluation_score": evaluation_score,
            "timestamp": time.time()
        })

    def export(self) -> dict[str, Any]:
        """Export the final manifest dictionary, including a self-verifying hash."""
        data = self._manifest.copy()

        # Calculate a self-verifying hash of the content
        content_str = json.dumps(data, sort_keys=True).encode('utf-8')
        import os
        import hmac
        key = os.environ.get("AGENT_EVIDENCE_KEY", "default-insecure-key").encode('utf-8')
        data["_signature"] = hmac.new(key, content_str, hashlib.sha256).hexdigest()

        return data
