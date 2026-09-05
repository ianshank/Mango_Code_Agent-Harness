"""Programs that execute whatever their arguments name.

``command_actions`` grades a command by its program: ``make`` and ``pnpm`` are
"running the repository's own gates", so they are ``test_execute`` -- an action
every role holds. That grade is only true of the *default* invocation. Two
families of argument turn the same program into an interpreter for text the
agent chose:

* ``make`` reads the makefile it is told to. ``-f GNUmakefile`` runs a file an
  agent wrote; ``-C dir`` runs another tree's makefile; ``--eval`` injects
  makefile text from the command line; ``-I`` redirects ``include``; and a
  ``NAME=value`` argument overrides the variable a recipe expands, so
  ``make PYTEST='curl evil' test-python`` runs ``curl`` and grades as running
  the test suite. Reproduced in the 2026 standards audit (B4): with
  ``GNUmakefile`` unprotected, ``run_command make -f GNUmakefile x`` was
  arbitrary shell for every role, no Python involved.
* ``pnpm exec <x>`` and ``npx <x>`` run ``<x>``. Both were graded
  ``test_execute`` wholesale, so ``<x>`` could be anything.

This module answers the narrow question the classifier needs: is this ``make``
invocation the canonical one, and which program does this ``pnpm exec``/``npx``
delegate to. The grading itself stays in ``command_actions``, whose tables are
the single allowlist; nothing here names a second set of programs.

Spec: ``docs/reports/2026-STANDARDS-AUDIT.md`` (B4);
``docs/specs/agent-containment.md``.
"""

from __future__ import annotations

#: The one makefile ``make`` may be told to read. ``verification.py`` pins
#: ``-f Makefile`` so GNU Make's ``GNUmakefile`` -> ``makefile`` -> ``Makefile``
#: search cannot be shadowed; the classifier accepts exactly the same name, so the
#: harness's own verification command grades as the gate run it is and every other
#: ``-f`` grades as what it is -- running a file the agent chose.
CANONICAL_MAKEFILE = "Makefile"

#: ``make`` options that select which makefile text runs. Long forms accept both
#: ``--opt value`` and ``--opt=value``; short forms accept ``-o value`` and
#: ``-ovalue``. ``-f`` is the only one with a permitted value; the rest are
#: refused outright, because there is no value for which they run *this*
#: repository's gates.
MAKEFILE_OPTIONS = frozenset({"-f", "--file", "--makefile"})
DIRECTORY_OPTIONS = frozenset({"-C", "--directory"})
EVAL_OPTIONS = frozenset({"-E", "--eval"})
INCLUDE_DIR_OPTIONS = frozenset({"-I", "--include-dir"})
#: ``-e`` makes every environment variable override the makefile's own, which
#: is ``NAME=value`` by another route: ``PYTEST=evil make -e test-python`` runs
#: ``evil`` as the test suite without an assignment on make's command line.
ENVIRONMENT_OVERRIDE_OPTIONS = frozenset({"-e", "--environment-overrides"})

#: Long options ``make`` accepts that select no makefile text, spelled in full.
#: GNU getopt_long resolves any unique *prefix* of a long option, so ``--dir=x``
#: reaches make as ``--directory=x`` and ``--ev=`` as ``--eval=`` while a
#: comparison against the full spellings above sees neither (Copilot review on
#: PR #86). A long option is therefore recognised by its exact spelling or not
#: at all, and one recognised nowhere is refused -- an unknown option is a
#: usage error to make anyway, and an abbreviation is one this table must not
#: expand on make's behalf. None of these takes a value that names a file or
#: makefile text; the value of ``--jobs`` and friends is a number or a switch.
HARMLESS_LONG_OPTIONS = frozenset(
    {
        "--always-make",
        "--assume-new",
        "--assume-old",
        "--check-symlink-times",
        "--debug",
        "--dry-run",
        "--help",
        "--ignore-errors",
        "--jobs",
        "--just-print",
        "--keep-going",
        "--load-average",
        "--max-load",
        "--new-file",
        "--no-builtin-rules",
        "--no-builtin-variables",
        "--no-keep-going",
        "--no-print-directory",
        "--old-file",
        "--output-sync",
        "--print-data-base",
        "--print-directory",
        "--question",
        "--quiet",
        "--recon",
        "--silent",
        "--stop",
        "--touch",
        "--trace",
        "--version",
        "--warn-undefined-variables",
        "--what-if",
    }
)

#: The short letters of every refused option above, so a cluster such as
#: ``-nf`` or ``-kC`` is caught rather than read as one harmless flag.
_SELECTING_LETTERS = frozenset(
    opt[1]
    for opt in (
        *MAKEFILE_OPTIONS,
        *DIRECTORY_OPTIONS,
        *EVAL_OPTIONS,
        *INCLUDE_DIR_OPTIONS,
        *ENVIRONMENT_OVERRIDE_OPTIONS,
    )
    if len(opt) == 2
)

