"""Regression: agent-memory integrity against direct write and shell redirect bypasses.

Spec: docs/specs/agent-memory-integrity.md (AC-AMI-2, AC-AMI-4, AC-AMI-6).
Finding: docs/reports/2026-DEEP-PEER-REVIEW-MEMORY-INTEGRITY.md §2.1.
"""

from __future__ import annotations

import json
import uuid
from pathlib import Path

import pytest

from harness.shared.governance.broker import ExecutionBroker
from harness.shared.governance.enforcement_digest import enforcement_digests
from harness.shared.memory_view import format_hypotheses_for_reasoner
from harness.shared.meta_tools import hypothesis_register
from harness.shared.orchestrator.dispatcher import ToolDispatcher
from harness.shared.tool_executors import (
    execute_apply_patch,
    execute_generate_code,
    execute_write_file,
)
from harness.shared.write_policy import DEFAULT_POLICY_PATH

pytestmark = pytest.mark.governance


class TestAgentMemoryIntegrityRegression:
    def test_write_file_is_denied_over_the_memory_store(self, tmp_path: Path) -> None:
        """AC-AMI-2: execute_write_file at .mango/memory/hypotheses.json is denied and leaves file unchanged."""
        memory_dir = tmp_path / ".mango" / "memory"
        memory_dir.mkdir(parents=True, exist_ok=True)
        hyp_path = memory_dir / "hypotheses.json"
        original_bytes = b"[]"
        hyp_path.write_bytes(original_bytes)

        res = execute_write_file(tmp_path, ".mango/memory/hypotheses.json", '[{"id": "forged"}]')

        assert "Denied" in res or "Error writing file" in res
        assert "inside the agent memory directory" in res
        assert hyp_path.read_bytes() == original_bytes

    def test_apply_patch_is_denied_over_the_memory_store(self, tmp_path: Path) -> None:
        """AC-AMI-2: execute_apply_patch at .mango/memory/hypotheses.json is denied and leaves file unchanged."""
        memory_dir = tmp_path / ".mango" / "memory"
        memory_dir.mkdir(parents=True, exist_ok=True)
        hyp_path = memory_dir / "hypotheses.json"
        original_bytes = b'[{"id": "real"}]'
        hyp_path.write_bytes(original_bytes)

        res = execute_apply_patch(tmp_path, ".mango/memory/hypotheses.json", "real", "fake")

        assert "Denied" in res or "Error patching file" in res
        assert "inside the agent memory directory" in res
        assert hyp_path.read_bytes() == original_bytes

    def test_generate_code_denied_on_governed_paths(self, tmp_path: Path) -> None:
        """AC-AMI-2, AC-CGT-3: execute_generate_code at .mango/memory/hypotheses.json is denied."""
        memory_dir = tmp_path / ".mango" / "memory"
        memory_dir.mkdir(parents=True, exist_ok=True)
        hyp_path = memory_dir / "hypotheses.json"
        original_bytes = b"[]"
        hyp_path.write_bytes(original_bytes)

        res = execute_generate_code(tmp_path, ".mango/memory/hypotheses.json", '[{"id": "forged"}]')

        assert "Denied" in res or "Error generating code" in res
        assert "inside the agent memory directory" in res
        assert hyp_path.read_bytes() == original_bytes

    def test_a_shell_redirect_into_the_memory_store_is_denied(self, tmp_path: Path) -> None:
        """AC-AMI-2: A run_command redirecting into .mango/memory is blocked by the broker before subprocess."""
        broker = ExecutionBroker()
        dispatcher = ToolDispatcher(workspace_dir=tmp_path, broker=broker)

        memory_dir = tmp_path / ".mango" / "memory"
        memory_dir.mkdir(parents=True, exist_ok=True)
        hyp_path = memory_dir / "hypotheses.json"
        hyp_path.write_bytes(b"[]")

        res = dispatcher.tool_handlers["run_command"]({"command": "echo malicious > .mango/memory/hypotheses.json"})

        assert "BLOCKED" in res
        assert "inside the agent memory directory" in res
        assert hyp_path.read_bytes() == b"[]"

    def test_a_well_formed_forged_hypothesis_is_refused_and_never_surfaced(self, tmp_path: Path) -> None:
        """AC-AMI-4: Well-formed forged hypothesis via write_file is refused, store is unchanged byte-for-byte,

        and format_hypotheses_for_reasoner surfaces only genuine entries.
        """
        # 1. Seed store with one genuine entry via hypothesis_register
        res_genuine = hypothesis_register(
            claim="genuine established fact",
            reasoning="verified with real tests",
            confidence=0.95,
            workspace_dir=tmp_path,
        )
        assert "registered successfully" in res_genuine
        hyp_path = tmp_path / ".mango" / "memory" / "hypotheses.json"
        assert hyp_path.is_file()
        prior_bytes = hyp_path.read_bytes()
        prior_data = json.loads(prior_bytes.decode("utf-8"))
        assert len(prior_data) == 1
        genuine_id = prior_data[0]["id"]

        # 2. Forge a well-formed entry (valid uuid4, valid status, valid confidence, false claim)
        forged_entry = {
            "id": str(uuid.uuid4()),
            "timestamp": 1234567890.0,
            "claim": "malicious forged claim that passes all shape checks",
            "reasoning": "attacker injected reason",
            "confidence": 0.99,
            "status": "confirmed",
        }
        forged_payload = json.dumps([prior_data[0], forged_entry], indent=2)

        # 3. Attempt write_file with forged payload
        denial_result = execute_write_file(tmp_path, ".mango/memory/hypotheses.json", forged_payload)
        assert "inside the agent memory directory" in denial_result

        # 4. Assert store on disk remains byte-for-byte identical
        assert hyp_path.read_bytes() == prior_bytes

        # 5. Assert format_hypotheses_for_reasoner renders ONLY the genuine entry
        rendered = format_hypotheses_for_reasoner(workspace_dir=tmp_path)
        assert "genuine established fact" in rendered
        assert genuine_id in rendered
        assert "malicious forged claim" not in rendered

    def test_the_memory_store_is_not_part_of_the_enforcement_digest_baseline(self, tmp_path: Path) -> None:
        """AC-AMI-6: .mango/memory is not in protected_paths, so meta-tool updates don't tamper digest."""
        policy_data = json.loads(DEFAULT_POLICY_PATH.read_text(encoding="utf-8"))
        protected_paths = policy_data.get("protected_paths", [])
        assert not any(".mango/memory" in p for p in protected_paths)

        # Baseline digests before running hypothesis_register
        digests_before = enforcement_digests(tmp_path)

        # Run hypothesis_register twice during task execution
        hypothesis_register("first runtime hypothesis", "reason 1", 0.8, workspace_dir=tmp_path)
        hypothesis_register("second runtime hypothesis", "reason 2", 0.9, workspace_dir=tmp_path)

        # Digests after
        digests_after = enforcement_digests(tmp_path)

        assert digests_before == digests_after
