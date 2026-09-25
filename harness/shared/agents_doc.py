"""Per-directory ``AGENTS.md`` documents, and the rules that keep them true.

Prose that has drifted from the tree is worse than no prose: it sends someone
looking for a module that moved, with the authority of a checked-in document.
This module is the machine half of that bargain -- it derives which directories
owe a document, parses each one, and reports every claim the tree no longer
backs. Every threshold comes from :mod:`agents_doc_policy`; nothing here
restates a rule that lives elsewhere.

The required set is derived, not transcribed. A hand-typed list is the failure
this exists to prevent: it passes forever while the tree grows around it. So
the floor is *every directory holding at least ``min_source_files`` first-party
sources*, minus a waiver map whose entries must each carry a reason, plus an
``additional`` list for boundaries that are document-worthy but source-light.

Filename choice is DEC-070: ``AGENTS.md`` is the cross-tool standard, and
Claude Code reads it only where no ``CLAUDE.md`` sits at or above it, so each
document ships beside a one-line ``CLAUDE.md`` that imports it.

C-ADOC-5: this module, :mod:`agents_doc_policy` and :mod:`agents_doc_discovery`
are each a ``protected_paths`` entry, on the same footing as every other
validator here. A gate whose own source can be relaxed without review is a gate
that reports on itself; `test_protected_path_liveness.py` holds all three.

Two boundaries are built in rather than remembered. C-ADOC-2: a persona
directory (``.mango/agents/``, any ``harness/*/agents/``) holds no source file,
so discovery never reaches it, and none is named in ``additional_directories``
-- their ``*.md`` namespace *is* the persona set, held to an exact membership
by several existing assertions. C-ADOC-3: where this gate needed to reach
further it derives the extra paths from the same policy rather than widening an
existing gate's exclusion list, so no rule already in place is loosened.
"""

from __future__ import annotations

import argparse
import logging
import re
import sys
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path

try:
    from harness.shared.agents_doc_discovery import (
        discover_source_directories,
        iter_documents,
        required_directories,
        source_file_count,
        waiver_findings,
    )
    from harness.shared.agents_doc_policy import AgentsDocConfig, load_config
    from harness.shared.json_logging import LOG_LEVEL_ENV_VAR, configure_gate_process_logging
    from harness.shared.policy_loader import PolicyError
except ImportError:  # sibling import when this dir is sys.path[0]
    from agents_doc_discovery import (  # type: ignore[no-redef]
        discover_source_directories,
        iter_documents,
        required_directories,
        source_file_count,
        waiver_findings,
    )
    from agents_doc_policy import AgentsDocConfig, load_config  # type: ignore[no-redef]
    from json_logging import LOG_LEVEL_ENV_VAR, configure_gate_process_logging  # type: ignore[no-redef]
    from policy_loader import PolicyError  # type: ignore[no-redef]

logger = logging.getLogger(__name__)

#: A persona declares its scope on one line beginning ``**Scope:**``. Owned here
#: so the convention has exactly one definition; `test_documentation_claims`
#: imports it rather than carrying a second copy that could drift.
SCOPE_LINE = re.compile(r"^\*\*Scope:\*\*(.*)$", re.M)
BACKTICKED = re.compile(r"`([^`]+)`")
REVIEWED_LINE = re.compile(r"^\*\*Reviewed:\*\*\s*(\S+)\s*$", re.M)
KEY_FILES_HEADING = re.compile(r"^##\s+Key files\s*$", re.M)
NEXT_HEADING = re.compile(r"^##\s+", re.M)
MERMAID_BLOCK = re.compile(r"```mermaid\n(.*?)```", re.S)
#: A node declaration: an identifier immediately followed by a shape opener.
#: An approximation, deliberately: the cap it feeds is a legibility budget, not
#: a parser, and over-counting a dense diagram is the safe direction.
MERMAID_NODE = re.compile(r"(?<![\w-])([A-Za-z_][\w-]*)\s*[\[\(\{]")
#: One `key: value` line of a subagent's YAML frontmatter. Deliberately not a
#: YAML parser: the only keys that decide whether Claude Code loads the file
#: are flat scalars, and a parser would add a dependency to a stdlib gate.
FRONTMATTER_KEY = re.compile(r"^([A-Za-z_][\w-]*):\s*(.*)$")

