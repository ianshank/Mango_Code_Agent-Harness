#!/usr/bin/env python3
"""Derive the protected-path attestation table instead of counting it by hand.

`validate_invariants.check_protected_paths` fails a PR that touches a protected
path unless `ALLOW_GITHUB_CHANGES=1`, which CI derives from the `infra-reviewed`
label; `harness/CONTRACT.md` requires the PR description to carry a per-file
attestation table so the reviewer applying that label knows what they are
attesting to. Nothing derived that table -- it was transcribed by hand from a CI
log, and on this repository's own governance PR the transcription said thirteen
rows when the validator's set was ten. A table a reviewer trusts, that overstates
what it covers, is the DEC-024 defect class (a claim that its evidence does not
support) reproduced in the control that exists to prevent it.

So the table is produced by the same matcher and the same file discovery the gate
uses, and `--check` verifies a written table against that set. There is exactly
one source of truth for "which protected paths does this change touch": the
`is_protected` predicate and `git_modified_files` in `validate_invariants`, both
imported here rather than reimplemented. A reimplementation would drift from the
gate silently -- which is the whole failure this module removes.

Exit codes: 0 = listed, or the written table matches; 1 = mismatch or unusable
input. `--check` fails closed: a body with no table at all is a failure, not an
empty match, because "no rows" and "no table" are the two states a reviewer must
never see conflated.
"""

from __future__ import annotations

import argparse
import logging
import os
import re
import subprocess
import sys
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

try:
    from harness.shared.validate_invariants import (
        DEFAULT_WORKSPACE_DIR,
        git_modified_files,
        is_protected,
        load_protected_patterns,
    )
except ImportError:  # direct `python harness/shared/governance/attestation.py`
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from validate_invariants import (  # type: ignore[no-redef]
        DEFAULT_WORKSPACE_DIR,
        git_modified_files,
        is_protected,
        load_protected_patterns,
    )

logger = logging.getLogger(__name__)

#: `git_modified_files` reads the PR base from this variable -- it is that
#: function's documented input, which is why the base ref is passed by scoping it
#: rather than by adding a parameter to a protected module.
BASE_REF_ENV = "GITHUB_BASE_REF"

#: A markdown table row's first cell, with the path optionally in backticks.
#: Anchored on the leading pipe so prose mentioning a path in backticks is not
#: mistaken for an attested row.
TABLE_ROW = re.compile(r"^\s*\|\s*`?([^`|]+?)`?\s*\|")

#: Heading that opens the attestation table. A PR description legitimately holds
#: other tables -- a summary of findings, a validation matrix -- and comparing
#: those rows against the protected set would report every one of them as a path
#: the change does not touch. The default matches `harness/CONTRACT.md`'s section
#: name; `--section` takes a different pattern for an adopter that names it
#: something else, so the heading is a convention, not a literal in the gate.
DEFAULT_SECTION = r"^#{1,6}\s.*attestation"

#: Any markdown heading, used to find where the attested section ends.
HEADING = re.compile(r"^#{1,6}\s", re.M)

#: A separator cell (`---`, `:--:`). Its presence is also what identifies the
#: row above it as a header, so both are recognised by shape rather than by
#: position -- a table preceded by prose, or a body carrying several tables,
#: parses the same way.
SEPARATOR_CELL = re.compile(r"^[-: ]+$")


def resolve_base_ref(workspace_dir: Path, explicit: str | None = None) -> str:
    """The branch this change is measured against.

    Never a literal: an adopter fork whose default branch is not `main` would get
    a table derived from a ref that does not exist, and `git diff` against a
    missing ref fails the whole run. Order is explicit flag, then the CI variable,
    then the remote's own published default.
    """
    if explicit:
        return explicit
    from_env = os.environ.get(BASE_REF_ENV)
    if from_env:
        logger.debug("base ref from %s: %s", BASE_REF_ENV, from_env)
        return from_env
    try:
        head = subprocess.check_output(
            ["git", "symbolic-ref", "--short", "refs/remotes/origin/HEAD"],
            encoding="utf-8",
            cwd=workspace_dir,
            stderr=subprocess.DEVNULL,
        ).strip()
    except (subprocess.CalledProcessError, OSError) as exc:
        logger.error(
            "[FAIL] no base ref: pass --base-ref, or set %s, or let the remote publish "
            "refs/remotes/origin/HEAD (git remote set-head origin -a): %s",
            BASE_REF_ENV,
            exc,
        )
        raise SystemExit(1) from exc
    return head.split("/", 1)[-1] if "/" in head else head


@contextmanager
def base_ref_scope(base_ref: str) -> Iterator[None]:
    """Present `base_ref` to `git_modified_files` through its documented input."""
    previous = os.environ.get(BASE_REF_ENV)
    os.environ[BASE_REF_ENV] = base_ref
    try:
        yield
    finally:
        if previous is None:
            os.environ.pop(BASE_REF_ENV, None)
        else:
            os.environ[BASE_REF_ENV] = previous


