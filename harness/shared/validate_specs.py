"""Spec Traceability Validator.

Validates that all specifications in docs/specs/ conform to the traceability
contract (Requirements R-* and Citations C-*), preventing untested or ungrounded
features from entering the codebase.

The rules themselves live in ``harness.shared.plan_rules``. They used to be
written out here *and* again as a heredoc inside ``validate_specs.sh`` -- two
implementations of one contract, which had already drifted (the shell copy
discovered specs recursively and skipped no template; this one did neither). One
definition, two callers, per C-PLR-2 of ``docs/specs/plan-review-framework.md``.
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path

try:
    from harness.shared.plan_rules import REQ_PATTERN, structural_findings, structural_line
except ImportError:  # pragma: no cover - direct `python harness/shared/validate_specs.py`
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
    from harness.shared.plan_rules import REQ_PATTERN, structural_findings, structural_line

logger = logging.getLogger(__name__)

#: Re-exported: this module was the published home of the pattern before the rules
#: moved, and `check_traceability` documents it by this name.
__all__ = ["REQ_PATTERN", "validate_spec", "main"]


def validate_spec(content: str, name: str) -> bool:
    """Validate that a spec file conforms to the structural rules."""
    findings = structural_findings(content, name)
    for finding in findings:
        logger.error("[FAIL] %s", structural_line(finding))
    return not findings


def main(specs_dir: Path | None = None) -> int:
    """Validate all markdown specification documents in the specs directory."""
    if specs_dir is None:
        # Default to repo root docs/specs
        repo_root = Path(__file__).resolve().parent.parent.parent
        specs_dir = repo_root / "docs" / "specs"

    if not specs_dir.exists():
        logger.info("[PASS] No docs/specs directory found.")
        print("[PASS] No docs/specs directory found.")
        return 0

    failed = False
    checked_count = 0
    for spec in sorted(specs_dir.rglob("*.md")):
        if spec.name == "SPEC_TEMPLATE.md":
            continue

        checked_count += 1
        try:
            content = spec.read_text(encoding="utf-8")
        except Exception as e:  # noqa: BLE001 — fail-closed on unreadable spec
            logger.error("[FAIL] Could not read %s: %s", spec.name, e)
            print(f"[FAIL] Could not read {spec.name}: {e}", file=sys.stderr)
            failed = True
            continue

        if not validate_spec(content, spec.name):
            print(f"[FAIL] {spec.name} failed spec validation.", file=sys.stderr)
            failed = True

    if failed:
        logger.error("[FAIL] Spec validation failed.")
        print("[FAIL] Spec validation failed.", file=sys.stderr)
        return 1

    msg = f"[PASS] All {checked_count} spec(s) in {specs_dir} conform to the traceability template."
    logger.info(msg)
    print(msg)
    return 0


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    sys.exit(main())