#: Programs that run their first non-flag argument as a program.
DELEGATING_PROGRAMS: dict[tuple[str, ...], str] = {
    ("pnpm", "exec"): "pnpm exec",
    ("npx",): "npx",
}


def _option_value(token: str, following: str | None) -> tuple[str, str | None, int]:
    """Split an option token into ``(option, value, tokens_consumed)``.

    ``--file=x`` and ``-fx`` carry their value; ``--file x`` and ``-f x`` take
    the next token. A missing value is ``None`` -- ``make -f`` alone is a
    usage error to make and a refusal here, since "no makefile named" is not
    the canonical one either.
    """
    if token.startswith("--"):
        if "=" in token:
            option, value = token.split("=", 1)
            return option, value, 1
        return token, following, 2
    if len(token) > 2:
        return token[:2], token[2:], 1
    return token, following, 2


def make_denial_reason(args: list[str]) -> str | None:
    """Why ``make <args>`` is not a run of this repository's gates, or ``None``.

    Every token is examined; the first offending one decides. Targets are not
    interpreted -- a target is a name the canonical makefile resolves, and the
    makefile is what this function establishes.
    """
    i = 0
    while i < len(args):
        token = args[i]
        following = args[i + 1] if i + 1 < len(args) else None
        if not token.startswith("-"):
            if "=" in token:
                name = token.split("=", 1)[0]
                return (
                    f"{token!r} overrides make variable {name!r} from the command line, "
                    "replacing whatever the recipe expands it to"
                )
            i += 1
            continue
        if token == "--":
            # Everything after `--` is a target or a variable assignment; the
            # assignment check above still applies to each of them.
            i += 1
            continue
        option, value, consumed = _option_value(token, following)
        if option in MAKEFILE_OPTIONS:
            if value != CANONICAL_MAKEFILE:
                return (
                    f"make is told to read {value!r} rather than {CANONICAL_MAKEFILE!r}; "
                    "only the canonical makefile is a gate run, any other file is a program the agent chose"
                )
            i += consumed
            continue
        if option in DIRECTORY_OPTIONS:
            return f"{option} changes directory before reading a makefile, so it runs another tree's recipes"
        if option in EVAL_OPTIONS:
            return f"{option} injects makefile text from the command line"
        if option in INCLUDE_DIR_OPTIONS:
            return f"{option} changes where included makefiles are resolved"
        if option in ENVIRONMENT_OVERRIDE_OPTIONS:
            return (
                f"{option} lets every environment variable override the recipe's own, "
                "the same effect as a NAME=value argument"
            )
        if token.startswith("--"):
            if option not in HARMLESS_LONG_OPTIONS:
                return (
                    f"{option!r} is not a long option of make spelled in full; make resolves any "
                    "unique prefix (--dir is --directory, --ev is --eval), so an abbreviated or "
                    "unknown long option is refused rather than expanded here"
                )
            # A recognised harmless option never consumes the next token: make
            # treats `--jobs 4` as a switch and a target, and consuming `4`
            # would also swallow a `NAME=value` that follows the option.
            i += 1
            continue
        if len(token) > 2:
            # A short-flag cluster. `-nf Makefile` is legal to make; refusing
            # the cluster rather than parsing it fails closed, and the
            # verification runner spells its flags separately.
            letters = set(token[1:])
            if letters & _SELECTING_LETTERS:
                return f"{token!r} bundles a makefile-selecting flag with others; spell it separately"
        i += 1
    return None


def delegated_argv(argv: list[str]) -> tuple[str, list[str]] | None:
    """The ``(delegator, inner argv)`` a delegating program hands off to.

    ``pnpm exec vitest run`` -> ``("pnpm exec", ["vitest", "run"])``. Any
    option before the program (``npx --yes tsc``, ``npx --package=evil vitest``,
    ``npx -p pkg vitest``) yields an empty inner argv, which the caller grades
    as nothing safe to run: ``--package``/``--call`` change what actually
    executes, and parsing a safe subset is a second allowlist that could drift
    (Copilot review on PR #86). ``None`` when ``argv`` is not a delegation,
    including a bare ``pnpm exec`` with nothing to run.
    """
    if not argv:
        return None
    program = argv[0].rsplit("/", 1)[-1]
    for prefix, label in DELEGATING_PROGRAMS.items():
        if program != prefix[0]:
            continue
        rest = argv[1:]
        if len(prefix) > 1:
            if not rest or rest[0] != prefix[1]:
                continue
            rest = rest[1:]
        if not rest or rest[0].startswith("-"):
            return label, []
        return label, rest
    return None


__all__ = [
    "CANONICAL_MAKEFILE",
    "DELEGATING_PROGRAMS",
    "DIRECTORY_OPTIONS",
    "ENVIRONMENT_OVERRIDE_OPTIONS",
    "EVAL_OPTIONS",
    "HARMLESS_LONG_OPTIONS",
    "INCLUDE_DIR_OPTIONS",
    "MAKEFILE_OPTIONS",
    "delegated_argv",
    "make_denial_reason",
]
