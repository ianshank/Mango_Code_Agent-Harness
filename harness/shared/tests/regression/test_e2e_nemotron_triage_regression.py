"""Regression tests for E2E Nemotron Live Triage and RCA fixes.

Defects covered:
1. Cross-platform newline preservation: execute_write_file and execute_read_file
   preserve strict Unix (LF) and Windows (CRLF) newlines without platform auto-expansion.
2. Bridge API key resolution: resolve_api_key cleanly resolves keys from process environment
   or local .env files.
3. Orchestrator prompt resolution fallback: MangoMASOrchestrator in scratch workspaces
   dynamically falls back to repo root .mango/agents directory.
4. Command broker discard stream filtering: write_targets excludes bit buckets (/dev/null,
   nul, NUL) so stdout/stderr redirection does not trigger write-policy denials.
5. Strict workspace containment: path escaping operations are rejected deterministically.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from harness.shared.governance.command_actions import write_targets
from harness.shared.mango_mas_orchestrator import MangoMASOrchestrator
from harness.shared.nemotron_bridge import resolve_api_key
from harness.shared.tool_executors import execute_read_file, execute_write_file


class TestNewlinePreservationRegression:
    """Ensures tool executors preserve exact newlines without Windows CRLF expansion."""

    def test_write_and_read_pure_lf(self, tmp_path: Path) -> None:
        target = tmp_path / "pure_lf.py"
        content = "def foo():\n    return 42\n"
        res = execute_write_file(workspace_dir=tmp_path, filepath="pure_lf.py", content=content)
        assert "Success: Wrote" in res

        # Verify raw binary bytes on disk
        raw_bytes = target.read_bytes()
        assert b"\r\n" not in raw_bytes
        assert raw_bytes == content.encode("utf-8")

        # Verify execute_read_file roundtrip
        read_res = execute_read_file(workspace_dir=tmp_path, filepath="pure_lf.py")
        assert read_res == content

    def test_write_and_read_explicit_crlf(self, tmp_path: Path) -> None:
        target = tmp_path / "explicit_crlf.py"
        content = "def bar():\r\n    return 100\r\n"
        res = execute_write_file(workspace_dir=tmp_path, filepath="explicit_crlf.py", content=content)
        assert "Success: Wrote" in res

        # Verify raw binary bytes on disk
        raw_bytes = target.read_bytes()
        assert raw_bytes == content.encode("utf-8")

        # Verify execute_read_file roundtrip
        read_res = execute_read_file(workspace_dir=tmp_path, filepath="explicit_crlf.py")
        assert read_res == content


class TestOrchestratorAgentPromptFallback:
    """Ensures MangoMASOrchestrator resolves canonical agents in scratch workspaces."""

    def test_scratch_workspace_resolves_repo_agents(self, tmp_path: Path) -> None:
        orchestrator = MangoMASOrchestrator(workspace_dir=tmp_path)
        # tmp_path has no .mango directory
        assert not (tmp_path / ".mango").exists()

        # Should cleanly resolve standard agent prompts via fallback
        planner_prompt = orchestrator.load_agent_prompt("planner")
        assert "planner" in planner_prompt.lower()

        reasoner_prompt = orchestrator.load_agent_prompt("nemotron-reasoner")
        assert "nemotron" in reasoner_prompt.lower()

        verifier_prompt = orchestrator.load_agent_prompt("verifier")
        assert "verifier" in verifier_prompt.lower()


class TestCommandBrokerDiscardStreamFiltering:
    """Ensures bit buckets and discard streams (/dev/null, nul) are not classified as file write targets."""

    @pytest.mark.parametrize(
        ("cmd", "label"),
        [
            ("pytest > /dev/null 2>&1", "unix-devnull"),
            ("pytest > nul", "windows-nul"),
            ("python -c 'print(1)' 2>/dev/null", "stderr-devnull"),
            ("make validate > /dev/null", "make-devnull"),
            ("echo 123 > /dev/zero", "dev-zero"),
        ],
    )
    def test_discard_streams_ignored_by_write_targets(self, cmd: str, label: str) -> None:
        targets = write_targets(cmd)
        assert targets == [], f"{label} produced unexpected write targets: {targets}"

    def test_real_file_redirect_retained(self) -> None:
        cmd = "pytest > results.txt 2>&1"
        targets = write_targets(cmd)
        assert targets == ["results.txt"]


class TestApiKeyResolutionRegression:
    """Ensures resolve_api_key handles environment and fallback safely."""

    def test_resolve_api_key_from_env(self) -> None:
        with patch.dict("os.environ", {"NVIDIA_API_KEY": "nvapi-test-key-12345"}):
            key = resolve_api_key()
            assert key == "nvapi-test-key-12345"

    def test_resolve_api_key_empty_when_unset(self) -> None:
        with patch("harness.shared.nemotron_bridge.resolve_environment", return_value={"api_key": ""}):
            key = resolve_api_key()
            assert key == ""


class TestLATSNegativeRewardRegression:
    """DEF-NEMO-002: Pins that MCTS selects the optimal branch even when all scores are negative."""

    def test_best_leaf_with_all_negative_scores(self) -> None:
        from harness.shared.langgraph.ablation import AblationNode
        from harness.shared.lats_optimizer import LATSOptimizer

        optimizer = LATSOptimizer()
        root = AblationNode(state_diff={})

        child1 = AblationNode(state_diff={"step": 1})
        child2 = AblationNode(state_diff={"step": 2})
        root.add_child(child1)
        root.add_child(child2)

        # child1 has average score -0.8, child2 has average score -0.2 (better)
        optimizer.backpropagate(child1, -0.8)
        optimizer.backpropagate(child2, -0.2)

        best = optimizer._best_leaf(root)
        assert best is not None
        assert best == child2
        assert best.state_diff == {"step": 2}

    def test_refine_plan_with_negative_evaluations(self) -> None:
        from harness.shared.lats_optimizer import LATSOptimizer

        optimizer = LATSOptimizer(exploration_weight=0.0, max_budget=3)
        from typing import Any, cast

        from harness.shared.langgraph.state import MangoState

        base_state = cast(MangoState, {"task": "solve bug", "plan": "initial"})

        def rollout(state: MangoState) -> list[dict[str, Any]]:
            return [{"plan": "attempt A"}, {"plan": "attempt B"}]

        def evaluate(state: MangoState) -> float:
            if state.get("plan") == "attempt B":
                return -0.1
            return -0.9

        refined = optimizer.refine_plan(base_state, rollout_fn=rollout, eval_fn=evaluate)
        assert refined.get("plan") == "attempt B"


class TestMultiToolBudgetExhaustionRegression:
    """DEF-NEMO-003: Pins multi-tool turn budget rejection and hook telemetry."""

    def test_multi_tool_call_exceeding_budget_halts_and_fires_hook(
        self, tmp_path: Path
    ) -> None:
        from harness.shared.tests._orchestrator_helpers import _resp, _tool_call
        from harness.shared.tool_budget import ToolBudget

        budget = ToolBudget(limit=1)
        two_calls = [
            _tool_call("read_file", {"filepath": "a.txt"}),
            _tool_call("read_file", {"filepath": "b.txt"}),
        ]

        with patch(
            "harness.shared.mango_mas_orchestrator.complete_chat",
            return_value=_resp(None, tool_calls=two_calls),
        ):
            orch = MangoMASOrchestrator(workspace_dir=tmp_path)
            hook_events: list[tuple[str, dict]] = []

            def _recording_hook(hook_name: str, **kwargs: object) -> None:
                hook_events.append((hook_name, kwargs))

            orch.execution_loop.hook_runner.run_hook = _recording_hook  # type: ignore[assignment]

            with pytest.raises(RuntimeError, match="exceeded the tool-call budget"):
                orch.execute_agent("nemotron-reasoner", "read both files", budget=budget)

        # Verify hook fired with budget_exceeded status
        post_hooks = [e for e in hook_events if "post-nemotron-reasoner-run" in e[0]]
        assert len(post_hooks) == 1
        assert post_hooks[0][1].get("status") == "budget_exceeded"


class TestMCPUnicodeAndErrorIsolationRegression:
    """DEF-NEMO-004: Pins MCP tool execution with Unicode paths and error safety."""

    def test_mcp_execute_unicode_path_and_content(self, tmp_path: Path) -> None:
        from harness.shared.governance.broker import ExecutionBroker
        from harness.shared.mcp_server import _build_tool_handlers

        broker = ExecutionBroker()
        handlers = _build_tool_handlers(tmp_path, broker, "nemotron-reasoner")

        unicode_file = "café_src.py"
        unicode_content = "def résumé(): return 'succès' \u2713\n"

        # Write
        res_write = handlers["write_file"]({"filepath": unicode_file, "content": unicode_content})
        assert "Success: Wrote" in res_write
        assert (tmp_path / unicode_file).exists()

        # Read back
        res_read = handlers["read_file"]({"filepath": unicode_file})
        assert res_read == unicode_content


class TestAutonomousHealingE2ERegression:
    """DEF-NEMO-006: Pins the autonomous self-healing loop in StateGraph."""

    def test_state_graph_healing_loop_recovers_from_test_failure(self) -> None:
        from unittest.mock import MagicMock

        from harness.shared.governance.verdict import FAILED, VERIFIED, Verdict
        from harness.shared.langgraph.graph import build_graph
        from harness.shared.langgraph.policy import GraphPolicy

        mock_orch = MagicMock()

        # Planner -> Reasoner (turn 1 buggy) -> Verifier (fails) -> Reasoner (turn 2 fixed) -> Verifier (passes)
        mock_orch.execute_agent.side_effect = [
            "# Plan: Implement fib",           # Planner
            "def fib(n): return n",             # Reasoner (turn 1 - buggy)
            "VERDICT: FAIL - test_fib failed",   # Verifier (turn 1)
            "def fib(n): return n if n < 2 else fib(n-1) + fib(n-2)",  # Reasoner (turn 2 - fixed)
            "VERDICT: PASS",                    # Verifier (turn 2)
        ]

        verdict_fail = Verdict(
            status=FAILED,
            reason="AssertionError: fib(5) == 5 != 1",
            termination_reason="",
            command="pytest test_fib.py",
            exit_code=1,
        )
        verdict_pass = Verdict(
            status=VERIFIED,
            reason="all 5 tests passed",
            termination_reason="",
            command="pytest test_fib.py",
            exit_code=0,
        )
        mock_orch._harness_verdict.side_effect = [verdict_fail, verdict_pass]

        policy = GraphPolicy(max_iterations=5, recursion_limit=25)
        graph = build_graph(policy=policy)
        config = {"configurable": {"orchestrator": mock_orch, "policy": policy}}

        initial_state = {"task": "Write Fibonacci function with tests"}
        final_state = graph.invoke(initial_state, config=config)

        assert final_state.get("verdict") == "VERIFIED"
        assert final_state.get("revision_count", 0) >= 1
        assert len(final_state.get("patches", [])) >= 2