#: Re-exported so the discovery split stays an implementation detail for
#: callers: `agents_doc` remains the one import for the whole gate.
__all__ = [
    "audit",
    "companion_findings",
    "contains",
    "discover_source_directories",
    "document_findings",
    "is_path_like",
    "iter_documents",
    "main",
    "mermaid_findings",
    "parse_document",
    "render_staleness_report",
    "required_directories",
    "scope_names",
    "source_file_count",
    "stale_documents",
    "subagent_findings",
    "waiver_findings",
]


def scope_names(text: str) -> list[str]:
    """Every backticked name on the document's ``**Scope:**`` line."""
    match = SCOPE_LINE.search(text)
    return BACKTICKED.findall(match.group(1)) if match else []


def is_path_like(name: str) -> bool:
    """Whether a scope name is a path claim rather than a technology claim.

    The same test ``test_documentation_claims.unsupported_scope_names`` applies,
    for the same reason: a scope line mixes the two and only one can be
    resolved against a directory. ``harness/node`` says `vitest` truthfully and
    this module has no manifest to judge that -- the Node gate does. So path
    claims are checked, technology claims are left to the stack that can check
    them, and at least one path is required or the line is unfalsifiable.
    """
    return "/" in name or name.startswith(".") or Path(name).suffix != ""


def contains(directory: Path, name: str) -> bool:
    """Whether `name` resolves to something that exists *inside* `directory`.

    Existence alone was the rule, and ``directory / name`` is not containment:
    an absolute name discards the base, so `/etc/passwd` was accepted on any
    scope line, and `../sibling.py` walked out of the directory the document
    describes. R-ADOC-1 says *under* that directory, which is the claim a
    reader takes away; a document that can name a file it does not own is back
    to prose. Resolution follows symlinks, so a link out of the tree is
    refused rather than accepted through its target.
    """
    if Path(name).is_absolute():
        return False
    try:
        root = directory.resolve(strict=True)
        candidate = (directory / name).resolve(strict=True)
    except (OSError, RuntimeError):  # missing, or a symlink loop
        return False
    return candidate == root or root in candidate.parents


@dataclass(frozen=True)
class AgentsDocument:
    """One parsed ``AGENTS.md``."""

    path: Path
    directory: Path
    text: str
    line_count: int
    scope_names: tuple[str, ...]
    key_files: tuple[str, ...]
    reviewed: str | None
    diagrams: tuple[str, ...]


def _key_file_names(text: str) -> tuple[str, ...]:
    """Backticked names in the first column of the ``## Key files`` table.

    Scoped to that section, not the whole document: prose elsewhere names
    modules it does not own, and holding those to existence under *this*
    directory would reject true sentences.
    """
    heading = KEY_FILES_HEADING.search(text)
    if heading is None:
        return ()
    rest = text[heading.end() :]
    following = NEXT_HEADING.search(rest)
    section = rest[: following.start()] if following else rest
    names: list[str] = []
    for line in section.splitlines():
        stripped = line.strip()
        if not stripped.startswith("|"):
            continue
        first_column = stripped.split("|")[1] if len(stripped.split("|")) > 1 else ""
        names.extend(BACKTICKED.findall(first_column))
    return tuple(names)


def parse_document(path: Path, directory: Path) -> AgentsDocument:
    """Read one document into the facts the checks below are written against."""
    text = path.read_text(encoding="utf-8")
    reviewed = REVIEWED_LINE.search(text)
    return AgentsDocument(
        path=path,
        directory=directory,
        text=text,
        line_count=len(text.splitlines()),
        scope_names=tuple(scope_names(text)),
        key_files=_key_file_names(text),
        reviewed=reviewed.group(1) if reviewed else None,
        diagrams=tuple(MERMAID_BLOCK.findall(text)),
    )


