"""The prompt templates handed to each agent role in the orchestration loop.

Separated from ``mango_mas_orchestrator`` so the templates have one home and the
orchestrator stays inside its 500-line budget -- the same split, for the same
reason, as ``tool_result_format``. Nothing outside the orchestrator referenced
the originals (confirmed by grep), so this is a move rather than a new surface.

Unprotected, same tier as ``tool_schemas``/``tool_result_format``: this module
holds inert string data with no decision content, so nothing here enforces
anything. It's reachable only through the protected orchestrator, the same as
a governance module would be -- but ``governance/**``'s protection is for
modules that decide, not for everything the orchestrator happens to import.
"""
from __future__ import annotations

AUTONOMOUS_AGENT_GUARDRAIL = (
    "YOU ARE AN AUTONOMOUS AGENT. You must follow repository invariants "
    "and fail closed when approval is required."
)

PLANNER_PROMPT_TEMPLATE = (
    "Create a plan for the following task, ensuring no hardcoded values and strict testing: {task}\n"
    f"{AUTONOMOUS_AGENT_GUARDRAIL}"
)

REASONER_PROMPT_TEMPLATE = (
    "Execute the following plan using backward-compatible, modular code. "
    "You MUST use your 'write_file' and 'run_command' tools to actually implement and test it on the filesystem.\n"
    f"{AUTONOMOUS_AGENT_GUARDRAIL} "
    "Use run_command to run the repository's own gates -- pytest, make, ruff, mypy. Commands that "
    "install packages or reach the network are classified as external actions and will be denied; "
    "if you need one, record the need with knowledge_gap_log rather than retrying.\n\n"
    "Plan:\n{plan}"
)

VERIFIER_PROMPT_TEMPLATE = (
    "Verify the generated codebase against our CI gates (ruff, mypy, pytest, vitest). "
    "Use your 'run_command' tool to execute them. Report PASS or FAIL.\n"
    f"{AUTONOMOUS_AGENT_GUARDRAIL}\n\n"
    "Reasoner Output:\n{code_output}"
)
