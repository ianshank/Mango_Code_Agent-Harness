"""Tests for harness/shared/tool_result_format.py.

Previously untested directly -- only incidentally referenced by
test_import_direction.py (an import-structure check, not a behavior test)
and regression/test_sandbox_violation_regression.py (which exercises the
critique path only). This exercises every branch of
format_execution_result() directly.
"""

from __future__ import annotations

import json
from dataclasses import dataclass

from harness.shared.tool_result_format import format_execution_result


@dataclass(frozen=True)
class _Result:
    """Minimal stand-in satisfying the _Renderable protocol."""

    status: str
    stdout: str = ""
    stderr: str = ""
    exit_code: int = 0
    reason: str = ""


class TestNonBlockedPath:
    """SUCCESS and FAILED share the same rendering branch in
    format_execution_result() -- only BLOCKED gets special handling (see
    TestBlockedPath below) -- so this class covers both statuses, including
    the FAILED case in test_a_reason_wins_over_stdout."""

    def test_stdout_only(self) -> None:
        assert format_execution_result(_Result("SUCCESS", stdout="hello\n")) == "hello\n"

    def test_stdout_and_stderr_both_included(self) -> None:
        rendered = format_execution_result(_Result("SUCCESS", stdout="out", stderr="warn"))
        assert rendered == "out\n[STDERR]\nwarn"

    def test_no_output_at_all_names_the_exit_code(self) -> None:
        rendered = format_execution_result(_Result("SUCCESS", exit_code=0))
        assert rendered == "Command executed with return code 0, but generated no output."

    def test_whitespace_only_output_counts_as_no_output(self) -> None:
        rendered = format_execution_result(_Result("SUCCESS", stdout="   \n", exit_code=0))
        assert "generated no output" in rendered

    def test_a_reason_wins_over_stdout(self) -> None:
        """A FAILED result with both a reason and stdout must report the
        reason -- the reason is why it failed, and burying it under stdout
        would hide the actionable part from the model."""
        rendered = format_execution_result(_Result("FAILED", stdout="partial output", reason="timed out"))
        assert rendered == "Error: timed out"


class TestBlockedPath:
    def test_plain_policy_denial(self) -> None:
        rendered = format_execution_result(_Result("BLOCKED", reason="destructive command denied"))
        assert rendered == "Error: Command blocked by policy guard. destructive command denied"

    def test_falls_back_to_stderr_when_no_reason(self) -> None:
        rendered = format_execution_result(_Result("BLOCKED", stderr="raw denial text"))
        assert rendered == "Error: Command blocked by policy guard. raw denial text"

    def test_structured_violation_renders_as_a_critique(self) -> None:
        violation = json.dumps(
            {
                "violation_type": "network_access_denied",
                "schema_version": "1.0",
                "evidence_id": "ev-123",
                "message": "outbound connection refused",
            }
        )
        rendered = format_execution_result(_Result("BLOCKED", stderr=violation))
        assert rendered.startswith("Error: Critique received.\n")
        critique = json.loads(rendered[len("Error: Critique received.\n") :])
        assert critique == {
            "schema_version": "1.0",
            "failure_type": "network_access_denied",
            "evidence_id": "ev-123",
            "location": "execution_broker",
            "normalized_message": "outbound connection refused",
            "redacted": False,
        }

    def test_malformed_json_stderr_falls_back_to_generic_denial(self) -> None:
        """Not valid JSON at all -- must not raise, must fall through to the
        plain policy-guard message rather than propagating a JSONDecodeError."""
        rendered = format_execution_result(_Result("BLOCKED", stderr="{not json", reason="denied"))
        assert rendered == "Error: Command blocked by policy guard. denied"

    def test_valid_json_without_violation_type_falls_back(self) -> None:
        """Structurally valid JSON that isn't shaped like a violation record
        must not be mistaken for one."""
        rendered = format_execution_result(
            _Result("BLOCKED", stderr=json.dumps({"some_other_key": "value"}), reason="denied")
        )
        assert rendered == "Error: Command blocked by policy guard. denied"

    def test_json_array_stderr_falls_back(self) -> None:
        """A JSON value that parses but isn't a dict (e.g. a bare list) must
        not be treated as a violation record either."""
        rendered = format_execution_result(_Result("BLOCKED", stderr=json.dumps([1, 2, 3]), reason="denied"))
        assert rendered == "Error: Command blocked by policy guard. denied"