def mermaid_findings(diagrams: Sequence[str], config: AgentsDocConfig) -> list[str]:
    """Structural checks the existing bracket-quoting rule cannot make.

    `test_documentation_truth` catches one failure mode -- a bare bracket in a
    label -- leaving an unknown opening keyword, an unbalanced quote and an
    unreadably dense diagram all passing. Each renders as an error box or as
    something nobody can follow, and none is visible until the page is opened.
    """
    findings: list[str] = []
    if len(diagrams) > config.max_diagrams:
        findings.append(f"{len(diagrams)} diagrams; at most {config.max_diagrams} keeps a document scannable")
    for index, body in enumerate(diagrams):
        lines = [line for line in body.splitlines() if line.strip()]
        if not lines:
            findings.append(f"diagram {index} is empty")
            continue
        opening = lines[0].strip()
        # The first whitespace-delimited token, not a prefix: `startswith` accepted
        # `flowchartX LR`, which shares a prefix with `flowchart` and renders as an
        # error box. A check that admits the typo it exists to catch is not a check.
        keyword = opening.split()[0] if opening.split() else opening
        if keyword not in config.diagram_types:
            findings.append(f"diagram {index} opens with {opening!r}, which is not a known mermaid diagram type")
        for lineno, line in enumerate(lines, 1):
            if line.count('"') % 2:
                findings.append(f"diagram {index} line {lineno} has an unbalanced quote: {line.strip()}")
            if line.count("[") != line.count("]"):
                findings.append(f"diagram {index} line {lineno} has unbalanced brackets: {line.strip()}")
        nodes = {match.group(1) for match in MERMAID_NODE.finditer(body)}
        if len(nodes) > config.max_diagram_nodes:
            findings.append(
                f"diagram {index} declares {len(nodes)} nodes; at most {config.max_diagram_nodes} stays legible"
            )
    return findings


def companion_findings(directory: Path, relative: str, config: AgentsDocConfig) -> list[str]:
    """The one-line ``CLAUDE.md`` that makes the document load in Claude Code.

    R-ADOC-3. Claude Code reads ``AGENTS.md`` only where no ``CLAUDE.md`` sits
    at or above it, and this repository has one at the root, so without the
    companion every document here would be inert for the agent it is written for. The body is
    held to exactly the import: anything else is content that belongs in the
    document, where the rest of the checks can see it.
    """
    companion = directory / config.companion_filename
    if not companion.is_file():
        return [f"{relative}: missing {config.companion_filename} importing {config.filename}"]
    body = companion.read_text(encoding="utf-8").strip()
    if body != config.companion_body:
        return [f"{relative}/{config.companion_filename}: body is {body!r}, expected {config.companion_body!r}"]
    return []


def document_findings(document: AgentsDocument, relative: str, config: AgentsDocConfig) -> list[str]:
    """Every claim one document makes that its own directory does not back.

    R-ADOC-1: the claims are checked against the directory itself. R-ADOC-5:
    every finding names the directory and the specific claim, so a failure
    states the fix rather than the symptom.
    """
    findings: list[str] = []
    if len(document.scope_names) < config.min_scope_names:
        findings.append(
            f"{relative}: **Scope:** carries {len(document.scope_names)} backticked names; "
            f"at least {config.min_scope_names} are required so the line says something falsifiable"
        )
    paths = [name for name in document.scope_names if is_path_like(name)]
    for name in paths:
        if not contains(document.directory, name):
            findings.append(f"{relative}: **Scope:** names `{name}`, which does not exist under {relative}")
    if not paths:
        findings.append(
            f"{relative}: **Scope:** names no path under {relative}, so nothing on the line can be checked "
            "against the tree. Name at least one real file or subdirectory"
        )
    if len(document.key_files) > config.max_key_files:
        findings.append(
            f"{relative}: ## Key files lists {len(document.key_files)} entries; at most {config.max_key_files} "
            "keeps the table a summary rather than a second copy of the README tree"
        )
    for name in document.key_files:
        if not contains(document.directory, name):
            findings.append(f"{relative}: ## Key files names `{name}`, which does not exist under {relative}")
    if document.reviewed is None:
        findings.append(f"{relative}: no **Reviewed:** line, so nothing records when this was last checked")
    else:
        try:
            date.fromisoformat(document.reviewed)
        except ValueError:
            findings.append(f"{relative}: **Reviewed:** {document.reviewed!r} is not an ISO date")
    if document.line_count > config.max_lines:
        findings.append(
            f"{relative}: {document.line_count} lines exceeds the {config.max_lines}-line budget; "
            "a longer instruction file measurably loses adherence"
        )
    findings.extend(f"{relative}: {finding}" for finding in mermaid_findings(document.diagrams, config))
    return findings


