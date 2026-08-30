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
    """Render ``result`` for the model. Always returns a string."""
    if result.status == "BLOCKED":
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
                    return "Error: Critique received.\n" + json.dumps(critique, indent=2)
            except ValueError:
                pass
        return f"Error: Command blocked by policy guard. {result.reason or result.stderr}".strip()

    if result.reason:
        return f"Error: {result.reason}"
    output = result.stdout
    if result.stderr:
        output += "\n[STDERR]\n" + result.stderr
    if not output.strip():
        return f"Command executed with return code {result.exit_code}, but generated no output."
    return output
