"""Unit and integration tests for the dedicated code generation writing tool (generate_code).

Spec: docs/specs/code-generation-tool.md (AC-CGT-1..AC-CGT-7).
"""

from __future__ import annotations

import logging
from pathlib import Path

import pytest

from harness.shared import mango_mas_orchestrator as orch_module
from harness.shared.agent_authority import tools_for_role
from harness.shared.governance.broker import ExecutionBroker
from harness.shared.tool_executors import (
    authorize_write,
    execute_generate_code,
)
from harness.shared.tool_schemas import NEMOTRON_TOOLS

pytestmark = pytest.mark.governance


class TestCodeGenerationTool:
    """Test suite verifying AC-CGT-1 through AC-CGT-7."""

    def test_generate_code_writes_valid_python(self, tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
        """AC-CGT-1: execute_generate_code writes valid Python code and logs context."""
        caplog.set_level(logging.INFO)
        valid_code = "def add(a: int, b: int) -> int:\n    return a + b\n"
        filepath = "src/math_ops.py"

        result = execute_generate_code(tmp_path, filepath, valid_code)

        assert "Success: Generated" in result
        target = tmp_path / filepath
        assert target.is_file()
        assert target.read_text(encoding="utf-8") == valid_code
        assert any("Successfully generated" in record.message for record in caplog.records)

    def test_generate_code_syntax_error_refuses_write(self, tmp_path: Path) -> None:
        """AC-CGT-2: Syntactically invalid Python is refused before touching disk."""
        invalid_code = "def broken(:\n    pass\n"
        filepath = "src/broken.py"
        target = tmp_path / filepath

        result = execute_generate_code(tmp_path, filepath, invalid_code)

        assert "SyntaxError" in result
        assert not target.exists()

    def test_generate_code_syntax_error_preserves_existing_file(self, tmp_path: Path) -> None:
        """AC-CGT-2: If a file already exists, a syntax error does not alter it."""
        filepath = "src/existing.py"
        original_code = "x = 1\n"
        target = tmp_path / filepath
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(original_code, encoding="utf-8")

        broken_code = "def unclosed_paren(\n"
        result = execute_generate_code(tmp_path, filepath, broken_code)

        assert "SyntaxError" in result
        assert target.read_text(encoding="utf-8") == original_code

    def test_generate_code_denied_on_governed_paths(self, tmp_path: Path) -> None:
        """AC-CGT-3: Targeting .mango/memory or a protected path returns denial and writes 0 bytes."""
        memory_path = ".mango/memory/hypotheses.json"
        code = '[{"id": "forged"}]'

        result = execute_generate_code(tmp_path, memory_path, code)

        assert "Denied" in result or "Error generating code" in result
        assert "inside the agent memory directory" in result
        assert not (tmp_path / memory_path).exists()

        protected_path = "harness/shared/governance-policy.json"
        result_protected = execute_generate_code(tmp_path, protected_path, "{}")
        assert "matches a protected path" in result_protected

    def test_generate_code_refuses_overwrite_when_false(self, tmp_path: Path) -> None:
        """AC-CGT-4: Refuses to overwrite when overwrite=False and file exists."""
        filepath = "src/config.py"
        target = tmp_path / filepath
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("API_VERSION = 1\n", encoding="utf-8")

        new_code = "API_VERSION = 2\n"
        result = execute_generate_code(tmp_path, filepath, new_code, overwrite=False)

        assert "File exists and overwrite is False" in result
        assert target.read_text(encoding="utf-8") == "API_VERSION = 1\n"

    def test_generate_code_confinement_denial(self, tmp_path: Path) -> None:
        """AC-CGT-5: Escaping workspace fails closed with confinement denial."""
        escape_path = "../../etc/shadow_clone.py"
        code = "secret = 'bad'\n"

        result = execute_generate_code(tmp_path, escape_path, code)

        assert "path escapes workspace" in result

    def test_generate_code_requires_write_authority(self) -> None:
        """AC-CGT-6: Lacking write authority refuses write for verifier and planner."""
        broker = ExecutionBroker()

        assert authorize_write(broker, "verifier", "test.py") is not None
        assert authorize_write(broker, "planner", "test.py") is not None
        assert authorize_write(broker, "nemotron-reasoner", "test.py") is None

    def test_generate_code_json_validation(self, tmp_path: Path) -> None:
        """Valid and invalid JSON handling."""
        valid_json = '{"valid": true, "count": 42}'
        result = execute_generate_code(tmp_path, "data.json", valid_json)
        assert "Success: Generated" in result

        invalid_json = '{"invalid": true, count: 42}'
        result_invalid = execute_generate_code(tmp_path, "bad_data.json", invalid_json)
        assert "JSONDecodeError" in result_invalid
        assert not (tmp_path / "bad_data.json").exists()

    def test_generate_code_schema_filtering(self) -> None:
        """Confirm generate_code is in NEMOTRON_TOOLS and filtered by role authority."""
        declared_names = {
            func.get("name")
            for t in NEMOTRON_TOOLS
            if isinstance(t, dict) and isinstance(func := t.get("function"), dict)
        }
        assert "generate_code" in declared_names

        reasoner_names = {t["function"]["name"] for t in tools_for_role("nemotron-reasoner", NEMOTRON_TOOLS)}
        assert "generate_code" in reasoner_names

        verifier_names = {t["function"]["name"] for t in tools_for_role("verifier", NEMOTRON_TOOLS)}
        assert "generate_code" not in verifier_names

        planner_names = {t["function"]["name"] for t in tools_for_role("planner", NEMOTRON_TOOLS)}
        assert "generate_code" not in planner_names

    def test_orchestrator_dispatch_generate_code(self, tmp_path: Path) -> None:
        """Integration test: ToolDispatcher correctly executes generate_code."""
        orch = orch_module.MangoMASOrchestrator(workspace_dir=tmp_path, active_role="nemotron-reasoner")
        dispatcher = orch.execution_loop.dispatcher

        res = dispatcher.tool_handlers["generate_code"](
            {
                "filepath": "generated_module.py",
                "code": "class Service:\n    pass\n",
            }
        )
        assert "Success: Generated" in res
        assert (tmp_path / "generated_module.py").is_file()
