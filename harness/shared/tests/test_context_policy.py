"""Tests for context-window budget (docs/specs/context-window-budget.md)."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest

from harness.shared.context_policy import (
    apply_context_policy,
    estimate_tokens,
    history_tool_links_are_consistent,
    identify_tool_call_groups,
    measure_tokens,
)
from harness.shared.orchestrator.loop import ExecutionLoop
from harness.shared.policy_loader import PolicyError, orchestrator_defaults
from harness.shared.tests._helpers import REPO
from harness.shared.tests._orchestrator_helpers import _resp, _tool_call

SHARED_POLICY = REPO / "harness" / "shared" / "governance-policy.json"
CHARS_PER_TOKEN = 4.0


def _assistant_tools(*calls: dict[str, Any]) -> dict[str, Any]:
    return {"role": "assistant", "content": None, "tool_calls": list(calls)}


def _tool_result(call_id: str, content: str) -> dict[str, Any]:
    return {"role": "tool", "tool_call_id": call_id, "content": content}


def _history_with_two_groups(*, payload: str = "x" * 4000) -> list[dict[str, Any]]:
    return [
        {"role": "system", "content": "sys"},
        {"role": "user", "content": "start"},
        _assistant_tools(_tool_call("write_file", {"filepath": "a.txt", "content": "a"}, call_id="call_old")),
        _tool_result("call_old", payload),
        _assistant_tools(_tool_call("write_file", {"filepath": "b.txt", "content": "b"}, call_id="call_new")),
        _tool_result("call_new", payload),
        {"role": "user", "content": "continue"},
    ]


class TestContextPolicyPure:
    def test_context_policy_preserves_tool_call_groups(self) -> None:
        history = _history_with_two_groups()
        kept, stats = apply_context_policy(history, budget_tokens=10**9, chars_per_token=CHARS_PER_TOKEN)
        assert history_tool_links_are_consistent(kept)
        assert stats["messages_evicted"] == 0
        assert stats["groups_preserved"] == 2

        newer_only = [history[0], history[1], history[4], history[5], history[6]]
        target = estimate_tokens(newer_only, CHARS_PER_TOKEN)
        kept, stats = apply_context_policy(history, budget_tokens=target, chars_per_token=CHARS_PER_TOKEN)
        assert history_tool_links_are_consistent(kept)
        assert stats["messages_evicted"] >= 2
        assert not any(tc.get("id") == "call_old" for m in kept for tc in (m.get("tool_calls") or []))
        assert any(m.get("tool_call_id") == "call_new" for m in kept)

    def test_context_policy_evicts_oldest_tool_results_under_budget(self) -> None:
        history = _history_with_two_groups(payload="p" * 8000)
        low_budget = estimate_tokens(
            [history[0], history[1], history[4], history[5], history[6]],
            CHARS_PER_TOKEN,
        )
        kept, stats = apply_context_policy(history, budget_tokens=low_budget, chars_per_token=CHARS_PER_TOKEN)
        assert stats["tokens_before"] > stats["tokens_after"] or stats["messages_evicted"] > 0
        assert stats["tokens_after"] <= low_budget or not identify_tool_call_groups(kept)
        assert history_tool_links_are_consistent(kept)
        assert not any(m.get("tool_call_id") == "call_old" for m in kept)
        assert any(m.get("tool_call_id") == "call_new" for m in kept)

    def test_measure_tokens_prefers_usage_prompt_tokens(self) -> None:
        messages = [{"role": "user", "content": "hi"}]
        assert measure_tokens(messages, usage={"prompt_tokens": 42}, chars_per_token=CHARS_PER_TOKEN) == 42
        assert measure_tokens(
            messages, usage={"prompt_tokens": -1}, chars_per_token=CHARS_PER_TOKEN
        ) == estimate_tokens(messages, CHARS_PER_TOKEN)

    def test_estimate_tokens_rounds_up_conservatively(self) -> None:
        assert estimate_tokens([{"role": "user", "content": "abcde"}], 4.0) == 3

    def test_identify_groups_keeps_multi_tool_assistant_atomic(self) -> None:
        history = [
            _assistant_tools(
                _tool_call("read_file", {"filepath": "a"}, call_id="c1"),
                _tool_call("read_file", {"filepath": "b"}, call_id="c2"),
            ),
            _tool_result("c1", "A"),
            _tool_result("c2", "B"),
        ]
        assert identify_tool_call_groups(history) == [(0, 1, 2)]


class TestContextBudgetPolicyDefaults:
    def test_context_budget_policy_defaults(self, tmp_path: Path) -> None:
        shipped = json.loads(SHARED_POLICY.read_text(encoding="utf-8"))["orchestrator"]
        missing = tmp_path / "absent.json"
        assert orchestrator_defaults(missing)["context_budget_tokens"] == shipped["context_budget_tokens"]
        assert orchestrator_defaults(missing)["context_chars_per_token"] == shipped["context_chars_per_token"]
        history = _history_with_two_groups(payload="small")
        kept, stats = apply_context_policy(
            history,
            budget_tokens=shipped["context_budget_tokens"],
            chars_per_token=float(shipped["context_chars_per_token"]),
        )
        assert stats["messages_evicted"] == 0
        assert kept == history

    def test_present_policy_missing_context_budget_fails_closed(self, tmp_path: Path) -> None:
        body = {
            "max_iterations": 10,
            "api_timeout_sec": 300,
            "verification_timeout_sec": 900,
            "tool_timeout_sec": 30,
            "max_command_bytes": 8192,
            "max_healing_retries": 3,
            "max_output_bytes": 65536,
            "context_chars_per_token": 4,
        }
        path = tmp_path / "policy.json"
        path.write_text(json.dumps({"orchestrator": body}), encoding="utf-8")
        with pytest.raises(PolicyError, match="context_budget_tokens"):
            orchestrator_defaults(path)

    def test_present_policy_missing_chars_per_token_fails_closed(self, tmp_path: Path) -> None:
        body = {
            "max_iterations": 10,
            "api_timeout_sec": 300,
            "verification_timeout_sec": 900,
            "tool_timeout_sec": 30,
            "max_command_bytes": 8192,
            "max_healing_retries": 3,
            "max_output_bytes": 65536,
            "context_budget_tokens": 128000,
        }
        path = tmp_path / "policy.json"
        path.write_text(json.dumps({"orchestrator": body}), encoding="utf-8")
        with pytest.raises(PolicyError, match="context_chars_per_token"):
            orchestrator_defaults(path)


class TestExecuteAgentBudgetWiring:
    def _policy_with_budget(self, tmp_path: Path, budget: int) -> Path:
        policy = json.loads(SHARED_POLICY.read_text(encoding="utf-8"))
        policy["orchestrator"]["context_budget_tokens"] = budget
        path = tmp_path / "policy.json"
        path.write_text(json.dumps(policy), encoding="utf-8")
        return path

    def _loop(self, tmp_path: Path, policy_path: Path, complete_chat_fn) -> ExecutionLoop:
        agents = tmp_path / "agents"
        agents.mkdir()
        (agents / "nemotron-reasoner.md").write_text("You are reasoner.", encoding="utf-8")
        return ExecutionLoop(
            workspace_dir=tmp_path,
            agents_dir=agents,
            dispatcher=MagicMock(),
            hook_runner=MagicMock(),
            verification=MagicMock(),
            verification_cwd=tmp_path,
            policy_path=policy_path,
            complete_chat_fn=complete_chat_fn,
            max_iterations=3,
            api_timeout=5,
            max_tool_calls_per_task=10,
        )

    def test_execute_agent_passes_budgeted_messages_to_complete_chat(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        seed = _history_with_two_groups(payload="Z" * 8000)
        newer = [seed[0], seed[1], seed[4], seed[5], seed[6]]
        budget = estimate_tokens(newer, CHARS_PER_TOKEN) + 50
        policy_path = self._policy_with_budget(tmp_path, budget)

        captured: list[list[dict[str, Any]]] = []

        def _capture(**kwargs: Any) -> dict[str, Any]:
            captured.append(list(kwargs["messages"]))
            return _resp("done")

        loop = self._loop(tmp_path, policy_path, _capture)
        loop.conversation_history.extend(seed)
        full_before = list(loop.conversation_history)

        with caplog.at_level(logging.DEBUG, logger="harness.shared.orchestrator.loop"):
            result = loop.execute_agent("nemotron-reasoner", "finish")

        assert result == "done"
        assert captured, "complete_chat was not called"
        model_facing = captured[0]
        assert history_tool_links_are_consistent(model_facing)
        assert not any(m.get("tool_call_id") == "call_old" for m in model_facing)
        assert loop.conversation_history[: len(full_before)] == full_before
        assert any(m.get("tool_call_id") == "call_old" for m in loop.conversation_history)
        extras = [r.__dict__ for r in caplog.records]
        assert any(e.get("event") == "context_policy" for e in extras)

    def test_stale_provider_usage_must_not_skip_eviction_of_grown_history(self) -> None:
        """Regression: prior-turn usage.prompt_tokens must not gate current eviction.

        apply_context_policy always estimates the *current* list. measure_tokens
        may still honour usage when the caller is measuring the same request.
        """
        history = _history_with_two_groups(payload="Q" * 8000)
        low = estimate_tokens(
            [history[0], history[1], history[4], history[5], history[6]],
            CHARS_PER_TOKEN,
        )
        # If usage were wrongly applied to tokens_before/size, a tiny prior
        # prompt_tokens would claim we are already under budget.
        assert measure_tokens(history, usage={"prompt_tokens": 3}, chars_per_token=CHARS_PER_TOKEN) == 3
        kept, stats = apply_context_policy(history, budget_tokens=low, chars_per_token=CHARS_PER_TOKEN)
        assert stats["messages_evicted"] >= 2
        assert history_tool_links_are_consistent(kept)
        assert not any(m.get("tool_call_id") == "call_old" for m in kept)

    def test_loop_has_no_hardcoded_context_budget(self) -> None:

        source = (REPO / "harness" / "shared" / "orchestrator" / "loop.py").read_text(encoding="utf-8")
        assert "apply_context_policy" in source
        assert "context_budget_tokens" in source
        assert "128000" not in source


def test_copy_isolates_tool_calls_nested_mutation() -> None:
    """Budgeted copy must not share nested tool_calls dicts with history."""
    history: list[dict[str, Any]] = [
        {"role": "system", "content": "sys"},
        _assistant_tools(_tool_call("run", "{}", "c1")),
        {"role": "tool", "tool_call_id": "c1", "content": "ok"},
    ]
    kept, _ = apply_context_policy(history, budget_tokens=10_000, chars_per_token=CHARS_PER_TOKEN)
    kept_calls = kept[1]["tool_calls"]
    assert isinstance(kept_calls, list)
    kept_fn = kept_calls[0]["function"]
    assert isinstance(kept_fn, dict)
    kept_fn["arguments"] = '{"mutated": true}'
    original_fn = history[1]["tool_calls"][0]["function"]
    assert isinstance(original_fn, dict)
    assert original_fn["arguments"] == "{}"


def test_measure_tokens_rejects_non_integer_float_usage() -> None:
    messages = [{"role": "user", "content": "abcd"}]
    # 3.7 must fall back to estimate, not truncate to 3
    estimated = estimate_tokens(messages, CHARS_PER_TOKEN)
    got = measure_tokens(messages, usage={"prompt_tokens": 3.7}, chars_per_token=CHARS_PER_TOKEN)
    assert got == estimated
