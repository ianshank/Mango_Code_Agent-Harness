"""The tool schema the orchestrator advertises to the model.

Separated from `mango_mas_orchestrator` so the declaration has one home and the
orchestrator stays inside the 500-line budget. `NEMOTRON_TOOLS` is re-exported
there unchanged: it is part of that module's public surface and several callers
and tests reach it as `orch_module.NEMOTRON_TOOLS`.

What the model is *offered* is decided here; what it is *permitted* is decided by
`agent_authority`, and what actually *runs* is decided by the orchestrator's
dispatcher. The three are deliberately separate -- the schema is advisory, and a
model can name a tool it was never offered.
"""

from __future__ import annotations

from harness.shared.meta_tools import META_TOOLS_SCHEMA

#: Baseline orchestrator tools plus the meta-learning tools.
NEMOTRON_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "write_file",
            "description": "Write or overwrite a file on the filesystem with the provided content.",
            "parameters": {
                "type": "object",
                "properties": {
                    "filepath": {"type": "string", "description": "The path to the file to write."},
                    "content": {"type": "string", "description": "The full content to write to the file."},
                },
                "required": ["filepath", "content"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "read_file",
            "description": (
                "Read a file from the workspace. Returns the content verbatim, with no line-number "
                "prefixes, so the result can be pasted straight into apply_patch's old_text."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "filepath": {"type": "string", "description": "Workspace-relative path to read."},
                    "start_line": {"type": "integer", "description": "First line to return, 1-based. Optional."},
                    "end_line": {"type": "integer", "description": "Last line to return, inclusive. Optional."},
                },
                "required": ["filepath"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "apply_patch",
            "description": (
                "Replace one exact substring in a workspace file, leaving the rest untouched. "
                "old_text MUST appear exactly once in the file; include surrounding lines until it "
                "does. Prefer this over write_file for editing an existing file."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "filepath": {"type": "string", "description": "Workspace-relative path to patch."},
                    "old_text": {"type": "string", "description": "The exact, uniquely-matching text to replace."},
                    "new_text": {"type": "string", "description": "The text to put in its place."},
                },
                "required": ["filepath", "old_text", "new_text"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "run_command",
            "description": "Run a shell command and return its output.",
            "parameters": {
                "type": "object",
                "properties": {"command": {"type": "string", "description": "The shell command to execute."}},
                "required": ["command"],
                "additionalProperties": False,
            },
        },
    },
] + META_TOOLS_SCHEMA
