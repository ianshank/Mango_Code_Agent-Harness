"""Agent prompt definitions and lifecycle hook constants for Mango MAS."""

from __future__ import annotations

from harness.shared.agent_authority import ACTIVE_TO_CANONICAL
from harness.shared.tool_schemas import format_tools_paragraph

# How much of a task string is echoed into log lines (avoids flooding logs
# with full prompts while keeping enough to correlate runs).
TASK_LOG_PREVIEW_CHARS = 100

#: The hook fired once at the start of every agent turn. Named rather than
#: repeated so the allowlist below and the call site cannot drift apart.
PRE_RUN_HOOK = "pre-nemotron-run"

#: Hook names `_run_hook` will execute. Derived from the active roles rather
#: than listed: a role added to `ACTIVE_TO_CANONICAL` gets its post-hook without
#: a second edit, and a list maintained by hand is exactly the thing that goes
#: stale into a permission. Every name here is one this module constructs
#: itself; nothing a caller passes can widen the set.
PERMITTED_HOOK_NAMES = frozenset({PRE_RUN_HOOK} | {f"post-{role}-run" for role in ACTIVE_TO_CANONICAL})

AUTONOMOUS_AGENT_GUARDRAIL = (
    "YOU ARE AN AUTONOMOUS AGENT. You must follow repository invariants and fail closed when approval is required."
)

PLANNER_PROMPT_TEMPLATE = (
    "Create a step-by-step implementation plan for the following task: {task}\n"
    "CRITICAL GOVERNANCE RULES FOR PLAN:\n"
    "- Every test/execution step MUST use a single standalone command "
    "(e.g. 'pytest <file>', 'python <file.py>', 'python -m unittest <file>').\n"
    "- NEVER suggest chained commands with '&&', ';', '|', or redirection '>'.\n"
    "- NEVER suggest 'python -c'. All code must be written into files.\n"
    f"{AUTONOMOUS_AGENT_GUARDRAIL}\n"
    "{open_gaps}"
)

REASONER_PROMPT_TEMPLATE = (
    "Execute the following plan using backward-compatible, modular code. "
    "Use the tools listed in your system prompt to implement and test it on the filesystem.\n"
    f"{AUTONOMOUS_AGENT_GUARDRAIL} "
    "If working in a scratch workspace without a Makefile or Agent.md, directly create and test the target files. "
    "Run each command individually as a single standalone command "
    "(do not chain with '&&', ';', '|', or redirect with '>'). "
    "Commands that install packages or reach the network are classified as external actions and will be denied; "
    "if you need one, record the need with knowledge_gap_log rather than retrying.\n\n"
    # `{open_hypotheses}` is the reasoner's bounded view of its own hypothesis
    # store (`memory_view.format_hypotheses_for_reasoner`, DEC-058). It renders
    # `""` when nothing is open, so the prompt is byte-identical to the
    # pre-DEC-058 one for every workspace without hypotheses; when non-empty
    # it begins with "\n\n", so there is no separator to keep in sync here.
    "Plan:\n{plan}{open_hypotheses}"
)

VERIFIER_PROMPT_TEMPLATE = (
    "You are the verifier. Inspect the reasoner's output and verify the workspace files.\n"
    "Run the test suite using the tools listed in your system prompt "
    "(e.g. 'pytest <test_file>', 'python -m unittest <test_file>', 'python <file.py>').\n"
    "If running in a standalone or scratch workspace without a Makefile, DO NOT search for or attempt to read "
    "missing config files (Makefile, pyproject.toml, .ruff.toml, tox.ini). "
    "Directly execute the target test script.\n"
    f"{AUTONOMOUS_AGENT_GUARDRAIL}\n\n"
    "Reasoner Output:\n{code_output}\n\n"
    "Provide a brief evaluation summary and MUST conclude your final response with either "
    "'VERDICT: PASS' or 'VERDICT: FAIL'."
)


def strip_yaml_frontmatter(text: str) -> str:
    """Drop a leading ``---`` YAML block so IDE-only tool names never reach Nemotron (C-RBT-3)."""
    if not text.startswith("---"):
        return text
    rest = text[3:]
    if rest.startswith("\n"):
        rest = rest[1:]
    end = rest.find("\n---")
    if end == -1:
        return text
    body = rest[end + 4 :]
    return body.lstrip("\n")


def compose_system_prompt(persona: str, tools: list) -> str:
    """Persona body (frontmatter stripped) plus the generated tool paragraph (R-RBT-1)."""
    body = strip_yaml_frontmatter(persona).rstrip()
    return f"{body}\n\n{format_tools_paragraph(tools)}"


__all__ = [
    "AUTONOMOUS_AGENT_GUARDRAIL",
    "PERMITTED_HOOK_NAMES",
    "PLANNER_PROMPT_TEMPLATE",
    "PRE_RUN_HOOK",
    "REASONER_PROMPT_TEMPLATE",
    "TASK_LOG_PREVIEW_CHARS",
    "VERIFIER_PROMPT_TEMPLATE",
    "compose_system_prompt",
    "strip_yaml_frontmatter",
]
