"""What files a shell word can reach, after the shell has finished with it.

``process_backend`` runs every command through ``bash -c``, so a program never
receives the argument the model typed: the shell strips its quotes, resolves its
backslashes, expands its braces and expands its globs first. A check written
against the command *text* is therefore checking a string that no filesystem
call will ever see, and four spellings of one read proved it -- ``cat '.env'``,
``cat ".env"``, ``cat \\.env`` and ``cat {.env,README.md}`` each opened the real
file while grading ``read``, the action every role holds.

This module is the other half of that contract: ``command_actions`` decides what
a command *does*, and this decides what its words can *reach*. Splitting them is
not cosmetic -- the reaching question is the one that keeps acquiring shell
semantics (globs, then braces, then whatever bash does next), and it now carries
its own tests and its own bounds instead of growing inside the classifier until
that file passed its size budget.

Spec: ``docs/specs/code-quality-tech-debt-plan.md`` (R-CQ-3).
"""

from __future__ import annotations

import fnmatch
import re
import typing

from harness.shared.read_policy import is_credential_filename

#: A shell glob character. `bash -c` expands these before the program sees them
#: (`process_backend` runs every command through a shell), so an argument is not
#: the filename it appears to be -- `.en?` is whatever `.en?` matches, and on this
#: repository that is `.env`.
#:
#: Finding *where* a wildcard ends needs more than this character class, because
#: `[` opens a bracket class that ends at its `]`. See `_glob_tokens`.
_GLOB_CHARS = re.compile(r"[*?\[]")

#: A brace expression bash expands into several words before it globs. Braces are
#: neither a glob character nor a command chain, so `cat {.env,README.md}` was
#: graded on a token no filesystem check ever sees: it is not `.env`, it *becomes*
#: `.env README.md`. Verified against a real shell, not inferred.
_BRACE = re.compile(r"\{([^{}]*,[^{}]*)\}")

#: Bounds on that expansion. A brace expression nests and multiplies -- `{a,b}`
#: three levels deep is 8 words, ten levels is 1024 -- and the input is a
#: model-supplied string. `classify` runs before the broker's timeout, so an
#: unbounded expansion here is the stall `MAX_COMMAND_BYTES` exists to prevent,
#: one layer down. Exceeding either bound is not a pass: the caller grades the
#: command `UNCLASSIFIED_ACTION`, because a command whose word list cannot be
#: enumerated cannot be shown to name no credential.
_BRACE_EXPANSION_LIMIT = 64
_BRACE_DEPTH_LIMIT = 4

#: Shortest literal suffix that counts as committing to a credential name, so
#: `*.pem` is graded and `*.py` is not. Two characters: `.npmrc` and `.netrc` end
#: in `rc`, and a suffix rule that could not see them would leave the shortest
#: real credential ending outside the check.
_GLOB_TAIL_MIN = 2
#: Concrete filenames standing in for the classes ``CREDENTIAL_FILENAME_PATTERN``
#: describes. A glob is matched against these rather than against the pattern
#: because deciding whether two patterns *can* describe the same string is regex
#: intersection; deciding whether one glob matches one filename is ``fnmatch``.
#:
#: They are representatives, not a second policy: every entry is asserted to match
#: ``CREDENTIAL_FILENAME_PATTERN`` by ``test_representatives_match_the_read_policy``,
#: so a name class added to the alternation without a representative here is a
#: failing test rather than a silent gap.
_CREDENTIAL_REPRESENTATIVES = (
    ".env", ".env.local", ".netrc", ".npmrc", ".pypirc", "id_rsa", "id_dsa", "key.pem",
)


def _expand_braces(token: str) -> list[str] | None:
    """The words bash produces from ``token``, or ``None`` if it cannot be bounded.

    Brace expansion happens *before* globbing and before the program is executed,
    so a token containing one is not a filename at all -- it is a word list. A
    token with no comma inside braces (``--format={%h}``) expands to itself and
    is returned unchanged, which is why ordinary flag values are unaffected.
    """
    results = [token]
    for _ in range(_BRACE_DEPTH_LIMIT):
        expanded: list[str] = []
        changed = False
        for item in results:
            match = _BRACE.search(item)
            if match is None:
                expanded.append(item)
                continue
            changed = True
            for alternative in match.group(1).split(","):
                expanded.append(item[: match.start()] + alternative + item[match.end() :])
        if not changed:
            return results
        if len(expanded) > _BRACE_EXPANSION_LIMIT:
            return None
        results = expanded
    # Still expanding after the depth bound: the word list is not enumerable here.
    return None if _BRACE.search("".join(results)) else results


class WordListNotEnumerable(Exception):
    """The words a token expands to cannot be listed within this module's bounds.

    Distinct from "this word names a credential", and deliberately not folded
    into it. ``credential_word_reason`` used to return an ordinary reason string
    for a brace expression past ``_BRACE_EXPANSION_LIMIT``, and the caller turned
    every non-``None`` reason into ``secret_access`` -- so a command nobody had
    shown to touch a credential was graded as one. The two are different
    findings: one asserts a fact about the command, the other admits the check
    could not be completed, and only the second should reach
    ``UNCLASSIFIED_ACTION``. Both are denied to every role today, which is why
    this was a contract defect rather than an exploitable one; it stops being
    only a contract defect the moment ``secret_access`` becomes separately
    grantable, which is the whole point of modelling it as its own action.

    Raised rather than returned so the ``str | None`` contract of the normal
    path stays a straight answer to a straight question. Reported by a review
    bot on the PR that introduced the bound.
    """


