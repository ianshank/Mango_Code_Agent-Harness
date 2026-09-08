"""Grade a developer tool by the form it was invoked in, not by its name.

``command_actions._BY_PROGRAM`` maps a whole program family to one action. That
is right for ``cat`` and wrong for any tool that both inspects and rewrites.
``ruff`` was graded ``test_execute`` in every form, so ``ruff format .`` and
``ruff check --fix .`` -- each of which rewrites every Python file it reaches,
in place -- were graded a gate run and ran for every role holding
``test_execute``. Reproduced end to end: ``ruff format .`` driven through
``ExecutionBroker`` as ``implementer`` rewrote
``harness/shared/governance/broker.py``, a path ``write_denial_reason`` refuses
by name, and the broker returned SUCCESS. ``write_targets`` finds no redirect in
such a command, so the write policy was never consulted (DEC-067).

The same table answers the question DEC-013 raises from the other side.
``CLAUDE.md`` mandates ``python -m ruff`` and ``python -m mypy``; both graded
``UNCLASSIFIED_ACTION`` ("python is not a modelled program"), so the form the
contributor guide requires could not execute through the broker while the bare
form it forbids could. One table drives both the bare and the interpreter path,
which is what stops them disagreeing again.

**Why an unbounded rewrite is not ``write``.** A mutating invocation naming
explicit files is a write over those files, and the broker's existing write
policy can refuse each one. A mutating invocation given a directory, a glob or
no operand at all rewrites whatever it finds, so there is no target set to
check -- the same reason ``python -c`` is unmodelled. It therefore resolves to
the caller's unmodelled default rather than to ``write``, and denies.

The existing ``python -m pytest`` and ``python -m pip install`` shape rules in
``command_actions`` are deliberately left where they are: they are correct,
pinned by tests, and model no mutating form, so folding them in here would be
churn against a working gate rather than single-sourcing a disagreement.

Spec: ``docs/specs/attested-execution-isolation.md`` (R-AEI-1).
"""

from __future__ import annotations

import dataclasses
import logging
import re
import typing
from collections.abc import Mapping, Sequence
from types import MappingProxyType

logger = logging.getLogger(__name__)

__all__ = [
    "MUTATING_ACTION",
    "TOOL_FORMS",
    "classify_argv",
    "ToolForm",
    "ToolInvocation",
    "classify_tool_invocation",
    "interpreter_module_invocation",
]

#: The action a rewrite over enumerable files exercises. Named rather than
#: inlined so it is one symbol the authority model can be checked against: it
#: was a literal inside ``_mutating_invocation``, outside ``TOOL_FORMS``, and so
#: outside the reach of the test that asserts every action this module can
#: return is one the PDP can decide (reported by a review bot on PR #122).
MUTATING_ACTION: typing.Final[str] = "write"

#: Characters that make a path operand name more than one file. A mutating
#: invocation over any of these has no enumerable target set.
_GLOB_CHARACTERS: typing.Final[frozenset[str]] = frozenset("*?[]{}")

#: A bounded path operand: no glob, no parent traversal, not absolute, and
#: carrying a file extension. ``.``, ``src`` and ``src/`` all fail it, which is
#: the point -- each names a tree rather than a file.
_BOUNDED_PATH = re.compile(r"^(?!/)(?!.*\.\.)[^\s]*[^/\s]\.[A-Za-z0-9_]+$")

#: Interpreter names that accept ``-m <module>``. Matched against argv[0]'s
#: basename, so ``/usr/bin/python3.12`` resolves like ``python``.
_INTERPRETER = re.compile(r"^(?:python[0-9.]*|py)$")


@dataclasses.dataclass(frozen=True)
class ToolForm:
    """How one tool's action depends on the form it is invoked in.

    ``default_action`` is what the tool does when it only inspects. The
    remaining fields describe the forms that depart from that, so a tool with no
    mutating form is one field long and reads as such.
    """

    #: Action for an invocation that neither rewrites files nor leaves the host.
    default_action: str
    #: Subcommands that rewrite files in place unless a neutralising flag is given.
    mutating_subcommands: frozenset[str] = frozenset()
    #: Flags that make an otherwise inspecting invocation rewrite files.
    mutating_flags: frozenset[str] = frozenset()
    #: Flags that turn a mutating form back into an inspecting one.
    neutralising_flags: frozenset[str] = frozenset()
    #: Flags carrying an action of their own, such as installing packages.
    flag_actions: Mapping[str, str] = dataclasses.field(default_factory=dict)
    #: Subcommands this tool declares, so a leading operand is read as a
    #: subcommand rather than as a path.
    subcommands: frozenset[str] = frozenset()


class ToolInvocation(typing.NamedTuple):
    """The action one invocation exercises, and the paths it would rewrite."""

    action: str
    reason: str
    write_targets: tuple[str, ...] = ()


#: The tools whose action depends on their form. A tool absent here is graded by
#: ``command_actions`` exactly as before, so this table only ever narrows.
TOOL_FORMS: Mapping[str, ToolForm] = MappingProxyType(
    {
        "ruff": ToolForm(
            default_action="test_execute",
            subcommands=frozenset({"check", "format", "rule", "linter", "clean", "version"}),
            mutating_subcommands=frozenset({"format"}),
            mutating_flags=frozenset({"--fix", "--fix-only", "--unsafe-fixes"}),
            # Probed, not assumed. `ruff check --fix --statistics a.py` rewrites
            # the file: `--statistics` changes the report, not the fixing, so
            # treating it as neutralising would have reopened this bypass for
            # anyone who passed it (Copilot review on PR #122). `--diff`,
            # `--no-fix` and `--check` each leave the file byte-identical.
            neutralising_flags=frozenset({"--check", "--diff", "--no-fix"}),
        ),
        "eslint": ToolForm(
            default_action="test_execute",
            # `--fix-type` needs `--fix` to have any effect, so listing it is
            # deliberately over-strict: an unnecessary denial is recoverable and
            # is measured by `denial_rate.py`, a missed rewrite is not. Unlike
            # the ruff rows these were not probed -- eslint is not installed
            # here -- which is itself the reason to keep them conservative.
            mutating_flags=frozenset({"--fix", "--fix-type"}),
            neutralising_flags=frozenset({"--fix-dry-run"}),
        ),
        "mypy": ToolForm(
            default_action="test_execute",
            # `--install-types` shells out to pip, which leaves the machine.
            flag_actions=MappingProxyType({"--install-types": "external_write"}),
        ),
    }
)

