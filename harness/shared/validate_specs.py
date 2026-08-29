"""Spec Traceability Validator.

Validates that all specifications in docs/specs/ conform to the traceability
contract (Requirements R-* and Citations C-*), preventing untested or ungrounded
features from entering the codebase.
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path

logger = logging.getLogger(__name__)


def validate_spec(content: str, name: str) -> bool:
    """Validate that a spec file contains mandatory requirements and citations sections."""
    failed = False
    if "## Requirements (R-*)" not in content:
        logger.error("[FAIL] %s is missing '## Requirements (R-*)' header.", name)
        failed = True
    if "## Citations (C-*)" not in content:
        logger.error("[FAIL] %s is missing '## Citations (C-*)' header.", name)
        failed = True
    return not failed


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
    for spec in sorted(specs_dir.glob("*.md")):
        if spec.name == "SPEC_TEMPLATE.md":
            continue

        checked_count += 1
        try:
            content = spec.read_text(encoding="utf-8")
        except Exception as e:
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
