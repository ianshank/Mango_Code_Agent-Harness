"""What a per-directory ``AGENTS.md`` claims, checked against its own directory.

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

C-ADOC-5: this module, :mod:`agents_doc`, :mod:`agents_doc_policy`,
:mod:`agents_doc_discovery` and :mod:`agents_doc_mermaid` are each a
``protected_paths`` entry, on the same footing as every other validator here. A
gate whose own source can be relaxed without review is a gate that reports on
itself; `test_protected_path_liveness.py` holds all five.

The seam against :mod:`agents_doc` is *what is true* against *how it is asked
and reported*, and the direction is the point: a command line sits at the top of
an import graph, never under the checks it drives. An earlier arrangement had
:mod:`agents_doc` delegate upward to a command-line module that imported these
checks back, which closed a cycle `test_import_direction.py` refuses. Callers
still import the whole gate from :mod:`agents_doc`, which re-exports every name
here, so the split stays an implementation detail.

Two boundaries are built in rather than remembered. C-ADOC-2: a persona
directory (``.mango/agents/``, any ``harness/*/agents/``) holds no source file,
so discovery never reaches it, and none is named in ``additional_directories``
-- their ``*.md`` namespace *is* the persona set, held to an exact membership
by several existing assertions. C-ADOC-3: where this gate needed to reach
further it derives the extra paths from the same policy rather than widening an
existing gate's exclusion list, so no rule already in place is loosened.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from datetime import date
from pathlib import Path

try:
    from harness.shared.agents_doc_discovery import iter_documents, waiver_findings
    from harness.shared.agents_doc_mermaid import MERMAID_BLOCK, mermaid_findings
    from harness.shared.agents_doc_policy import AgentsDocConfig, load_config
except ImportError:  # sibling import when this dir is sys.path[0]
    from agents_doc_discovery import (  # type: ignore[no-redef]
        iter_documents,
        waiver_findings,
    )
    from agents_doc_mermaid import MERMAID_BLOCK, mermaid_findings  # type: ignore[no-redef]
    from agents_doc_policy import AgentsDocConfig, load_config  # type: ignore[no-redef]

logger = logging.getLogger(__name__)

#: A persona declares its scope on one line beginning ``**Scope:**``. Owned here
#: so the convention has exactly one definition; `test_documentation_claims`
#: imports it rather than carrying a second copy that could drift.
SCOPE_LINE = re.compile(r"^\*\*Scope:\*\*(.*)$", re.M)
BACKTICKED = re.compile(r"`([^`]+)`")
REVIEWED_LINE = re.compile(r"^\*\*Reviewed:\*\*\s*(\S+)\s*$", re.M)
KEY_FILES_HEADING = re.compile(r"^##\s+Key files\s*$", re.M)
NEXT_HEADING = re.compile(r"^##\s+", re.M)
#: One `key: value` line of a subagent's YAML frontmatter. Deliberately not a
#: YAML parser: the only keys that decide whether Claude Code loads the file
#: are flat scalars, and a parser would add a dependency to a stdlib gate.
FRONTMATTER_KEY = re.compile(r"^([A-Za-z_][\w-]*):\s*(.*)$")


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


def is_regular_in(directory: Path, name: str) -> bool:
    """A regular file directly under `directory`, reached without following a link.

    Containment alone did not enforce the rule DEC-070 states. That decision
    rejected a symlinked ``AGENTS.md``/``CLAUDE.md`` outright, for Windows
    checkouts where ``core.symlinks`` is off by default -- but an *in-tree* link
    such as ``pkg/CLAUDE.md -> pkg/real.md`` resolves inside and compares equal,
    so `contains()` accepted exactly the shape the decision refuses. A link is
    refused here whether or not its target escapes; when it does escape,
    `contains()` refuses it too.
    """
    candidate = directory / name
    return not candidate.is_symlink() and candidate.is_file() and contains(directory, name)


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
    if not is_regular_in(directory, config.companion_filename):
        # DEC-070 rejected a symlinked companion for Windows portability; this
        # makes that decision mechanical. Containment alone was not enough: an
        # in-tree link resolves inside and compared equal, so the shape the
        # decision refuses still passed.
        return [f"{relative}/{config.companion_filename}: must be a regular file in this directory, not a link"]
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
    if not directory.exists():
        return []  # a repository need not define subagents at all
    if not directory.is_dir():
        return [f"{config.subagent_directory}: configured as the subagent directory but is not a directory"]
    if not contains(repo_root, config.subagent_directory):
        outside = (
            f"{config.subagent_directory}: resolves outside the checkout, "
            "so this audit would read a tree this repository does not own"
        )
        return [outside]
    findings: list[str] = []
    for path in sorted(directory.glob("*.md")):
        relative = f"{config.subagent_directory}/{path.name}"
        if not is_regular_in(directory, path.name):
            # The directory being contained said nothing about its children: a
            # linked `rogue.md` was read and parsed like any other definition.
            findings.append(f"{relative}: must be a regular file in this directory, not a link")
            continue
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


def configured_path_findings(repo_root: Path, config: AgentsDocConfig) -> list[str]:
    """Configured directories that do not resolve to a directory inside the checkout.

    The load-time rule in :mod:`agents_doc_policy` is lexical, so it cannot see
    a symlink: `additional_directories: ["docs_link"]` is a plain relative name
    until something resolves it, and then the audit walks whatever it points
    at. Lexical is still right at load time -- a configured directory may
    legitimately not exist yet, and `waiver_findings` reports that rather than
    crashing -- so the resolution half belongs here, where the root is known.
    """
    findings: list[str] = []
    for name in sorted({*config.additional_directories, *config.waived_directories}):
        if (repo_root / name).exists() and not contains(repo_root, name):
            findings.append(f"{name}: configured in the policy but resolves outside the checkout")
    for name in sorted(config.additional_directories):
        # The `continue` in `audit()` skips anything `contains()` refuses, and
        # `contains()` refuses a path that does not resolve *at all* as readily as
        # one that resolves outside -- so a typo in `additional_directories` was
        # skipped in silence, and a satisfied floor made the whole audit return
        # `[]`. A waived directory already gets this check in `waiver_findings`;
        # an additional one had nothing.
        if not (repo_root / name).is_dir():
            findings.append(
                f"{name}: named in additional_directories but is not a directory in this checkout, "
                "so nothing would be judged for it"
            )
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
    findings = (
        waiver_findings(repo_root, resolved)
        + configured_path_findings(repo_root, resolved)
        + subagent_findings(repo_root, resolved)
        if only is None
        else []
    )
    present = 0
    for relative, path in iter_documents(repo_root, resolved):
        if only is not None and relative != only:
            continue
        directory = repo_root / relative
        if not contains(repo_root, relative):
            # Reported by `configured_path_findings`; skipped here so the
            # external document is not read as well as reported. Discovery
            # cannot produce such a directory -- `os.walk` does not follow
            # links -- so the only routes in are the two configured lists.
            continue
        if not path.is_file():
            findings.append(f"{relative}: missing {resolved.filename}")
            continue
        if not is_regular_in(directory, resolved.filename):
            findings.append(f"{relative}/{resolved.filename}: must be a regular file in this directory, not a link")
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
