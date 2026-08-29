"""Spec Traceability Validator.

Validates that all specifications in docs/specs/ conform to the traceability
contract (Requirements R-* and Citations C-*), preventing untested or ungrounded
features from entering the codebase.
"""

from __future__ import annotations

import logging
import re
import sys
from pathlib import Path

logger = logging.getLogger(__name__)

REQ_PATTERN = re.compile(r"\b([CR]-[A-Za-z0-9_-]+)\b")
UNFALSIFIABLE_TERMS = ("works correctly", "as expected", "appropriately")


def validate_spec(content: str, name: str) -> bool:
    """Validate that a spec file conforms to the structural rules."""
    failed = False
    for section in ("## Requirements", "## Acceptance criteria"):
        if section not in content:
            logger.error("[FAIL] %s is missing '%s' header.", name, section)
            failed = True

    for ln in content.splitlines():
        if ln.lstrip().startswith(("- ", "* ")) and "MUST" in ln and not REQ_PATTERN.search(ln):
            logger.error("[FAIL] %s: normative MUST has no requirement ID: %s", name, ln[:80])
            failed = True

    lower_content = content.lower()
    for term in UNFALSIFIABLE_TERMS:
        if term in lower_content:
            logger.error("[FAIL] %s: unfalsifiable acceptance language '%s'", name, term)
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
