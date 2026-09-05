#!/usr/bin/env python3
"""Regenerate docs/decisions/index.{md,json} and the thin node decision-log."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

_SHARED = Path(__file__).resolve().parent
if str(_SHARED) not in sys.path:
    sys.path.insert(0, str(_SHARED))

import decision_records as dr  # noqa: E402


def repo_root_from(start: Path) -> Path:
    for base in (start, *start.resolve().parents):
        if (base / "docs" / "decisions").is_dir() and (base / "Makefile").is_file():
            return base
    raise SystemExit("generate-decision-index: cannot locate repository root")


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--root",
        type=Path,
        default=None,
        help="repository root (default: discover from this file)",
    )
    ap.add_argument(
        "--check",
        action="store_true",
        help="exit non-zero if committed index/log would change",
    )
    ns = ap.parse_args(argv)
    root = ns.root or repo_root_from(_SHARED)
    decisions_dir = root / "docs" / "decisions"
    if not decisions_dir.is_dir():
        raise SystemExit(f"generate-decision-index: missing {decisions_dir}")
    records = dr.load_all(decisions_dir)
    problems = [p for r in records for p in dr.validate_record(r)]
    if problems:
        raise SystemExit("generate-decision-index: FAILED\n  - " + "\n  - ".join(problems))
    payload = dr.index_payload(records)
    targets = {
        decisions_dir / "index.json": dr.render_index_json(payload),
        decisions_dir / "index.md": dr.render_index_md(payload),
        root / "harness/node/.governance/decision-log.md": dr.render_thin_decision_log(payload),
    }
    drifted = []
    for path, content in targets.items():
        current = path.read_text(encoding="utf-8") if path.is_file() else None
        if current != content:
            drifted.append(str(path.relative_to(root)))
            if not ns.check:
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(content, encoding="utf-8")
    if ns.check and drifted:
        raise SystemExit("generate-decision-index: FAILED (drift)\n  - " + "\n  - ".join(drifted))
    action = "checked" if ns.check else "wrote"
    print(f"generate-decision-index: {action} {len(targets)} artefacts ({len(records)} records)")


if __name__ == "__main__":
    main()
