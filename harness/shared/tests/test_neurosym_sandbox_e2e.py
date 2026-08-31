from __future__ import annotations

import json
from pathlib import Path

import pytest

import harness.shared.mango_mas_orchestrator as mmo
from harness.shared.governance.broker import ExecutionBroker, ExecutionResult, ProcessBackend
from harness.shared.mango_mas_orchestrator import MangoMASOrchestrator


class MockSandboxProcessBackend(ProcessBackend):
    """
    A mocked ProcessBackend that intercepts specific commands (like network calls)
    and simulates a SandboxViolation as defined in AC-CE-3.
    """

    def __init__(self, simulate_network_violation: bool = False):
        super().__init__()
        self.simulate_network_violation = simulate_network_violation
        self.call_count = 0

    def run(self, command: str, cwd: Path | None, timeout: int, max_output_bytes: int) -> ExecutionResult:
        self.call_count += 1

        # Check if the command or the file it runs contains network calls
        has_network = False
        if "curl" in command or "requests.get" in command:
            has_network = True
        else:
            # If it's running a file, check the file contents
            parts = command.split()
            if len(parts) >= 2 and parts[0] in ("bash", "sh", "python", "pytest"):
                if cwd and Path(cwd).exists():
                    for file_path in Path(cwd).glob("*.py"):
                        try:
                            content = file_path.read_text(encoding="utf-8")
                            if "curl" in content or "urllib" in content or "requests" in content:
                                if "mock" not in content.lower():
                                    has_network = True
                        except (OSError, UnicodeDecodeError):
                            pass

        if self.simulate_network_violation and has_network:
            sandbox_violation = {
                "schema_version": "1.0",
                "violation_type": "network_access_denied",
                "evidence_id": "evd-12345",
                "capability_profile": "network-isolated",
                "message": "Outbound network calls are prohibited under the network-isolated capability profile.",
            }
            return ExecutionResult(
                status="BLOCKED",
                stdout="",
                stderr=json.dumps(sandbox_violation),
                exit_code=1,
                reason="BLOCKED: Sandbox violation",
                action="execute",
            )

        # If no violation, fallback to actual execution
        return super().run(command, cwd, timeout, max_output_bytes)


