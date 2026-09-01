"""Tests for harness/shared/langgraph/decorators.py.

Verifies:
- with_authority enforces write permissions from agent-policy.json
- with_authority fails open gracefully on policy lookup exceptions
- budgeted enforces tool limits from governance policy
- budgeted fails open gracefully on policy lookup exceptions
- budgeted increments budget counter correctly in state returns
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from harness.shared.langgraph.decorators import budgeted, with_authority

pytestmark = pytest.mark.langgraph


class TestWithAuthorityDecorator:
    """Verifies role authority enforcement on LangGraph node functions."""

    def test_read_only_node_executes_successfully(self) -> None:
        @with_authority("nemotron-verifier", may_write=False)
        def sample_node(state: dict) -> dict:
            return {"status": "ok"}

        res = sample_node({"task": "verify"})
        assert res == {"status": "ok"}

    def test_writer_role_allowed_when_may_write_true(self) -> None:
        @with_authority("nemotron-reasoner", may_write=True)
        def writer_node(state: dict) -> dict:
            return {"patches": ["patch1"]}

        res = writer_node({"task": "write"})
        assert res == {"patches": ["patch1"]}

    def test_read_only_role_blocked_when_may_write_true(self) -> None:
        @with_authority("nemotron-verifier", may_write=True)
        def unauthorized_writer_node(state: dict) -> dict:
            return {"patches": ["should_not_run"]}

        res = unauthorized_writer_node({"task": "illegal_write"})
        assert "errors" in res
        assert "lacks write authority" in res["errors"][0]["error"]

    def test_authority_lookup_exception_fails_open(self) -> None:
        @with_authority("unknown-role", may_write=True)
        def fallback_node(state: dict) -> dict:
            return {"executed": True}

        with patch("harness.shared.agent_authority.allowed_actions", side_effect=RuntimeError("Policy missing")):
            res = fallback_node({"task": "fallback"})
            assert res == {"executed": True}


class TestBudgetedDecorator:
    """Verifies tool call budget limits and tracking on LangGraph node functions."""

    def test_budget_within_limit_executes_and_increments(self) -> None:
        @budgeted("tool_budget_used")
        def work_node(state: dict) -> dict:
            return {"data": 123}

        res = work_node({"tool_budget_used": 2})
        assert res["data"] == 123
        assert res["tool_budget_used"] == 3

    def test_budget_exhaustion_blocks_execution(self) -> None:
        @budgeted("tool_budget_used")
        def expensive_node(state: dict) -> dict:
            return {"data": "unreachable"}

        with patch("harness.shared.policy_loader.max_tool_calls_per_task", return_value=5):
            res = expensive_node({"tool_budget_used": 5})
            assert "errors" in res
            assert "tool budget exhausted (5/5)" in res["errors"][0]["error"]

    def test_budget_exception_fails_open(self) -> None:
        @budgeted("tool_budget_used")
        def safe_node(state: dict) -> dict:
            return {"data": "proceed"}

        with patch("harness.shared.policy_loader.max_tool_calls_per_task", side_effect=RuntimeError("IO Error")):
            res = safe_node({"tool_budget_used": 0})
            assert res["data"] == "proceed"
            assert res["tool_budget_used"] == 1

    def test_budget_preserves_explicit_budget_key_in_result(self) -> None:
        @budgeted("tool_budget_used")
        def custom_budget_node(state: dict) -> dict:
            return {"tool_budget_used": 42}

        res = custom_budget_node({"tool_budget_used": 5})
        assert res["tool_budget_used"] == 42

    def test_budget_non_dict_return_value_preserved(self) -> None:
        @budgeted("tool_budget_used")
        def non_dict_node(state: dict) -> str:
            return "string_result"

        res = non_dict_node({"tool_budget_used": 1})
        assert res == "string_result"
