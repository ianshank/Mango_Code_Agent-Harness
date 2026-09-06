"""Regression pin: H4 context-window budget preserves tool-call groups.

Audit H4 (`docs/reports/2026-STANDARDS-AUDIT.md`) / OpenSpec
`docs/specs/context-window-budget.md`: under a low policy budget, eviction must
drop oldest assistant+tool groups atomically — never orphan a ``role:tool``
result or leave ``tool_calls`` without matching results — while
``conversation_history`` on the loop stays the full append-only log.

Unit coverage lives in ``test_context_policy.py``; this module pins the
defect-class survival contract in the regression tier (CONTRACT.md).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest

from harness.shared.context_policy import (
    apply_context_policy,
    estimate_tokens,
    history_tool_links_are_consistent,
)
from harness.shared.orchestrator.loop import ExecutionLoop
from harness.shared.tests._helpers import REPO
from harness.shared.tests._orchestrator_helpers import _resp, _tool_call

pytestmark = pytest.mark.governance

SHARED_POLICY = REPO / "harness" / "shared" / "governance-policy.json"
CHARS_PER_TOKEN = 4.0


def _assistant_tools(*calls: dict[str, Any]) -> dict[str, Any]:
    return {"role": "assistant", "content": None, "tool_calls": list(calls)}


def _tool_result(call_id: str, content: str) -> dict[str, Any]:
    return {"role": "tool", "tool_call_id": call_id, "content": content}


def _history_with_two_groups(*, payload: str) -> list[dict[str, Any]]:
    return [
        {"role": "system", "content": "sys"},
        {"role": "user", "content": "start"},
        _assistant_tools(_tool_call("write_file", {"filepath": "a.txt", "content": "a"}, call_id="call_old")),
        _tool_result("call_old", payload),
        _assistant_tools(_tool_call("write_file", {"filepath": "b.txt", "content": "b"}, call_id="call_new")),
        _tool_result("call_new", payload),
        {"role": "user", "content": "continue"},
    ]


def test_tool_group_survival_under_context_budget(tmp_path: Path) -> None:
    """Oldest tool-call group is evicted as a unit; newer group and links survive."""
    history = _history_with_two_groups(payload="R" * 8000)
    newer = [history[0], history[1], history[4], history[5], history[6]]
    low_budget = estimate_tokens(newer, CHARS_PER_TOKEN)

    kept, stats = apply_context_policy(history, budget_tokens=low_budget, chars_per_token=CHARS_PER_TOKEN)
    assert stats["messages_evicted"] >= 2
    assert history_tool_links_are_consistent(kept)
    assert not any(m.get("tool_call_id") == "call_old" for m in kept)
    assert any(m.get("tool_call_id") == "call_new" for m in kept)
    assert not any(tc.get("id") == "call_old" for m in kept for tc in (m.get("tool_calls") or []))

    policy = json.loads(SHARED_POLICY.read_text(encoding="utf-8"))
    # Budget slightly above the newer-only estimate so eviction of the oldest
    # group is required once the loop prepends the agent system/user turn.
    policy["orchestrator"]["context_budget_tokens"] = low_budget + 80
    policy_path = tmp_path / "policy.json"
    policy_path.write_text(json.dumps(policy), encoding="utf-8")

    agents = tmp_path / "agents"
    agents.mkdir()
    (agents / "nemotron-reasoner.md").write_text("You are reasoner.", encoding="utf-8")

    captured: list[list[dict[str, Any]]] = []

    def _capture(**kwargs: Any) -> dict[str, Any]:
        captured.append(list(kwargs["messages"]))
        return _resp("done")

    loop = ExecutionLoop(
        workspace_dir=tmp_path,
        agents_dir=agents,
        dispatcher=MagicMock(),
        hook_runner=MagicMock(),
        verification=MagicMock(),
        verification_cwd=tmp_path,
        policy_path=policy_path,
        complete_chat_fn=_capture,
        max_iterations=3,
        api_timeout=5,
        max_tool_calls_per_task=10,
    )
    loop.conversation_history.extend(history)
    full_before = list(loop.conversation_history)
    result = loop.execute_agent("nemotron-reasoner", "finish")

    assert result == "done"
    assert captured, "complete_chat was not called"
    model_facing = captured[0]
    assert history_tool_links_are_consistent(model_facing)
    assert not any(m.get("tool_call_id") == "call_old" for m in model_facing)
    assert loop.conversation_history[: len(full_before)] == full_before
    assert any(m.get("tool_call_id") == "call_old" for m in loop.conversation_history)