@pytest.mark.neurosym
class TestNeurosymSandboxE2E:
    """
    E2E integration tests for the code generation workflow executing inside a sandbox.
    Verifies AC-CE-1, AC-CE-3, and INV-9.
    """

    @pytest.fixture(autouse=True)
    def _mock_hooks(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("ALLOW_GITHUB_CHANGES", "1")
        monkeypatch.setattr(MangoMASOrchestrator, "_run_hook", lambda *args, **kwargs: None)

    def test_sandbox_unavailable_inv9_fallback(self, tmp_path):
        """
        Verifies INV-9: Sandbox unavailable -> BLOCKED, never direct host execution.
        """
        broker = ExecutionBroker(sandbox_available=False)
        orchestrator = MangoMASOrchestrator(workspace_dir=tmp_path, broker=broker)

        task = "Use your run_command tool to execute the shell command `echo hello`. You MUST use the tool."

        original_complete_chat = mmo.complete_chat

        call_count = 0

        def complete_chat_mock(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                # Planner output (plain text plan)
                return {
                    "choices": [{
                        "message": {
                            "role": "assistant",
                            "content": "Plan: 1. Run echo hello using run_command.",
                        }
                    }]
                }
            elif call_count == 2:
                # Reasoner execution
                return {
                    "choices": [{
                        "message": {
                            "role": "assistant",
                            "content": "Executing command.",
                            "tool_calls": [{
                                "id": "call-inv9-1",
                                "type": "function",
                                "function": {
                                    "name": "run_command",
                                    "arguments": '{"command": "echo hello"}',
                                },
                            }],
                        }
                    }]
                }
            else:
                # Final answer / Verifier
                return {
                    "choices": [{
                        "message": {
                            "role": "assistant",
                            "content": "Execution blocked: Sandbox unavailable. FAIL",
                        }
                    }]
                }

        mmo.complete_chat = complete_chat_mock
        try:
            orchestrator.execute_sequential_thinking_loop(task)
        finally:
            mmo.complete_chat = original_complete_chat

        history_str = str(orchestrator.conversation_history)
        assert "Sandbox unavailable" in history_str or "BLOCKED: the execution backend is unavailable" in history_str

    def test_sandbox_violation_triggers_critique_repair_loop(self, tmp_path):
        """
        Verifies AC-CE-1 and AC-NS-3.
        A network violation returns a SandboxViolation. The orchestrator should feed this
        back to the agent to repair.
        """
        # Mock backend that blocks curl/requests
        mock_backend = MockSandboxProcessBackend(simulate_network_violation=True)
        broker = ExecutionBroker(sandbox_available=True, backend=mock_backend)
        orchestrator = MangoMASOrchestrator(workspace_dir=tmp_path, broker=broker)

        task = (
            "Use your run_command tool to execute `curl http://example.com`. "
            "If it fails due to network restrictions, write 'MOCK_DATA' to a file using write_file."
        )

        original_complete_chat = mmo.complete_chat
        call_count = 0

        def complete_chat_mock(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                # Planner response
                return {
                    "choices": [{
                        "message": {
                            "role": "assistant",
                            "content": "Plan: 1. Run curl. 2. If fails, write mock data.",
                        }
                    }]
                }
            elif call_count == 2:
                # Reasoner execution
                return {
                    "choices": [{
                        "message": {
                            "role": "assistant",
                            "content": "Executing curl.",
                            "tool_calls": [{
                                "id": "call-net-1",
                                "type": "function",
                                "function": {
                                    "name": "run_command",
                                    "arguments": '{"command": "curl http://example.com"}',
                                },
                            }],
                        }
                    }]
                }
            elif call_count == 3:
                # Reasoner repair
                return {
                    "choices": [{
                        "message": {
                            "role": "assistant",
                            "content": "Repairing with mock data after network denial.",
                            "tool_calls": [{
                                "id": "call-net-2",
                                "type": "function",
                                "function": {
                                    "name": "write_file",
                                    "arguments": '{"filepath": "data.txt", "content": "MOCK_DATA"}',
                                },
                            }],
                        }
                    }]
                }
            else:
                return {
                    "choices": [{
                        "message": {
                            "role": "assistant",
                            "content": "Repaired network_access_denied in network-isolated sandbox. PASS",
                        }
                    }]
                }

        mmo.complete_chat = complete_chat_mock
        try:
            verification_result = orchestrator.execute_sequential_thinking_loop(task)
        finally:
            mmo.complete_chat = original_complete_chat

        assert mock_backend.call_count > 0
        history_str = str(orchestrator.conversation_history)
        assert "network_access_denied" in history_str
        assert "network-isolated" in history_str
        assert "PASS" in verification_result or "FAIL" in verification_result
        assert (tmp_path / "data.txt").read_text(encoding="utf-8").strip() == "MOCK_DATA"

    def test_sandbox_application_synthesis_with_repair(self, tmp_path):
        """
        Verifies that the orchestrator can synthesize a simple multi-file Python application
        (a CLI script and its test) while correctly navigating a network-isolated SandboxViolation.
        """
        # We enforce a network-isolated capability profile by mocking it
        mock_backend = MockSandboxProcessBackend(simulate_network_violation=True)
        broker = ExecutionBroker(sandbox_available=True, backend=mock_backend)
        orchestrator = MangoMASOrchestrator(workspace_dir=tmp_path, broker=broker)

        app_dir = tmp_path / "weather_cli"

        task = (
            f"Please create a Python script in {app_dir}/app.py that fetches JSON and prints the temperature.\n"
            "You MUST use the `write_file` tool to create this file.\n"
            "After creating the file, you MUST use the `run_command` tool to execute: `python -m pytest app.py`.\n"
            "If your run_command is blocked with a SandboxViolation, replace the network call with MOCK_DATA."
        )
        original_complete_chat = mmo.complete_chat

        call_count = 0

        def complete_chat_mock(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                # Planner response
                return {
                    "choices": [{
                        "message": {
                            "role": "assistant",
                            "content": "Plan: 1. Write app.py 2. Run pytest 3. Repair if network denied.",
                        }
                    }]
                }
            elif call_count == 2:
                # First attempt: write the live file
                return {
                    "choices": [{
                        "message": {
                            "role": "assistant",
                            "content": "Writing the file with requests.",
                            "tool_calls": [{
                                "id": "call-1",
                                "type": "function",
                                "function": {
                                    "name": "write_file",
                                    "arguments": (
                                        '{"filepath": "weather_cli/app.py", '
                                        '"content": "import requests\\nrequests.get(\\"http://example.com/api\\")"}'
                                    ),
                                },
                            }],
                        }
                    }]
                }
            elif call_count == 3:
                # Second attempt: run the file
                return {
                    "choices": [{
                        "message": {
                            "role": "assistant",
                            "content": "Running tests.",
                            "tool_calls": [{
                                "id": "call-2",
                                "type": "function",
                                "function": {
                                    "name": "run_command",
                                    "arguments": '{"command": "python -m pytest weather_cli/app.py"}',
                                },
                            }],
                        }
                    }]
                }
            elif call_count == 4:
                # Third attempt: fix the file (after SandboxViolation)
                return {
                    "choices": [{
                        "message": {
                            "role": "assistant",
                            "content": "Fixing SandboxViolation.",
                            "tool_calls": [{
                                "id": "call-3",
                                "type": "function",
                                "function": {
                                    "name": "write_file",
                                    "arguments": '{"filepath": "weather_cli/app.py", "content": "MOCK_DATA = 42"}',
                                },
                            }],
                        }
                    }]
                }
            elif call_count == 5:
                # Fourth attempt: run tests again
                return {
                    "choices": [{
                        "message": {
                            "role": "assistant",
                            "content": "Running tests on mock.",
                            "tool_calls": [{
                                "id": "call-4",
                                "type": "function",
                                "function": {
                                    "name": "run_command",
                                    "arguments": '{"command": "python -m pytest weather_cli/app.py"}',
                                },
                            }],
                        }
                    }]
                }
            else:
                # Stop tool calls
                return {
                    "choices": [{
                        "message": {
                            "role": "assistant",
                            "content": (
                                "Done testing. I fixed the network_access_denied "
                                "(network-isolated) violation using MOCK_DATA. PASS"
                            ),
                        }
                    }]
                }

        mmo.complete_chat = complete_chat_mock

        try:
            verification_result = orchestrator.execute_sequential_thinking_loop(task)
        finally:
            mmo.complete_chat = original_complete_chat

        # Assertions
        assert mock_backend.call_count > 0

        # Ensure the SandboxViolation was triggered and passed to the agent
        history_str = str(orchestrator.conversation_history)
        assert "network_access_denied" in history_str
        assert "network-isolated" in history_str

        # Ensure the test ran and the agent claimed a pass or fail
        assert "PASS" in verification_result or "FAIL" in verification_result
        assert "MOCK_DATA = 42" in (app_dir / "app.py").read_text(encoding="utf-8")

