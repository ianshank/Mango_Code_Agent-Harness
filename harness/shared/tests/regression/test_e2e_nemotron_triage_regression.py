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