def subagent_findings(repo_root: Path, config: AgentsDocConfig) -> list[str]:
    """Claude Code subagent definitions whose frontmatter it would silently skip.

    This is the only check here that guards against a *silent* outcome. Claude
    Code discovers a project subagent by reading frontmatter, and a file whose
    opening ``---`` is not on line 1, or whose ``name`` is missing, starts with
    ``-``, or contains ``:``, is treated as ordinary documentation: no error, no
    warning, the agent simply never exists. Every other defect in this module
    announces itself the moment someone reads the file. This one announces
    itself as an agent that does not answer, months later.
    """
    directory = repo_root / config.subagent_directory
    if not directory.is_dir():
        return []
    findings: list[str] = []
    for path in sorted(directory.glob("*.md")):
        relative = f"{config.subagent_directory}/{path.name}"
        lines = path.read_text(encoding="utf-8").splitlines()
        if not lines or lines[0].strip() != "---":
            findings.append(f"{relative}: no opening '---' on line 1, so Claude Code reads it as documentation")
            continue
        try:
            closing = lines.index("---", 1)
        except ValueError:
            findings.append(f"{relative}: frontmatter is never closed with '---'")
            continue
        fields: dict[str, str] = {}
        for line in lines[1:closing]:
            field = FRONTMATTER_KEY.match(line)
            if field is not None:
                fields[field.group(1)] = field.group(2)
        name = fields.get("name", "").strip()
        if not name:
            findings.append(f"{relative}: no 'name', so the subagent is silently skipped")
        elif name.startswith("-") or ":" in name:
            findings.append(f"{relative}: name {name!r} starts with '-' or contains ':', which Claude Code rejects")
        elif name != path.stem:
            findings.append(f"{relative}: name {name!r} does not match the filename, so the file is hard to find")
        if not fields.get("description", "").strip():
            findings.append(f"{relative}: no 'description', so nothing tells Claude when to delegate to it")
    return findings


def audit(repo_root: Path, config: AgentsDocConfig | None = None, only: str | None = None) -> list[str]:
    """Every finding across the repository. Empty means the documents are true.

    ``only`` narrows to one required directory and, with it, drops the
    population floor: an author checking the document they are writing wants
    that document judged, not a reminder that the other twenty-four are still
    in progress. A run without ``only`` is the gate; a run with it is a draft
    check, and nothing in CI passes it.
    """
    resolved = config if config is not None else load_config()
    findings = waiver_findings(repo_root, resolved) + subagent_findings(repo_root, resolved) if only is None else []
    present = 0
    for relative, path in iter_documents(repo_root, resolved):
        if only is not None and relative != only:
            continue
        directory = repo_root / relative
        if not path.is_file():
            findings.append(f"{relative}: missing {resolved.filename}")
            continue
        present += 1
        findings.extend(companion_findings(directory, relative, resolved))
        findings.extend(document_findings(parse_document(path, directory), relative, resolved))
    if only is not None:
        if present == 0 and not findings:
            findings.append(f"{only} is not a required directory; nothing was checked")
        return findings
    if present < resolved.min_documented_directories:
        findings.append(
            f"only {present} directories carry a {resolved.filename}; the floor is "
            f"{resolved.min_documented_directories}. A gate that judges nothing reports success for free"
        )
    logger.info("agents_doc audit: %d directories documented, %d findings", present, len(findings))
    return findings


