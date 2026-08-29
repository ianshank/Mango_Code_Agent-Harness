"""Plan gate: run the decidable defect rules over changed plan documents.

Spec: ``docs/specs/plan-review-framework.md`` (R-PLR-5, R-PLR-6, C-PLR-3).

The third tier of ``make specs``. The structural tier checks that a plan has the
right shape; this one checks that its acceptance criteria could actually fail.

Scoped to plans git reports as modified (R-PLR-5). Landed plans predate the
sections these rules read, and back-filling them would mean inventing plausible
retrospective plans for work already shipped -- the sort of vacuous artifact the
rest of this harness exists to catch. New and edited plans fail closed; old ones
are left alone.
"""

from __future__ import annotations

import argparse
import logging
import sys
from collections.abc import Iterable, Sequence
from pathlib import Path

try:
    from harness.shared.plan_rules import Finding, check_plan
    from harness.shared.validate_invariants import git_modified_files
except ImportError:  # pragma: no cover - direct `python harness/shared/validate_plan.py`
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
    from harness.shared.plan_rules import Finding, check_plan
    from harness.shared.validate_invariants import git_modified_files

logger = logging.getLogger(__name__)

DEFAULT_SPEC_DIR = Path("docs") / "specs"
TEMPLATE_NAME = "SPEC_TEMPLATE.md"


def changed_plans(workspace: Path, spec_dir: Path) -> list[Path]:
    """Plans under ``spec_dir`` that git reports as modified, template excluded."""
    root = spec_dir if spec_dir.is_absolute() else workspace / spec_dir
    changed = []
    for rel in git_modified_files(workspace):
        candidate = (workspace / rel).resolve()
        if candidate.suffix != ".md" or candidate.name == TEMPLATE_NAME:
            continue
        try:
            candidate.relative_to(root.resolve())
        except ValueError:
            continue
        if candidate.is_file():
            changed.append(candidate)
    return sorted(set(changed))


def review(paths: Iterable[Path], workspace: Path) -> list[Finding]:
    """Run every rule over every plan. An unreadable plan is a finding, not a skip."""
    findings: list[Finding] = []
    for path in paths:
        try:
            text = path.read_text(encoding="utf-8")
        except OSError as exc:  # unreadable is a verdict, never a pass
            findings.append(
                Finding(
                    defect_class="UNPARSEABLE_PLAN",
                    spec=path.name,
                    ref=str(path),
                    detail=f"could not be read: {exc}",
                    remedy="fix the file's permissions or encoding",
                )
            )
            continue
        findings.extend(check_plan(text, path.relative_to(workspace).as_posix()))
    return findings


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--repo-root", type=Path, default=Path("."))
    parser.add_argument("--spec-dir", type=Path, default=DEFAULT_SPEC_DIR)
    parser.add_argument(
        "--all",
        action="store_true",
        help="review every plan in --spec-dir, not just modified ones (report-only sweeps)",
    )
    parser.add_argument("--log-level", default="INFO")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    logging.basicConfig(level=args.log_level.upper(), format="%(levelname)s: %(message)s")
    workspace = args.repo_root.resolve()
    spec_root = args.spec_dir if args.spec_dir.is_absolute() else workspace / args.spec_dir

    if args.all:
        plans = sorted(p for p in spec_root.glob("*.md") if p.name != TEMPLATE_NAME)
    else:
        plans = changed_plans(workspace, args.spec_dir)

    if not plans:
        # Said out loud on purpose: a gate that examined nothing has not passed,
        # and silence here is how a scoped gate goes quietly dead.
        print("plan: no changed plan documents to review (0 examined)")
        return 0

    findings = review(plans, workspace)
    for finding in findings:
        print(f"[FAIL] {finding.render()}", file=sys.stderr)

    if findings:
        classes = sorted({f.defect_class for f in findings})
        print(
            f"plan: FAILED — {len(findings)} finding(s) across {len(plans)} plan(s): "
            f"{', '.join(classes)}",
            file=sys.stderr,
        )
        return 1

    print(f"plan: passed ({len(plans)} plan(s) examined)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
