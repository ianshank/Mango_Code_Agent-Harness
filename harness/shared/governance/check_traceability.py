#!/usr/bin/env python3
"""Bidirectional requirement traceability gate.

Every requirement ID declared in the spec globs must be cited by both an
implementation file and a test file. Failures name each ID *and which side* it is
missing from, because "missing implementation and/or test citation" alone does not
tell an operator which half to fix.

Run with ``LOG_LEVEL=DEBUG`` to see which globs matched which files. That is the
fastest way to diagnose the common failure where a glob is scoped to one stack and
silently checks nothing outside it.
"""

from __future__ import annotations

import glob
import json
import logging
import re
import sys
from pathlib import Path

REQ = re.compile(r"\b([CR]-[A-Za-z0-9_-]+)\b")

TRACEABILITY_CONFIG = Path(".governance/traceability.json")


def _gate_logger() -> logging.Logger:
    """Return the shared gate logger, degrading to a bare one if unimportable.

    These scripts run as ``python ../shared/governance/check_traceability.py`` from
    a stack directory, where the repo root is not on ``sys.path``. Diagnostics are
    never allowed to fail the gate, so an import problem degrades to a no-op logger
    rather than raising.
    """
    try:
        root = Path(__file__).resolve().parents[3]
        if str(root) not in sys.path:
            sys.path.insert(0, str(root))
        from harness.shared.json_logging import configure_gate_logging

        return configure_gate_logging(__name__)
    except Exception:  # noqa: BLE001 - logging setup must never break a gate
        return _fallback_logger()


def _fallback_logger() -> logging.Logger:
    """A stderr logger that does not propagate, for when the shared helper is absent.

    Propagating would hand diagnostics to the root logger, and `setup_json_logging`
    in this same package attaches a root handler on **stdout** — so the fallback
    could put diagnostics into the verdict channel the separation exists to protect.
    """
    logger = logging.getLogger(__name__)
    logger.propagate = False
    if not logger.handlers:
        logger.addHandler(logging.StreamHandler(sys.stderr))
    return logger


logger = _gate_logger()


def check_traceability() -> None:
    cfg = json.loads(TRACEABILITY_CONFIG.read_text())

    def files(patterns: list[str], label: str) -> list[Path]:
        out: list[Path] = []
        for p in patterns:
            matched = [Path(x) for x in glob.glob(p, recursive=True) if Path(x).is_file()]
            logger.debug("%s glob %r matched %d file(s)", label, p, len(matched))
            out += matched
        logger.debug("%s: %d file(s) total: %s", label, len(out), [str(p) for p in out])
        return out

    specs = files(cfg["spec_globs"], "spec_globs")
    impl = files(cfg["implementation_globs"], "implementation_globs")
    tests = files(cfg["test_globs"], "test_globs")
    if not specs:
        raise SystemExit("traceability: no spec files matched")
    ids: set[str] = set()
    for p in specs:
        ids.update(REQ.findall(p.read_text(errors="replace")))
    if not ids:
        raise SystemExit("traceability: specs contain no requirement IDs")
    logger.debug("discovered %d requirement ID(s): %s", len(ids), sorted(ids))
    impl_text = "\n".join(p.read_text(errors="replace") for p in impl)
    test_text = "\n".join(p.read_text(errors="replace") for p in tests)

    # Track each side separately: an ID cited in code but not in a test is a very
    # different fix from one cited nowhere, and the combined message hid that.
    gaps: dict[str, list[str]] = {}
    for req in sorted(ids):
        absent_from = []
        if req not in impl_text:
            absent_from.append("implementation")
        if req not in test_text:
            absent_from.append("tests")
        if absent_from:
            gaps[req] = absent_from
    if gaps:
        # Leading sentence is unchanged: CI logs and the test suite match on it.
        detail = "".join(f"\n  {req}: absent from {' and '.join(sides)}" for req, sides in gaps.items())
        raise SystemExit(
            "traceability: requirement IDs missing implementation and/or test citation: " + ", ".join(gaps) + detail
        )
    print(f"traceability: passed ({len(ids)} requirements)")


if __name__ == "__main__":
    check_traceability()