def stale_documents(
    repo_root: Path, config: AgentsDocConfig, max_age_days: int, today: date
) -> list[tuple[str, str, int]]:
    """Documents whose ``**Reviewed:**`` date is older than `max_age_days`.

    C-ADOC-4. Reported, never blocking, and the split is deliberate. *Presence* of the
    date is a blocking rule in :func:`document_findings`, because a document
    that records nothing about when it was checked is broken the moment it is
    written. *Age* is a clock-dependent fact: gating on it turns unrelated pull
    requests red at a date boundary, on a day nobody touched the document. The
    skills already carry exactly this split, for exactly this reason.
    """
    stale: list[tuple[str, str, int]] = []
    for relative, path in iter_documents(repo_root, config):
        if not path.is_file():
            continue
        reviewed = parse_document(path, repo_root / relative).reviewed
        if reviewed is None:
            continue  # a blocking finding already, not a staleness report
        try:
            age = (today - date.fromisoformat(reviewed)).days
        except ValueError:
            continue  # likewise
        if age > max_age_days:
            stale.append((relative, reviewed, age))
    return stale


def render_staleness_report(stale: Sequence[tuple[str, str, int]], max_age_days: int, filename: str) -> str:
    """A markdown table for the weekly drift issue. Empty when nothing is stale."""
    if not stale:
        return ""
    lines = [
        f"## `{filename}` documents past {max_age_days} days\n",
        "A stale document is one whose claims may no longer match the code it",
        "describes. Re-read it, change what is wrong, and bump `**Reviewed:**`.\n",
        "| Directory | Reviewed | Age (days) |",
        "|---|---|---|",
    ]
    lines.extend(f"| `{relative}` | {reviewed} | {age} |" for relative, reviewed, age in stale)
    return "\n".join(lines) + "\n"


def _render(findings: Iterable[str]) -> str:
    return "\n".join(f"  - {finding}" for finding in findings)


def main(argv: Sequence[str] | None = None) -> int:
    """``python -m harness.shared.agents_doc`` -- the gate outside pytest."""
    parser = argparse.ArgumentParser(description="Audit per-directory AGENTS.md documents.")
    parser.add_argument("--repo-root", type=Path, default=Path.cwd())
    parser.add_argument("--policy", type=Path, default=None, help="governance-policy.json to read thresholds from")
    parser.add_argument("--max-lines", type=int, default=None, help="override agents_doc.max_lines")
    parser.add_argument("--list", action="store_true", help="print the required directories and exit")
    parser.add_argument("--directory", default=None, help="check one required directory (a draft check, not the gate)")
    parser.add_argument(
        "--stale-since-days",
        type=int,
        default=None,
        help="report documents past this age as markdown and exit 0; never a gate",
    )
    args = parser.parse_args(argv)

    configure_gate_process_logging()
    logger.debug("log level from %s; repo root %s", LOG_LEVEL_ENV_VAR, args.repo_root)
    try:
        config = load_config(args.policy, max_lines=args.max_lines)
    except PolicyError as error:
        logger.error("[FAIL] agents_doc policy: %s", error)
        return 1

    if args.list:
        for relative in required_directories(args.repo_root, config):
            print(relative)
        return 0

    if args.stale_since_days is not None:
        # UTC rather than local: the report runs on a scheduled runner, and a
        # horizon that shifts with the runner's timezone is one nobody can reproduce.
        stale = stale_documents(args.repo_root, config, args.stale_since_days, datetime.now(tz=timezone.utc).date())
        report = render_staleness_report(stale, args.stale_since_days, config.filename)
        if report:
            print(report, end="")
        logger.info("%d document(s) past %d days", len(stale), args.stale_since_days)
        return 0

    findings = audit(args.repo_root, config, only=args.directory)
    if findings:
        logger.error("[FAIL] agents_doc: %d findings\n%s", len(findings), _render(findings))
        return 1
    logger.info("[PASS] agents_doc: every required directory carries a true %s", config.filename)
    return 0


if __name__ == "__main__":  # pragma: no cover - exercised via main()
    sys.exit(main())
