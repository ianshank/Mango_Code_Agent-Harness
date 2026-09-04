"""The typed outcome channel on tool results.

The executors return text the model reads. Both transports used to infer how
the call ended from that text -- the dispatcher from "the handler returned",
the MCP server from a prefix table -- and both were wrong in opposite
directions: a refused write graded ``executed`` in one, a successful read of a
file beginning with ``Error:`` graded as a denial in the other (Copilot review
on PR #86). ``tool_result_format.ToolText`` is the same string with the
outcome attached by whoever decided it. These tests pin the channel itself and
each executor's use of it.
"""

from __future__ import annotations

import copy
import json
from dataclasses import dataclass
from pathlib import Path

import pytest

from harness.shared.tool_executors import (
    execute_apply_patch,
    execute_read_file,
    execute_write_file,
)
from harness.shared.tool_result_format import (
    DENIALS,
    DENIED_POLICY,
    EXECUTED,
    FAILED,
    INVALID_ARGUMENTS,
    ToolText,
    denied,
    failed,
    format_execution_result,
    is_permitted,
    tool_outcome,
)


@dataclass(frozen=True)
class _Result:
    status: str
    stdout: str = ""
    stderr: str = ""
    exit_code: int = 0
    reason: str = ""


class TestTheChannelItself:
    def test_a_tool_text_is_the_string_it_wraps(self) -> None:
        text = denied("Error writing file x: refused")
        assert text == "Error writing file x: refused"
        assert isinstance(text, str)
        assert str(text) == "Error writing file x: refused" and type(str(text)) is str
        assert hash(text) == hash("Error writing file x: refused")
        assert json.dumps({"content": text}) == json.dumps({"content": "Error writing file x: refused"})

    def test_the_outcome_rides_on_the_result_and_nowhere_in_its_text(self) -> None:
        assert tool_outcome(denied("Error: no")) == DENIED_POLICY
        assert tool_outcome(failed("Error: no")) == FAILED
        assert tool_outcome(ToolText("Error: no", INVALID_ARGUMENTS)) == INVALID_ARGUMENTS
        assert tool_outcome("Error: this is a file's content") == EXECUTED, "a plain string succeeded"
        assert tool_outcome(ToolText("ok")) == EXECUTED

    def test_a_copy_still_carries_its_outcome(self) -> None:
        text = denied("Error: no")
        assert tool_outcome(copy.deepcopy(text)) == DENIED_POLICY

    def test_only_the_denials_are_not_permitted(self) -> None:
        for outcome in DENIALS:
            assert not is_permitted(outcome)
        assert is_permitted(EXECUTED) and is_permitted(FAILED)
        assert DENIED_POLICY in DENIALS and INVALID_ARGUMENTS in DENIALS


class TestTheBrokerRenderingCarriesItsOutcome:
    def test_a_blocked_command_is_a_denial(self) -> None:
        assert tool_outcome(format_execution_result(_Result("BLOCKED", reason="destructive"))) == DENIED_POLICY
        violation = json.dumps({"violation_type": "network_access_denied", "message": "no"})
        assert tool_outcome(format_execution_result(_Result("BLOCKED", stderr=violation))) == DENIED_POLICY

    def test_a_failed_command_with_a_reason_is_a_failure(self) -> None:
        assert tool_outcome(format_execution_result(_Result("FAILED", reason="timed out"))) == FAILED

    def test_output_is_a_success_whatever_it_says(self) -> None:
        rendered = format_execution_result(_Result("SUCCESS", stdout="Error: printed by the program\n"))
        assert tool_outcome(rendered) == EXECUTED
        assert tool_outcome(format_execution_result(_Result("SUCCESS", exit_code=0))) == EXECUTED


class TestEachExecutorReportsItsOwnDecision:
    def test_write_file(self, tmp_path: Path) -> None:
        assert tool_outcome(execute_write_file(tmp_path, "note.txt", "x")) == EXECUTED
        assert tool_outcome(execute_write_file(tmp_path, ".env", "K=v")) == DENIED_POLICY
        assert tool_outcome(execute_write_file(tmp_path, "../escape.txt", "x")) == DENIED_POLICY
        (tmp_path / "adir").mkdir()
        assert tool_outcome(execute_write_file(tmp_path, "adir", "x")) == FAILED

    def test_read_file(self, tmp_path: Path) -> None:
        (tmp_path / "log.txt").write_text("Error: the file's own first line\n", encoding="utf-8")
        assert tool_outcome(execute_read_file(tmp_path, "log.txt")) == EXECUTED
        assert tool_outcome(execute_read_file(tmp_path, "absent.txt")) == FAILED
        assert tool_outcome(execute_read_file(tmp_path, ".env")) == DENIED_POLICY
        assert tool_outcome(execute_read_file(tmp_path, "log.txt", start_line=0)) == INVALID_ARGUMENTS
        (tmp_path / "adir").mkdir()
        assert tool_outcome(execute_read_file(tmp_path, "adir")) == FAILED

    def test_apply_patch(self, tmp_path: Path) -> None:
        (tmp_path / "f.txt").write_text("one two one\n", encoding="utf-8")
        assert tool_outcome(execute_apply_patch(tmp_path, "f.txt", "two", "2")) == EXECUTED
        assert tool_outcome(execute_apply_patch(tmp_path, "f.txt", "one", "1")) == FAILED, "matched twice"
        assert tool_outcome(execute_apply_patch(tmp_path, "absent.txt", "a", "b")) == FAILED
        assert tool_outcome(execute_apply_patch(tmp_path, ".env", "a", "b")) == DENIED_POLICY

    @pytest.mark.parametrize("relpath", ["Makefile", ".venv/lib/python3.11/site-packages/sitecustomize.py"])
    def test_a_protected_path_is_a_policy_denial_not_a_failure(self, tmp_path: Path, relpath: str) -> None:
        result = execute_write_file(tmp_path, relpath, "x")
        assert tool_outcome(result) == DENIED_POLICY
        assert not (tmp_path / relpath).exists()
