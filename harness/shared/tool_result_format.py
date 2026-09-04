"""Render a broker result as the tool message the model receives.

Separated from ``mango_mas_orchestrator`` so the rendering has one home and the
orchestrator stays inside the 500-line budget -- the same split, for the same two
reasons, as ``tool_schemas``. Nothing outside the orchestrator referenced the
private original, so this is a move rather than a new surface.

Kept pure and separate from execution so the four output shapes stay testable
without spawning a process. Note what it drops: on the success path the exit code
does not reach the model, which is why a verdict cannot be recovered from this
string and is derived from the structured result instead (see
``harness.shared.governance.verdict``).
"""
from __future__ import annotations

import json
import typing

# The one first-party import: the status vocabulary, which itself imports
# nothing first-party (C-VP-2), so this module stays one step above the bottom
# of the graph rather than restating the strings it compares against
# (tech-debt-hardening-plan R-TDH-14).
from harness.shared.governance.verdict import BROKER_BLOCKED

#: How a tool call ended, as the dispatcher and the MCP transport log it. One
#: vocabulary, declared where every result is rendered, so the two transports
#: cannot spell the same outcome two ways.
EXECUTED = "executed"
DENIED_POLICY = "denied_policy"
DENIED_ROLE = "denied_role"
UNKNOWN_TOOL = "unknown_tool"
INVALID_ARGUMENTS = "invalid_arguments"
POLICY_LOOKUP_FAILED = "policy_lookup_failed"
FAILED = "failed"
RAISED = "raised"

#: The outcomes in which the call was refused before or by the handler. The
#: rest -- executed, failed, raised -- are calls the harness permitted.
DENIALS = frozenset({DENIED_POLICY, DENIED_ROLE, UNKNOWN_TOOL, INVALID_ARGUMENTS, POLICY_LOOKUP_FAILED})


class ToolText(str):
    """A tool result that knows how it ended.

    Every executor returns a ``str`` the model reads, and every caller appends
    it to a message or writes it to a transport unchanged. The outcome used to
    be inferred back out of that text by prefix (``Error writing file …``), so a
    refused write graded ``executed`` in the dispatcher's event and a successful
    ``read_file`` of a file that happens to begin with ``Error:`` graded as a
    denial in the MCP transport's (Copilot review on PR #86). This is the same
    string with the outcome attached by the executor that made the decision;
    nothing downstream parses the text.

    It *is* a ``str``: equality, hashing, JSON encoding and ``str()`` are the
    plain string's, so no caller changes. Only ``tool_outcome`` reads the
    attribute.
    """

    outcome: str

    def __new__(cls, text: str, outcome: str = EXECUTED) -> ToolText:
        self = super().__new__(cls, text)
        self.outcome = outcome
        return self


def denied(text: str) -> ToolText:
    """The call was refused: a policy, containment or authority decision."""
    return ToolText(text, DENIED_POLICY)


def failed(text: str) -> ToolText:
    """The call was permitted and did not succeed: an I/O error, a missing
    file, a patch that matched zero or several times."""
    return ToolText(text, FAILED)


def tool_outcome(result: object) -> str:
    """The outcome a result carries. A plain string is a result that succeeded:
    the executors only wrap what did not."""
    return result.outcome if isinstance(result, ToolText) else EXECUTED


def is_permitted(outcome: str) -> bool:
    """Whether the harness let the call proceed, whatever became of it after."""
    return outcome not in DENIALS


class _Renderable(typing.Protocol):
    """The shape this needs off a broker result.

    Declared structurally rather than imported, so the module stays at the bottom
    of the import graph and mypy still checks the field types. ``ExecutionResult``
    satisfies it; nothing has to say so.
    """

    @property
    def status(self) -> str: ...

    @property
    def stdout(self) -> str: ...

    @property
    def stderr(self) -> str: ...

    @property
    def exit_code(self) -> int: ...

    @property
    def reason(self) -> str: ...


def format_execution_result(result: _Renderable) -> str:
    """Render ``result`` for the model. Always returns a string; a blocked or
    failed result returns one that carries its outcome (``ToolText``)."""
    if result.status == BROKER_BLOCKED:
        if result.stderr:
            try:
                parsed_violation = json.loads(result.stderr)
                if isinstance(parsed_violation, dict) and "violation_type" in parsed_violation:
                    critique = {
                        "schema_version": parsed_violation.get("schema_version", "1.0"),
                        "failure_type": parsed_violation.get("violation_type", "sandbox_violation"),
                        "evidence_id": parsed_violation.get("evidence_id", "unknown"),
                        "location": "execution_broker",
                        "normalized_message": parsed_violation.get("message", result.reason or result.stderr),
                        "redacted": False,
                    }
                    return denied("Error: Critique received.\n" + json.dumps(critique, separators=(",", ":")))
            except ValueError:
                pass
        return denied(f"Error: Command blocked by policy guard. {result.reason or result.stderr}".strip())

    if result.reason:
        return failed(f"Error: {result.reason}")
    output = result.stdout
    if result.stderr:
        output += "\n[STDERR]\n" + result.stderr
    if not output.strip():
        return f"Command executed with return code {result.exit_code}, but generated no output."
    return output
