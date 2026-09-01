"""Autonomous Healing module for resolving test failures.

Parses test failures and triggers the orchestrator for automated remediation loops.
"""

from __future__ import annotations

import logging
import subprocess

from harness.shared.langgraph import LANGGRAPH_AVAILABLE
from harness.shared.langgraph.state import MangoState
from harness.shared.mango_mas_orchestrator import MangoMASOrchestrator
from harness.shared.policy_loader import orchestrator_defaults

logger = logging.getLogger(__name__)

class TestHealer:
    """Detects test failures and triggers automated remediation."""
    def __init__(self, workspace: str, max_retries: int | None = None):
        self.workspace = workspace
        policy_limit = orchestrator_defaults().get("max_healing_retries", 3)
        self.max_retries = max_retries if max_retries is not None else policy_limit

    def _run_test_suite(self, command: list[str]) -> tuple[bool, str]:
        """Runs the test suite and returns (success, output)."""
        try:
            result = subprocess.run(
                command,
                cwd=self.workspace,
                capture_output=True,
                text=True,
                check=False
            )
            success = result.returncode == 0
            output = result.stdout + "\n" + result.stderr
            return success, output
        except Exception as e:  # noqa: BLE001
            return False, f"Failed to run test suite: {e}"

    def heal_until_green(self, command: list[str]) -> bool:
        """Runs the test suite and repeatedly heals failures up to max_retries."""
        attempts = 0
        while attempts < self.max_retries:
            success, output = self._run_test_suite(command)
            if success:
                logger.info("Test suite passed on attempt %s.", attempts + 1)
                return True

            logger.warning(
                "Test suite failed (Attempt %s/%s). Triggering healing...",
                attempts + 1,
                self.max_retries,
            )

            # Formulate the prompt for the reasoning agent
            prompt = (
                f"The test suite failed with the following output:\n\n"
                f"{output}\n\n"
                f"Please diagnose the issue and apply the necessary patches to fix it. "
                f"Ensure your changes pass strict governance checks."
            )

            # Create a localized state for the healing loop
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

            # Invoke the orchestrator
            try:
                if LANGGRAPH_AVAILABLE:
                    from harness.shared.langgraph.graph import build_graph
                    from harness.shared.langgraph.policy import GraphPolicy
                    graph = build_graph(policy=GraphPolicy.from_governance_json())
                    graph.invoke(healing_state)
                else:
                    from pathlib import Path
                    orchestrator = MangoMASOrchestrator(workspace_dir=Path(self.workspace))
                    orchestrator.execute_loop(prompt)
            except Exception as e:  # noqa: BLE001
                logger.error("Healing loop encountered an error: %s", e)
                return False

            attempts += 1

        logger.error("Max healing retries exhausted. Test suite remains red.")
        return False
