"""``ExecutionLoop``'s budgets come from the policy when a caller omits them.

Before this change the constructor defaulted to ``15 / 30 / 50`` while
``governance-policy.json`` said ``10 / 300 / 100``; the facade always passed
explicit values, so the drift was masked from the orchestrator's own tests and
live for any direct constructor call (tech-debt-hardening-plan R-TDH-12,
policy-single-source AC-1).

Distinguishable values in a temporary policy are the proof: a test that
asserted the defaults equal the shipped policy would also pass if someone
hand-edited the literals back to 10/300/100.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from harness.shared.orchestrator.loop import ExecutionLoop
from harness.shared.policy_loader import PolicyError
from harness.shared.tests._helpers import REPO

SHARED_POLICY = REPO / "harness" / "shared" / "governance-policy.json"

DISTINGUISHABLE = {"max_iterations": 77, "api_timeout_sec": 88, "max_tool_calls_per_task": 99}


def _loop(tmp_path: Path, **kwargs) -> ExecutionLoop:
    return ExecutionLoop(
        workspace_dir=tmp_path,
        agents_dir=tmp_path,
        dispatcher=MagicMock(),
        hook_runner=MagicMock(),
        verification=MagicMock(),
        verification_cwd=tmp_path,
        **kwargs,
    )


@pytest.fixture
def temp_policy(tmp_path: Path) -> Path:
    policy = json.loads(SHARED_POLICY.read_text(encoding="utf-8"))
    policy["orchestrator"]["max_iterations"] = DISTINGUISHABLE["max_iterations"]
    policy["orchestrator"]["api_timeout_sec"] = DISTINGUISHABLE["api_timeout_sec"]
    policy["agent_defaults"]["max_tool_calls_per_task"] = DISTINGUISHABLE["max_tool_calls_per_task"]
    path = tmp_path / "policy.json"
    path.write_text(json.dumps(policy), encoding="utf-8")
    return path


class TestExecutionLoopDefaults:
    def test_omitted_budgets_come_from_the_policy(self, tmp_path: Path, temp_policy: Path) -> None:
        loop = _loop(tmp_path, policy_path=temp_policy)
        assert loop.max_iterations == DISTINGUISHABLE["max_iterations"]
        assert loop.api_timeout == DISTINGUISHABLE["api_timeout_sec"]
        assert loop.max_tool_calls_per_task == DISTINGUISHABLE["max_tool_calls_per_task"]

    def test_explicit_budgets_win_over_the_policy(self, tmp_path: Path, temp_policy: Path) -> None:
        loop = _loop(tmp_path, max_iterations=3, api_timeout=4, max_tool_calls_per_task=5, policy_path=temp_policy)
        assert (loop.max_iterations, loop.api_timeout, loop.max_tool_calls_per_task) == (3, 4, 5)

    def test_partial_override_resolves_only_the_omitted_budget(self, tmp_path: Path, temp_policy: Path) -> None:
        loop = _loop(tmp_path, max_iterations=3, policy_path=temp_policy)
        assert loop.max_iterations == 3
        assert loop.api_timeout == DISTINGUISHABLE["api_timeout_sec"]

    def test_the_shipped_policy_is_the_default_source(self, tmp_path: Path) -> None:
        shipped = json.loads(SHARED_POLICY.read_text(encoding="utf-8"))
        loop = _loop(tmp_path)
        assert loop.max_iterations == shipped["orchestrator"]["max_iterations"]
        assert loop.api_timeout == shipped["orchestrator"]["api_timeout_sec"]
        assert loop.max_tool_calls_per_task == shipped["agent_defaults"]["max_tool_calls_per_task"]

    def test_a_malformed_policy_fails_closed(self, tmp_path: Path) -> None:
        bad = tmp_path / "bad.json"
        bad.write_text(json.dumps({"orchestrator": {"max_iterations": "ten"}}), encoding="utf-8")
        with pytest.raises(PolicyError):
            _loop(tmp_path, policy_path=bad)

    def test_resolution_is_logged_at_debug(
        self, tmp_path: Path, temp_policy: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        with caplog.at_level(logging.DEBUG, logger="harness.shared.orchestrator.loop"):
            _loop(tmp_path, policy_path=temp_policy)
        messages = [r.getMessage() for r in caplog.records]
        assert any("resolved from policy" in m and "77" in m for m in messages)
        assert any("tool-call budget resolved from policy: 99" in m for m in messages)

    def test_no_literal_budget_defaults_remain(self) -> None:
        source = (REPO / "harness" / "shared" / "orchestrator" / "loop.py").read_text(encoding="utf-8")
        assert "max_iterations: int = " not in source
        assert "api_timeout: int = " not in source
        assert "max_tool_calls_per_task: int = " not in source
