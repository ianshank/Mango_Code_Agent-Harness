"""Which directories owe an ``AGENTS.md``, derived from the tree and the policy.

Split from :mod:`agents_doc` along the seam the `god-file-decomposer` skill
names: *which directories are in scope* and *is this document true* grow for
different reasons and were pushing one module past
``limits.size_budget_lines``. This half answers the first question and knows
nothing about a document's contents.

The set is derived, never transcribed. A hand-typed list of directories is the
failure the gate exists to prevent -- it passes forever while the tree grows
around it. So the floor is every directory holding at least
``min_source_files`` first-party sources, minus a waiver map whose entries must
each carry a reason, plus an ``additional_directories`` list for boundaries
that are document-worthy but source-light (R-ADOC-2).
"""

from __future__ import annotations

import logging
import os
from collections.abc import Iterator
from pathlib import Path

try:
    from harness.shared.agents_doc_policy import AgentsDocConfig
except ImportError:  # sibling import when this dir is sys.path[0]
    from agents_doc_policy import AgentsDocConfig  # type: ignore[no-redef]

logger = logging.getLogger(__name__)


def source_file_count(directory: Path, config: AgentsDocConfig) -> int:
    """First-party source files directly in `directory`, not recursively.

    Not recursive on purpose: a parent would otherwise inherit every child's
    count and the rule would demand a document at the root of any deep tree,
    which is the opposite of scoping instructions to where the edit happens.
    """
    try:
        entries = list(directory.iterdir())
    except OSError:  # pragma: no cover - unreadable dir is not a documentation fact
        return 0
    return sum(1 for f in entries if f.is_file() and f.suffix in config.source_extensions)


def discover_source_directories(repo_root: Path, config: AgentsDocConfig) -> list[str]:
    """Repo-relative directories carrying at least `min_source_files` sources.

    Pruned names are dropped from `dirnames` in place, so `os.walk` never
    descends them. Filtering after `rglob("*")` was correct but materialised
    the whole checkout first: on this repository 96% of the 3,417 directories
    walked were discarded afterwards, and the 194 `node_modules` trees a
    `pnpm install` leaves behind are the common case in CI, not the edge one.

    The repository root is not a candidate, which matches `rglob` -- it yields
    only descendants. Instructions for the root are `CLAUDE.md`, not this gate.
    """
    pruned = set(config.pruned_directory_names)
    found: list[str] = []
    for dirpath, dirnames, _ in os.walk(repo_root):
        dirnames[:] = [name for name in dirnames if name not in pruned]
        directory = Path(dirpath)
        if directory == repo_root:
            continue
        if source_file_count(directory, config) >= config.min_source_files:
            found.append(directory.relative_to(repo_root).as_posix())
    return sorted(found)


def required_directories(repo_root: Path, config: AgentsDocConfig) -> list[str]:
    """The directories that owe a document: discovered, minus waived, plus additional.

    R-ADOC-2: derived from the tree so a directory added later is caught,
    never transcribed as a literal list that passes while the tree grows.
    """
    discovered = set(discover_source_directories(repo_root, config))
    required = (discovered - set(config.waived_directories)) | set(config.additional_directories)
    logger.debug(
        "required directories: %d discovered, %d waived, %d additional, %d required",
        len(discovered),
        len(config.waived_directories),
        len(config.additional_directories),
        len(required),
    )
    return sorted(required)


def waiver_findings(repo_root: Path, config: AgentsDocConfig) -> list[str]:
    """A waiver must name a real directory and carry a reason worth reading.

    Both halves matter. A waiver for a path that no longer exists is a rule
    nobody can evaluate, and a waiver whose reason is "n/a" is an exemption
    granted without one -- the shape `STANDALONE_SKILLS` guards against by the
    same means.
    """
    findings: list[str] = []
    for name, reason in sorted(config.waived_directories.items()):
        if not (repo_root / name).is_dir():
            findings.append(f"{name}: waived but the directory does not exist")
        if len(reason.strip()) < config.min_waiver_reason_chars:
            findings.append(
                f"{name}: waiver reason is {len(reason.strip())} characters; "
                f"at least {config.min_waiver_reason_chars} are required so an exemption states why"
            )
    return findings


def iter_documents(repo_root: Path, config: AgentsDocConfig) -> Iterator[tuple[str, Path]]:
    """Every required directory paired with the path its document should occupy."""
    for relative in required_directories(repo_root, config):
        yield relative, repo_root / relative / config.filename