def protected_changes(workspace_dir: Path, patterns: list[str], base_ref: str) -> list[str]:
    """Protected paths this change touches, in the order the gate reports them.

    Sorted, like `check_protected_paths`, so a table generated here and a failure
    message read from a CI log line up row for row.
    """
    with base_ref_scope(base_ref):
        modified = git_modified_files(workspace_dir)
    return sorted({path for path in modified if is_protected(path, patterns)})


def render(paths: list[str], fmt: str) -> str:
    """`plain` for piping, `markdown` for pasting into a PR description."""
    if fmt == "plain":
        return "\n".join(paths)
    header = ["| Protected path | Why this change touches it |", "| --- | --- |"]
    return "\n".join(header + [f"| `{path}` |  |" for path in paths])


def table_paths(body: str) -> list[str]:
    """Paths named in the first cell of every markdown table body row in `body`.

    A header row is dropped because it sits directly above a separator, not
    because it is the first row: a description that introduces its table with a
    paragraph, or carries more than one table, would otherwise donate its column
    title to the comparison and be reported as a path the change does not touch.
    """
    rows: list[tuple[int, str]] = []
    for lineno, line in enumerate(body.splitlines()):
        match = TABLE_ROW.match(line)
        if match is None:
            continue
        cell = match.group(1).strip()
        if not cell:
            continue
        if SEPARATOR_CELL.match(cell):
            if rows and rows[-1][0] == lineno - 1:
                rows.pop()
            continue
        rows.append((lineno, cell))
    return [cell for _, cell in rows]


def section_body(body: str, pattern: str) -> str | None:
    """The text under the first heading matching `pattern`, up to the next heading.

    None when no heading matches, which the caller treats as a failure rather
    than as an empty section: a description with no attestation section has not
    attested to anything, and reading the whole body instead would silently
    compare unrelated tables.
    """
    opening = re.search(pattern, body, re.I | re.M)
    if opening is None:
        return None
    rest = body[opening.end() :]
    following = HEADING.search(rest)
    return rest[: following.start()] if following else rest


def compare(expected: list[str], body: str) -> tuple[list[str], list[str]]:
    """`(missing, unexpected)` -- protected paths absent from the table, and rows naming none.

    A row whose first cell is not a protected path of this change is reported
    rather than ignored: a table listing a path the change does not touch invites
    the reviewer to attest to something that is not there, which is the same
    overstatement as a missing row, pointed the other way.
    """
    written = table_paths(body)
    missing = [path for path in expected if path not in written]
    unexpected = [cell for cell in written if cell not in expected]
    return missing, unexpected


def _check(expected: list[str], body_path: Path, section: str = DEFAULT_SECTION) -> int:
    try:
        body = body_path.read_text(encoding="utf-8")
    except OSError as exc:
        logger.error("[FAIL] could not read %s: %s", body_path, exc)
        return 1
    attested = section_body(body, section)
    if attested is None:
        logger.error(
            "[FAIL] %s has no heading matching %r, so nothing is attested. %d protected path(s) need a table: %s",
            body_path,
            section,
            len(expected),
            ", ".join(expected) or "(none)",
        )
        return 1
    if not table_paths(attested):
        logger.error(
            "[FAIL] %s contains no attestation table. %d protected path(s) need one: %s",
            body_path,
            len(expected),
            ", ".join(expected) or "(none)",
        )
        return 1
    missing, unexpected = compare(expected, attested)
    for path in missing:
        logger.error("[FAIL] protected path not attested: %s", path)
    for cell in unexpected:
        logger.error("[FAIL] attested row names no protected path of this change: %s", cell)
    if missing or unexpected:
        logger.error(
            "[FAIL] attestation table does not match the %d protected path(s) this change touches",
            len(expected),
        )
        return 1
    logger.info("[PASS] attestation table matches all %d protected path(s)", len(expected))
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--workspace", type=Path, default=DEFAULT_WORKSPACE_DIR)
    parser.add_argument("--policy", type=Path, default=None)
    parser.add_argument("--base-ref", default=None, help="branch to diff against; default is the remote's")
    parser.add_argument("--format", choices=("plain", "markdown"), default="markdown")
    parser.add_argument("--check", type=Path, default=None, help="verify this file's table instead of printing one")
    parser.add_argument("--section", default=DEFAULT_SECTION, help="regex for the heading that opens the table")
    args = parser.parse_args(argv)

    policy_path = args.policy or (args.workspace / "harness" / "shared" / "governance-policy.json")
    patterns = load_protected_patterns(policy_path)
    base_ref = resolve_base_ref(args.workspace, args.base_ref)
    expected = protected_changes(args.workspace, patterns, base_ref)
    logger.debug("base_ref=%s protected=%d", base_ref, len(expected))

    if args.check is not None:
        return _check(expected, args.check, args.section)

    if not expected:
        logger.info("[PASS] this change touches no protected path; no attestation is required")
        return 0
    print(render(expected, args.format))
    return 0


if __name__ == "__main__":
    try:
        from harness.shared.json_logging import resolve_log_level
    except ImportError:  # pragma: no cover - exercised by the standalone-script test
        sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
        from json_logging import resolve_log_level  # type: ignore[no-redef]
    logging.basicConfig(level=resolve_log_level(), format="%(levelname)s: %(message)s")
    sys.exit(main())
