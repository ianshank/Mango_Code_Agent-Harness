"""Print the agent memory stores for a human. Read-only; no prompt reads *this*.

The operator counterpart to the meta-tools. ``hypothesis_register`` and
``knowledge_gap_log`` write a durable trail of what the reasoner could not
determine and what it believed on what evidence, and DEC-057 gives that trail as
the reason revision is worth having -- but a record nothing can read is not
evidence. This is the reader, behind ``make memory-show``.

It is deliberately *not* wired into any prompt or gate, and it renders
everything: the unbounded view an operator wants at a terminal, where it costs
no tokens on any run. The reasoner sees the store only through the bounded
``format_hypotheses_for_reasoner`` (DEC-058, spec C-HS-1); a test pins that no
prompt builder imports this module or the unbounded readers it uses.
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path

from harness.shared.memory_view import format_hypotheses_for_review, load_hypotheses
from harness.shared.meta_tools import format_gaps_for_planner, load_open_gaps, resolve_memory_dir


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Print the agent memory stores (gaps and hypotheses).")
    parser.add_argument(
        "--workspace",
        type=Path,
        default=None,
        help="Workspace whose .mango/memory/ to read. Omit for the legacy install-root store.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Show at most this many of each, most recent first. Omit for all.",
    )
    parser.add_argument(
        "--store",
        choices=("all", "gaps", "hypotheses"),
        default="all",
        help="Which store to print (default: all).",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    memory_dir = resolve_memory_dir(args.workspace)
    print(f"Memory store: {memory_dir}")

    if args.store in ("all", "gaps"):
        gaps = load_open_gaps(args.workspace)
        rendered = format_gaps_for_planner(gaps, workspace_dir=args.workspace, limit=args.limit)
        # `format_gaps_for_planner` returns "" for an empty store because it
        # feeds a prompt, where a heading with nothing under it is noise. A
        # human asking to see the store deserves to be told it is empty.
        print(rendered if rendered else "No knowledge gaps recorded.\n")

    if args.store in ("all", "hypotheses"):
        print(format_hypotheses_for_review(load_hypotheses(args.workspace), limit=args.limit))

    return 0


if __name__ == "__main__":  # pragma: no cover - exercised via `make memory-show`
    sys.exit(main())