def _glob_tokens(segment: str) -> list[tuple[int, int]]:
    """The half-open spans of the wildcard tokens in ``segment``.

    A wildcard is ``*``, ``?``, or a whole bracket class ``[...]`` -- and the
    third is why this exists. The commitment rule below asks what literal text a
    glob *ends* with, and computing that from the last of ``*?[`` puts the split
    at the ``[`` rather than at the ``]`` that closes it: ``*[a-z].pem`` yielded
    the tail ``a-z].pem``, which ends no credential name, so the glob committed
    to nothing and ``cat *[a-z].pem`` graded ``read`` while a real ``bash -c``
    printed ``key.pem``. Same for ``cat *id_[rd]sa`` and ``id_rsa``. Reported by
    a review bot on this PR and reproduced against a real shell before fixing.

    A ``[`` with no closing ``]`` is a literal ``[`` to both bash and ``fnmatch``,
    so it opens no span -- a word of literals is not a glob, and is left to the
    literal rule that already ran.
    """
    spans: list[tuple[int, int]] = []
    index = 0
    length = len(segment)
    while index < length:
        char = segment[index]
        if char in "*?":
            spans.append((index, index + 1))
            index += 1
            continue
        if char == "[":
            close = index + 1
            # `!` or `^` negates, and a `]` in first position is a literal member:
            # `[]]` matches `]`. Both are bash and `fnmatch` semantics.
            if close < length and segment[close] in "!^":
                close += 1
            if close < length and segment[close] == "]":
                close += 1
            while close < length and segment[close] != "]":
                close += 1
            if close < length:
                spans.append((index, close + 1))
                index = close + 1
                continue
        index += 1
    return spans


def credential_word_reason(argv: typing.Sequence[str]) -> str | None:
    """Why a word in ``argv`` names or reaches a credential file, or ``None``.

    Raises ``WordListNotEnumerable`` when a token's expansion exceeds the bounds
    above -- a different answer from either of those two, and the caller grades
    it ``UNCLASSIFIED_ACTION`` rather than ``secret_access``.

    This grades the words the *shell* produces, which is the only list that
    matters: ``process_backend`` runs every command through ``bash -c``, so by
    the time a program sees an argument the shell has already stripped its
    quotes, resolved its backslashes, expanded its braces and expanded its globs.

    The literal rule in ``_BY_SHAPE`` scans the raw command text with
    ``(?:^|[\\s/])`` boundaries instead, and every one of those four
    transformations defeats it: ``cat '.env'``, ``cat ".env"``, ``cat \\.env``
    and ``cat {.env,README.md}`` all graded ``read`` -- the ``cat`` in
    ``_BY_PROGRAM`` -- while reading the real file, confirmed against a real
    shell. ``shlex.split`` already performs the first two transformations, so
    checking its output rather than the text closes quoting and escaping at the
    seam rather than by adding three more patterns to a regex; braces and globs
    are performed here for the same reason.

    Dotglob semantics are honoured because bash's default is to honour them: a
    pattern whose segment does not begin with a literal dot cannot match a
    dotfile, which is what keeps ``*.py`` and ``src/*`` ordinary reads instead of
    collateral denials. The raw-text rule stays where it is: it still catches a
    command ``shlex`` cannot tokenize, and two overlapping checks on one control
    is the shape this module already uses for redirection.
    """
    for token in argv:
        words = _expand_braces(token)
        if words is None:
            raise WordListNotEnumerable(
                f"the brace expression {token!r} expands past the "
                f"{_BRACE_EXPANSION_LIMIT}-word bound, so the files it names cannot be enumerated"
            )
        for word in words:
            for segment in word.split("/"):
                if not segment:
                    continue
                # The word the program will actually receive. Quotes and escapes
                # are already gone; a brace has already been expanded.
                if is_credential_filename(segment):
                    return f"the command names {segment!r}, a credential-bearing file"

                spans = _glob_tokens(segment)
                if not spans:
                    continue
                # Literal text before the first wildcard and after the last one.
                # `spans` ends a bracket class at its `]`, so `*[a-z].pem` tails
                # with `.pem` rather than with `a-z].pem`.
                prefix = segment[: spans[0][0]].lower()
                tail = segment[spans[-1][1] :].lower()
                lowered = segment.lower()
                for name in _CREDENTIAL_REPRESENTATIVES:
                    if name.startswith(".") and not segment.startswith("."):
                        continue  # bash does not expand a bare glob onto dotfiles
                    # Case-folded on both sides. The literal rule carries
                    # `re.IGNORECASE` for the case-preserving filesystems this
                    # harness targets, and a case-sensitive glob rule beside it
                    # meant `cat .ENV` graded `secret_access` while `cat .EN?`
                    # graded `read` -- the inconsistency biting exactly where the
                    # `IGNORECASE` was added to help.
                    if not fnmatch.fnmatchcase(name, lowered):
                        continue
                    # `fnmatch` alone is not enough: `*` matches `id_rsa`, so a
                    # bare `ls src/*` would grade `secret_access` and ordinary
                    # work would be denied. The glob must *commit* to the name --
                    # either the literal it starts with is the start of a
                    # credential name (`.en?`, `id_*`, `.*`), or the literal it
                    # ends with is the end of one (`*.pem`). A wildcard that
                    # commits to neither describes every file in the directory
                    # and is graded on its program, as it was before.
                    if prefix and name.startswith(prefix):
                        committed = prefix
                    elif len(tail) >= _GLOB_TAIL_MIN and name.endswith(tail):
                        committed = tail
                    else:
                        continue
                    return (
                        f"the glob {segment!r} commits to {committed!r} and can expand to "
                        f"{name!r}, a credential-bearing file, so the command is graded on "
                        "what it can read"
                    )
    return None
