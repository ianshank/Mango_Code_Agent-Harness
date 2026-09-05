"""Agent prompt definitions and lifecycle hook constants for Mango MAS."""

from __future__ import annotations

from harness.shared.agent_authority import ACTIVE_TO_CANONICAL

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
    "- NEVER suggest 'python -c'. All code must be written into files using write_file.\n"
    f"{AUTONOMOUS_AGENT_GUARDRAIL}"
)

REASONER_PROMPT_TEMPLATE = (
    "Execute the following plan using backward-compatible, modular code. "
    "You MUST use your 'read_file', 'apply_patch', 'write_file' and 'run_command' tools to actually "
    "implement and test it on the filesystem.\n"
    "Read with read_file rather than 'cat': it returns the file verbatim and does not spawn a shell. "
    "Edit an existing file with apply_patch, whose old_text must match exactly once -- include "
    "surrounding lines until it does. Reserve write_file for new files; rewriting a whole file to "
    "change a few lines is how large files get truncated. Always create new files using write_file "
    "rather than shell redirection.\n"
    f"{AUTONOMOUS_AGENT_GUARDRAIL} "
    "Use run_command to run test gates (e.g. pytest, python <file.py>, python -m unittest <file.py>). "
    "If working in a scratch workspace without a Makefile or Agent.md, directly create and test the target files. "
    "Run each command individually as a single standalone command "
    "(do not chain with '&&', ';', '|', or redirect with '>'). "
    "Commands that install packages or reach the network are classified as external actions and will be denied; "
    "if you need one, record the need with knowledge_gap_log rather than retrying.\n\n"
    "Plan:\n{plan}"
)

VERIFIER_PROMPT_TEMPLATE = (
    "You are the verifier. Inspect the reasoner's output and verify the workspace files.\n"
    "Run the test suite using 'run_command' "
    "(e.g. 'pytest <test_file>', 'python -m unittest <test_file>', 'python <file.py>').\n"
    "If running in a standalone or scratch workspace without a Makefile, DO NOT search for or attempt to read "
    "missing config files (Makefile, pyproject.toml, .ruff.toml, tox.ini). "
    "Directly execute the target test script.\n"
    f"{AUTONOMOUS_AGENT_GUARDRAIL}\n\n"
    "Reasoner Output:\n{code_output}\n\n"
    "Provide a brief evaluation summary and MUST conclude your final response with either "
    "'VERDICT: PASS' or 'VERDICT: FAIL'."
)

__all__ = [
    "AUTONOMOUS_AGENT_GUARDRAIL",
    "PERMITTED_HOOK_NAMES",
    "PLANNER_PROMPT_TEMPLATE",
    "PRE_RUN_HOOK",
    "REASONER_PROMPT_TEMPLATE",
    "TASK_LOG_PREVIEW_CHARS",
    "VERIFIER_PROMPT_TEMPLATE",
]
