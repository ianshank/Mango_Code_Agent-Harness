"""The per-directory ``AGENTS.md`` gate: its command line, and its whole surface.

``python -m harness.shared.agents_doc`` is the documented entry point -- root
`CLAUDE.md` and `.github/workflows/scheduled-drift.yml` both name it -- so this
module is where a run lands, and every other name a caller needs is re-exported
from here. Importing the gate is one import; which module a rule happens to live
in is an implementation detail that may move.

The checks themselves are in :mod:`agents_doc_checks`, split out when the
containment fixes pushed one module against ``limits.size_budget_lines``. The
seam is *how this is invoked and reported* against *what is true*, and this half
sits **above** that one: a command line at the top of the import graph, never
underneath the checks it drives. The first attempt had it the other way around --
this module delegating upward to a command-line module that imported the checks
back -- which closed an import cycle `test_import_direction.py` refuses, and
rightly: a module pair that each need the other has no seam, only a split file.

Staleness lives here rather than with the checks for a reason of its own
(C-ADOC-4): it never blocks a pull request. A clock-dependent gate over two
dozen documents turns CI red on a date boundary for a change that touched none
of them, so the weekly drift workflow reports it and `make ci` does not. It sits
beside the command line because that workflow is its only caller.
"""

from __future__ import annotations

import argparse
import logging
import sys
from collections.abc import Iterable, Sequence
from datetime import date, datetime, timezone
from pathlib import Path

try:
    from harness.shared.agents_doc_checks import (
        AgentsDocument,
        audit,
        companion_findings,
        configured_path_findings,
        contains,
        document_findings,
        is_path_like,
        is_regular_in,
        parse_document,
        scope_names,
        subagent_findings,
    )
    from harness.shared.agents_doc_discovery import (
        discover_source_directories,
        iter_documents,
        required_directories,
        source_file_count,
        waiver_findings,
    )
    from harness.shared.agents_doc_mermaid import MERMAID_BLOCK, declared_nodes, mermaid_findings
    from harness.shared.agents_doc_policy import AgentsDocConfig, load_config
    from harness.shared.json_logging import LOG_LEVEL_ENV_VAR, configure_gate_process_logging
    from harness.shared.policy_loader import PolicyError
except ImportError:  # sibling import when this dir is sys.path[0]
    from agents_doc_checks import (  # type: ignore[no-redef]
        AgentsDocument,
        audit,
        companion_findings,
        configured_path_findings,
        contains,
        document_findings,
        is_path_like,
        is_regular_in,
        parse_document,
        scope_names,
        subagent_findings,
    )
    from agents_doc_discovery import (  # type: ignore[no-redef]
        discover_source_directories,
        iter_documents,
        required_directories,
        source_file_count,
        waiver_findings,
    )
    from agents_doc_mermaid import (  # type: ignore[no-redef]
        MERMAID_BLOCK,
        declared_nodes,
        mermaid_findings,
    )
    from agents_doc_policy import AgentsDocConfig, load_config  # type: ignore[no-redef]
    from json_logging import (  # type: ignore[no-redef]
        LOG_LEVEL_ENV_VAR,
        configure_gate_process_logging,
    )
    from policy_loader import PolicyError  # type: ignore[no-redef]

logger = logging.getLogger(__name__)

#: The whole gate, from one import. Names defined in :mod:`agents_doc_checks`,
#: :mod:`agents_doc_discovery` and :mod:`agents_doc_mermaid` are re-exported so a
#: caller never has to know which of them a given rule lives in, and so a later
#: split moves code without moving anybody's import.
__all__ = [
    "MERMAID_BLOCK",
    "AgentsDocument",
    "audit",
    "companion_findings",
    "configured_path_findings",
    "contains",
    "declared_nodes",
    "discover_source_directories",
    "document_findings",
    "is_path_like",
    "is_regular_in",
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


def stale_documents(
    repo_root: Path, config: AgentsDocConfig, max_age_days: int, today: date
) -> list[tuple[str, str, int]]:
    """Documents whose ``**Reviewed:**`` date is older than `max_age_days`.

    C-ADOC-4. Reported, never blocking, and the split is deliberate. *Presence* of the
    date is a blocking rule in :func:`agents_doc_checks.document_findings`, because a document
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


if __name__ == "__main__":  # pragma: no cover - exercised as a subprocess
    sys.exit(main())