#: ``python -m <module>`` forms this table grades. Keyed by module name so the
#: bare and interpreter invocations of one tool cannot drift apart.
_INTERPRETER_MODULES: Mapping[str, str] = MappingProxyType({name: name for name in TOOL_FORMS})


def interpreter_module_invocation(argv: Sequence[str]) -> tuple[str, list[str]] | None:
    """Return ``(tool, tail)`` for ``python -m <tool> ...``, else ``None``.

    Only modules this table models are recognised. ``python -m pytest`` is left
    to the shape rules in ``command_actions`` that already grade it, and any
    other module falls through to the unmodelled default rather than being
    guessed at.
    """
    if not argv or not _INTERPRETER.match(argv[0].rsplit("/", 1)[-1]):
        return None
    try:
        marker = argv.index("-m")
    except ValueError:
        return None
    # Everything between the interpreter and `-m` must be a flag; a bare operand
    # there means the interpreter was given a script and the `-m` belongs to it.
    if any(not token.startswith("-") for token in argv[1:marker]):
        return None
    if marker + 1 >= len(argv):
        return None
    tool = _INTERPRETER_MODULES.get(argv[marker + 1])
    if tool is None:
        return None
    return tool, list(argv[marker + 2 :])


def _is_bounded_path(operand: str) -> bool:
    """Whether ``operand`` names one file this module can hand to a write check."""
    if any(character in operand for character in _GLOB_CHARACTERS):
        return False
    return bool(_BOUNDED_PATH.match(operand))


def classify_tool_invocation(tool: str, tail: Sequence[str], unmodelled_action: str) -> ToolInvocation | None:
    """Grade ``tool`` invoked with ``tail``, or ``None`` if it is not modelled.

    ``None`` means "this module has nothing to say", never "allowed": the caller
    keeps whatever verdict it would have reached without this table.

    ``unmodelled_action`` is injected rather than imported because the action a
    caller denies with is the caller's policy, and importing it from
    ``command_actions`` -- which imports this module -- would close a cycle.
    """
    form = TOOL_FORMS.get(tool)
    if form is None:
        return None

    flags = [token for token in tail if token.startswith("-")]
    operands = [token for token in tail if not token.startswith("-")]
    subcommand = operands[0] if operands and operands[0] in form.subcommands else ""
    paths = operands[1:] if subcommand else operands

    # A flag with an action of its own outranks the form: `mypy --install-types`
    # installs packages whatever else it is asked to do.
    for flag in flags:
        action = form.flag_actions.get(flag.split("=", 1)[0])
        if action is not None:
            logger.debug("tool_forms: %s graded %s by flag %s", tool, action, flag)
            return ToolInvocation(action, f"{tool} {flag} performs that action regardless of subcommand")

    neutralised = any(flag.split("=", 1)[0] in form.neutralising_flags for flag in flags)
    mutating = subcommand in form.mutating_subcommands or any(
        flag.split("=", 1)[0] in form.mutating_flags for flag in flags
    )
    if mutating and not neutralised:
        return _mutating_invocation(tool, subcommand, paths, unmodelled_action)

    named = f"{tool} {subcommand}".strip()
    return ToolInvocation(form.default_action, f"{named} inspects without rewriting")


def _mutating_invocation(tool: str, subcommand: str, paths: Sequence[str], unmodelled_action: str) -> ToolInvocation:
    """A rewriting invocation: ``write`` over enumerable files, else unmodelled.

    Returning ``None`` is not an option here -- the invocation definitely
    rewrites something. What varies is whether the caller can be told *what*,
    and an answer of "anything it finds" is not a write the policy can check.
    """
    named = f"{tool} {subcommand}".strip()
    if paths and all(_is_bounded_path(path) for path in paths):
        logger.debug("tool_forms: %s rewrites %d named file(s)", named, len(paths))
        return ToolInvocation(MUTATING_ACTION, f"{named} rewrites the files it names", tuple(paths))
    logger.warning("tool_forms: %s rewrites an unbounded set of files; grading it unmodelled", named)
    return ToolInvocation(
        unmodelled_action,
        f"{named} rewrites every file it reaches, so there is no write target to check",
    )


def classify_argv(argv: Sequence[str], unmodelled_action: str) -> ToolInvocation | None:
    """Grade a whole ``argv`` by invocation form, bare or ``python -m``.

    The one entry point both callers use: ``command_actions`` for the action and
    ``command_write_targets`` for the files. Two call sites resolving the tool
    name their own way is how the bare and interpreter forms drifted apart in
    the first place.
    """
    if not argv:
        return None
    interpreter = interpreter_module_invocation(argv)
    if interpreter is not None:
        tool, tail = interpreter
    else:
        tool, tail = argv[0].rsplit("/", 1)[-1], list(argv[1:])
    return classify_tool_invocation(tool, tail, unmodelled_action)
