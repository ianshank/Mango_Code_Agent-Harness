from __future__ import annotations

import json
from pathlib import Path

import pytest

import harness.shared.mango_mas_orchestrator as mmo
from harness.shared.governance.broker import ExecutionBroker, ExecutionResult, ProcessBackend
from harness.shared.governance.verdict import BROKER_BLOCKED
from harness.shared.mango_mas_orchestrator import MangoMASOrchestrator
from harness.shared.orchestrator.hook_runner import HookRunner

# The evidence id the mock stamps on every simulated violation. It can reach the
# model-facing history only by travelling backend -> broker ->
# `format_execution_result`; none of the mocked model turns below ever say it,
# so its presence is proof the critique path ran and not an echo of the script.
VIOLATION_EVIDENCE_ID = "evd-12345"


class MockSandboxProcessBackend(ProcessBackend):
    """
    A mocked ProcessBackend that intercepts specific commands (like network calls)
    and simulates a SandboxViolation as defined in AC-CE-3.
    """

    def __init__(self, simulate_network_violation: bool = False):
        super().__init__()
        self.simulate_network_violation = simulate_network_violation
        self.call_count = 0
        # Every (command, result) pair handed back to the broker, in order, so a
        # test asserts on what the backend did rather than on what the mocked
        # model claimed afterwards. The orchestrator's own pre-flight `make -n`
        # probe lands here too; `statuses_for` filters to one command.
        self.calls: list[tuple[str, ExecutionResult]] = []

    def statuses_for(self, command: str) -> list[str]:
        return [result.status for issued, result in self.calls if issued == command]

    def run(self, command: str, cwd: Path | None, timeout: int, max_output_bytes: int) -> ExecutionResult:
        self.call_count += 1
        result = self._simulate_or_run(command, cwd, timeout, max_output_bytes)
        self.calls.append((command, result))
        return result

    def _simulate_or_run(self, command: str, cwd: Path | None, timeout: int, max_output_bytes: int) -> ExecutionResult:
        # Check if the command or the file it runs contains network calls
        has_network = False
        if "curl" in command or "requests.get" in command:
            has_network = True
        else:
            # If it's running a file, check the file contents
            parts = command.split()
            if len(parts) >= 2 and parts[0] in ("bash", "sh", "python", "pytest"):
                if cwd and Path(cwd).exists():
                    # rglob, not glob: the synthesised app lives in a subdirectory
                    # of the workspace, and a top-level scan never saw it, so the
                    # violation this mock exists to simulate was never raised.
                    for file_path in Path(cwd).rglob("*.py"):
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
                "evidence_id": VIOLATION_EVIDENCE_ID,
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
    Verifies INV-9 and AC-NS-3. The AC-CE-1 capability-profile violation is
    *simulated* by ``MockSandboxProcessBackend``; the production ``ProcessBackend``
    does not enforce capability profiles, so nothing here is a production
    enforcement check (``docs/architecture/c4_architecture.md`` §4.6).
    """

    @pytest.fixture(autouse=True)
    def _mock_hooks(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("ALLOW_GITHUB_CHANGES", "1")
        # Hooks live on the HookRunner the facade composes (R-TDH-18); patch the
        # class so every orchestrator built inside a test inherits the no-op.
        monkeypatch.setattr(HookRunner, "run_hook", lambda *args, **kwargs: None)

    @pytest.fixture(autouse=True)
    def _ensure_make_on_path(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Bypass the pre-flight check so the broker is actually called."""
        monkeypatch.setattr("shutil.which", lambda cmd: "mock/make" if cmd == "make" else None)

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
                    "choices": [
                        {
                            "message": {
                                "role": "assistant",
                                "content": "Plan: 1. Run echo hello using run_command.",
                            }
                        }
                    ]
                }
            elif call_count == 2:
                # Reasoner execution
                return {
                    "choices": [
                        {
                            "message": {
                                "role": "assistant",
                                "content": "Executing command.",
                                "tool_calls": [
                                    {
                                        "id": "call-inv9-1",
                                        "type": "function",
                                        "function": {
                                            "name": "run_command",
                                            "arguments": '{"command": "echo hello"}',
                                        },
                                    }
                                ],
                            }
                        }
                    ]
                }
            else:
                # Final answer / Verifier
                return {
                    "choices": [
                        {
                            "message": {
                                "role": "assistant",
                                "content": "Execution blocked: Sandbox unavailable. FAIL",
                            }
                        }
                    ]
                }

        original_complete_chat = orchestrator.execution_loop.complete_chat_fn
        orchestrator.execution_loop.complete_chat_fn = complete_chat_mock
        try:
            orchestrator.execute_sequential_thinking_loop(task)
        finally:
            orchestrator.execution_loop.complete_chat_fn = original_complete_chat

        history_str = str(orchestrator.conversation_history)
        assert "Sandbox unavailable" in history_str or "BLOCKED: the execution backend is unavailable" in history_str

    def test_sandbox_violation_triggers_critique_repair_loop(self, tmp_path):
        """
        Verifies AC-NS-3 against a simulated AC-CE-1 violation.
        The mock backend returns a SandboxViolation for a script that makes a network
        call; the orchestrator should normalise it into a critique and feed it back to
        the agent to repair. Production does not raise this violation.
        """
        # Mock backend that blocks scripts making network calls
        mock_backend = MockSandboxProcessBackend(simulate_network_violation=True)
        broker = ExecutionBroker(sandbox_available=True, backend=mock_backend)
        orchestrator = MangoMASOrchestrator(workspace_dir=tmp_path, broker=broker)

        # The script is run rather than a bare `curl`: the policy decision point
        # classifies `curl` as `external_write` and denies it before the broker
        # ever reaches the backend, so a curl-based version of this test never
        # exercised the sandbox violation it is named for.
        run_script = "python fetch.py"
        task = (
            "Use write_file to create fetch.py, which fetches http://example.com with requests, "
            f"then use your run_command tool to execute `{run_script}`. "
            "If it fails due to network restrictions, write 'MOCK_DATA' to a file using write_file."
        )

        original_complete_chat = orchestrator.execution_loop.complete_chat_fn
        call_count = 0

        def complete_chat_mock(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                # Planner response
                return {
                    "choices": [
                        {
                            "message": {
                                "role": "assistant",
                                "content": "Plan: 1. Write fetch.py. 2. Run it. 3. If denied, write mock data.",
                            }
                        }
                    ]
                }
            elif call_count == 2:
                # Reasoner writes the script that will trip the sandbox
                return {
                    "choices": [
                        {
                            "message": {
                                "role": "assistant",
                                "content": "Writing fetch.py.",
                                "tool_calls": [
                                    {
                                        "id": "call-net-0",
                                        "type": "function",
                                        "function": {
                                            "name": "write_file",
                                            "arguments": (
                                                '{"filepath": "fetch.py", '
                                                '"content": "import requests\\nrequests.get(\\"http://example.com\\")"}'
                                            ),
                                        },
                                    }
                                ],
                            }
                        }
                    ]
                }
            elif call_count == 3:
                # Reasoner execution
                return {
                    "choices": [
                        {
                            "message": {
                                "role": "assistant",
                                "content": "Running fetch.py.",
                                "tool_calls": [
                                    {
                                        "id": "call-net-1",
                                        "type": "function",
                                        "function": {
                                            "name": "run_command",
                                            "arguments": json.dumps({"command": run_script}),
                                        },
                                    }
                                ],
                            }
                        }
                    ]
                }
            elif call_count == 4:
                # Reasoner repair
                return {
                    "choices": [
                        {
                            "message": {
                                "role": "assistant",
                                "content": "Repairing with mock data after network denial.",
                                "tool_calls": [
                                    {
                                        "id": "call-net-2",
                                        "type": "function",
                                        "function": {
                                            "name": "write_file",
                                            "arguments": '{"filepath": "data.txt", "content": "MOCK_DATA"}',
                                        },
                                    }
                                ],
                            }
                        }
                    ]
                }
            else:
                return {
                    "choices": [
                        {
                            "message": {
                                "role": "assistant",
                                "content": "Repaired the denial in the isolated sandbox. PASS",
                            }
                        }
                    ]
                }

        orchestrator.execution_loop.complete_chat_fn = complete_chat_mock
        try:
            verification_result = orchestrator.execute_sequential_thinking_loop(task)
        finally:
            orchestrator.execution_loop.complete_chat_fn = original_complete_chat

        # The script reached the backend once, and the backend blocked it.
        assert mock_backend.statuses_for(run_script) == [BROKER_BLOCKED]
        # The violation was normalised into a critique and handed to the model:
        # these strings originate in the backend payload, not in any mocked turn.
        history_str = str(orchestrator.conversation_history)
        assert "Error: Critique received." in history_str
        assert VIOLATION_EVIDENCE_ID in history_str
        assert "network_access_denied" in history_str
        assert "network-isolated" in history_str
        # The loop ran to the mocked final turn rather than aborting on the violation.
        assert "PASS" in verification_result
        assert (tmp_path / "data.txt").read_text(encoding="utf-8").strip() == "MOCK_DATA"

    def test_sandbox_application_synthesis_with_repair(self, tmp_path):
        """
        Verifies that the orchestrator can synthesize a simple multi-file Python application
        (a CLI script and its test) while correctly navigating a *simulated* network-isolated
        SandboxViolation raised by the mock backend (AC-NS-3; AC-CE-1 is not enforced in
        production).
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
        original_complete_chat = orchestrator.execution_loop.complete_chat_fn

        call_count = 0

        def complete_chat_mock(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                # Planner response
                return {
                    "choices": [
                        {
                            "message": {
                                "role": "assistant",
                                "content": "Plan: 1. Write app.py 2. Run pytest 3. Repair if network denied.",
                            }
                        }
                    ]
                }
            elif call_count == 2:
                # First attempt: write the live file
                return {
                    "choices": [
                        {
                            "message": {
                                "role": "assistant",
                                "content": "Writing the file with requests.",
                                "tool_calls": [
                                    {
                                        "id": "call-1",
                                        "type": "function",
                                        "function": {
                                            "name": "write_file",
                                            "arguments": (
                                                '{"filepath": "weather_cli/app.py", '
                                                '"content": "import requests\\nrequests.get(\\"http://example.com/api\\")"}'
                                            ),
                                        },
                                    }
                                ],
                            }
                        }
                    ]
                }
            elif call_count == 3:
                # Second attempt: run the file
                return {
                    "choices": [
                        {
                            "message": {
                                "role": "assistant",
                                "content": "Running tests.",
                                "tool_calls": [
                                    {
                                        "id": "call-2",
                                        "type": "function",
                                        "function": {
                                            "name": "run_command",
                                            "arguments": '{"command": "python -m pytest weather_cli/app.py"}',
                                        },
                                    }
                                ],
                            }
                        }
                    ]
                }
            elif call_count == 4:
                # Third attempt: fix the file (after SandboxViolation)
                return {
                    "choices": [
                        {
                            "message": {
                                "role": "assistant",
                                "content": "Fixing SandboxViolation.",
                                "tool_calls": [
                                    {
                                        "id": "call-3",
                                        "type": "function",
                                        "function": {
                                            "name": "write_file",
                                            "arguments": (
                                                '{"filepath": "weather_cli/app.py", "content": "MOCK_DATA = 42"}'
                                            ),
                                        },
                                    }
                                ],
                            }
                        }
                    ]
                }
            elif call_count == 5:
                # Fourth attempt: run tests again
                return {
                    "choices": [
                        {
                            "message": {
                                "role": "assistant",
                                "content": "Running tests on mock.",
                                "tool_calls": [
                                    {
                                        "id": "call-4",
                                        "type": "function",
                                        "function": {
                                            "name": "run_command",
                                            "arguments": '{"command": "python -m pytest weather_cli/app.py"}',
                                        },
                                    }
                                ],
                            }
                        }
                    ]
                }
            else:
                # Stop tool calls
                return {
                    "choices": [
                        {
                            "message": {
                                "role": "assistant",
                                # Deliberately does not name the violation: the history
                                # assertions below must be satisfied by the backend's
                                # critique, never by this scripted turn.
                                "content": "Done testing. I replaced the network call with MOCK_DATA. PASS",
                            }
                        }
                    ]
                }

        orchestrator.execution_loop.complete_chat_fn = complete_chat_mock

        try:
            verification_result = orchestrator.execute_sequential_thinking_loop(task)
        finally:
            orchestrator.execution_loop.complete_chat_fn = original_complete_chat

        # Two brokered test runs: the first hit the simulated capability violation,
        # the second (after the repair) reached the real backend and was not
        # blocked. This is the evidence the repair worked; the mocked model's own
        # "PASS" text could not distinguish a repaired run from an unrepaired one.
        statuses = mock_backend.statuses_for("python -m pytest weather_cli/app.py")
        assert len(statuses) == 2, statuses
        assert statuses[0] == BROKER_BLOCKED
        assert statuses[1] != BROKER_BLOCKED

        # Ensure the SandboxViolation was normalised and passed to the agent; the
        # evidence id can only have come from the backend payload.
        history_str = str(orchestrator.conversation_history)
        assert "Error: Critique received." in history_str
        assert VIOLATION_EVIDENCE_ID in history_str
        assert "network_access_denied" in history_str
        assert "network-isolated" in history_str

        # The loop ran to the mocked final turn, and the repaired file is what
        # the second run executed.
        assert "PASS" in verification_result
        assert "MOCK_DATA = 42" in (app_dir / "app.py").read_text(encoding="utf-8")
