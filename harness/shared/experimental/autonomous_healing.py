"""Autonomous Healing module for resolving test failures.

Parses test failures and triggers the orchestrator for automated remediation loops.
"""

from __future__ import annotations

import logging
import shlex
from pathlib import Path
from typing import TYPE_CHECKING

from harness.shared.agent_authority import execution_identity
from harness.shared.governance.verdict import BROKER_SUCCESS
from harness.shared.langgraph import LANGGRAPH_AVAILABLE
from harness.shared.langgraph.state import MangoState
from harness.shared.mango_mas_orchestrator import MangoMASOrchestrator
from harness.shared.policy_loader import orchestrator_defaults
from harness.shared.tool_result_format import format_execution_result

if TYPE_CHECKING:
    from harness.shared.governance.broker import ExecutionBroker

logger = logging.getLogger(__name__)


class TestHealer:
    """Detects test failures and triggers automated remediation."""
    __test__ = False

    def __init__(
        self,
        workspace: str,
        max_retries: int | None = None,
        broker: ExecutionBroker | None = None,
    ):
        self.workspace = workspace
        self.broker = broker
        policy_limit = orchestrator_defaults().get("max_healing_retries", 3)
        if max_retries is None:
            self.max_retries = policy_limit
        elif isinstance(max_retries, bool) or not isinstance(max_retries, int) or max_retries < 0:
            raise ValueError(f"max_retries must be a non-negative integer, got {max_retries!r}")
        elif max_retries > policy_limit:
            raise ValueError(
                f"max_retries={max_retries} exceeds governance policy limit of {policy_limit}"
            )
        else:
            self.max_retries = max_retries

    def _run_test_suite(self, command: list[str]) -> tuple[bool, str]:
        """Runs the test suite and returns (success, output).

        Routes through the injected ExecutionBroker (INV-8) when available so
        that command classification, pretool guard, and output caps apply.
        """
        from harness.shared.governance.broker import ExecutionBroker
        broker = self.broker if self.broker is not None else ExecutionBroker()
        try:
            broker_result = broker.execute_command(
                shlex.join(command),
                context={"agent_id": execution_identity("nemotron-reasoner")},
                cwd=Path(self.workspace),
            )
            return broker_result.status == BROKER_SUCCESS, format_execution_result(broker_result)
        except Exception as e:  # noqa: BLE001
            return False, f"Failed to run test suite: {e}"

    def heal_until_green(self, command: list[str]) -> bool:
        """Runs tests, then heals up to max_retries times, retesting after each heal."""
        # One initial run, then up to max_retries heal-and-retest cycles.
        success, output = self._run_test_suite(command)
        if success:
            logger.info("Test suite passed on initial run.")
            return True

        for attempt in range(1, self.max_retries + 1):
            logger.warning(
                "Test suite failed (Attempt %s/%s). Triggering healing...",
                attempt,
                self.max_retries,
            )

            prompt = (
                f"The test suite failed with the following output:\n\n"
                f"{output}\n\n"
                f"Please diagnose the issue and apply the necessary patches to fix it. "
                f"Ensure your changes pass strict governance checks."
            )

            healing_state: MangoState = {
                "task": prompt,
                "plan": "",
                "shadow_plan": "",
                "plan_divergence": 0.0,
                "revision_count": 0,
                "gate_status": {},
                "verdict": "",
                "tool_budget_used": 0,
                "patches": [],
                "findings": [],
                "test_results": [],
                "errors": [],
            }

            try:
                if LANGGRAPH_AVAILABLE:
                    from harness.shared.langgraph.graph import build_graph
                    from harness.shared.langgraph.policy import GraphPolicy
                    orchestrator = MangoMASOrchestrator(
                        workspace_dir=Path(self.workspace), broker=self.broker
                    )
                    graph = build_graph(policy=GraphPolicy.from_governance_json())
                    graph.invoke(
                        healing_state,
                        config={"configurable": {"orchestrator": orchestrator}},
                    )
                else:
                    orchestrator = MangoMASOrchestrator(
                        workspace_dir=Path(self.workspace), broker=self.broker
                    )
                    orchestrator.execute_loop(prompt)
            except Exception as e:  # noqa: BLE001
                logger.error("Healing loop encountered an error: %s", e)
                return False

            # Retest after healing
            success, output = self._run_test_suite(command)
            if success:
                logger.info("Test suite passed after healing attempt %s.", attempt)
                return True

        logger.error("Max healing retries exhausted. Test suite remains red.")
        return False
