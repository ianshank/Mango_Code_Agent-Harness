"""Paths a shell command would create or overwrite.

``command_actions.classify`` answers what *action* a command exercises.
This module answers the prior question the broker also needs: which *paths*
``run_command`` would write, so the same write policy that gates ``write_file``
can refuse ``echo x > .git/hooks/pre-commit`` and ``cp evil .mango/hooks/x.sh``.

Split out when ``command_actions.py`` reached 552 lines against a 500-line
``limits.size_budget_lines`` after the NS-33 ``ruff format`` apply expanded
the file from 472. The seam is the one the broker already draws — it imports
``classify`` and ``write_targets`` as two calls — not a line count: everything
here decides membership of a write-target set, nothing here decides an action.

Spec: ``docs/specs/agent-containment.md``.
"""

from __future__ import annotations

import logging
import re
import shlex
import typing

logger = logging.getLogger(__name__)

#: Write-redirect operators, longest first so ``>>`` / ``>|`` beat a lone ``>``.
#: Built into the compiled patterns by :func:`_compile_redirect_regexes` — do not
#: hard-code these glyphs in match sites; extend this tuple instead.
_REDIRECT_OPERATORS: tuple[str, ...] = (">>", ">|", ">")


def _redirect_operator_pattern(operators: tuple[str, ...] = _REDIRECT_OPERATORS) -> str:
    """Alternation of ``operators``, longest-first, each ``re.escape``d."""
    ordered = sorted(set(operators), key=len, reverse=True)
    return "|".join(re.escape(op) for op in ordered)


def _compile_redirect_regexes(
    operators: tuple[str, ...] = _REDIRECT_OPERATORS,
) -> tuple[re.Pattern[str], re.Pattern[str], re.Pattern[str]]:
    """Build presence, full-token, and prefix regexes from ``operators``.

    The optional ``[0-9]*|&|<`` prefix covers fd-numbered forms (``2>>``),
    ``&>``, and ``<>``. Descriptor duplication (``2>&1``) is excluded by the
    trailing ``(?!&[0-9-])`` lookahead on the presence pattern and by the
    ``tail.startswith("&")`` check in :func:`write_targets`.

    Mid-token forms such as ``x>>out.txt`` / ``x>|out.txt`` are handled by the
    presence pattern matching the *full* operator (longest first), so the
    filename tail is ``out.txt`` rather than ``>out.txt`` / ``|out.txt``.
    """
    ops = _redirect_operator_pattern(operators)
    # Presence / mid-token: match the full operator so ``x>>out`` yields
    # tail ``out``, not ``>out``.
    presence = re.compile(rf"(?:{ops})(?!&[0-9-])")
    # Entire token is an operator (filename is the next argv entry).
    full = re.compile(rf"^(?:[0-9]*|&|<)(?:{ops})$")
    # Operator at start of token with filename glued on (``2>f``, ``>>f``).
    prefix = re.compile(rf"^(?:[0-9]*|&|<)(?:{ops})")
    return presence, full, prefix


# Previous presence form was ``(?<!>)>(?!&[0-9-])`` — a single ``>`` token.
# That made every mid-token ``>>`` / ``>|`` report a wrong path (``>out`` /
# ``|out``). Operators are now driven by ``_REDIRECT_OPERATORS``.
_REDIRECT, _REDIRECT_OP, _REDIRECT_PREFIX = _compile_redirect_regexes()

#: Programs whose non-flag arguments name files they create or overwrite. Their
#: targets go through the same write policy as the write tool, so `cp evil
#: .mango/hooks/x.sh` is refused for the same reason `write_file` would refuse it.
WRITE_TARGET_PROGRAMS: typing.Mapping[str, int] = {
    # program -> index of the first argument that is a write target
    "cp": 1,
    "mv": 1,
    "tee": 0,
    "touch": 0,
    "mkdir": 0,
    "install": 1,
}


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
            # but shlex does not, e.g. `foo>bar` / `x>>out.txt` / `x>|out.txt`.
            inner = _REDIRECT.search(token)
            match = inner if inner and inner.end() < len(token) else None
        if match is not None:
            # `>file` written without a space, or `2>file`, or mid-token forms.
            tail = token[match.end() :]
            if tail and not tail.startswith("&") and tail not in discard_targets:
                targets.append(tail)

    program = argv[0].rsplit("/", 1)[-1] if argv else ""
    start = WRITE_TARGET_PROGRAMS.get(program)
    if start is not None:
        operands = [a for a in argv[1:] if not a.startswith("-") and not _REDIRECT.search(a)]
        targets.extend(operands[start:] if start else operands)
    if targets and logger.isEnabledFor(logging.DEBUG):
        # Counts only — never argv / program / command / path text (model-
        # supplied; may carry secrets). Basename length is a coarse shape hint
        # without echoing the name.
        logger.debug(
            "write_targets: %d path(s); program_basename_len=%d",
            len(targets),
            len(program),
        )
    return targets
