"""Backward-compatible shim for check_traceability."""
import sys
from pathlib import Path

try:
    from harness.shared.governance.check_traceability import check_traceability as check_traceability
except ImportError:
    # Bare `python harness/shared/check_traceability.py` from an arbitrary CWD: the
    # repo root is not importable yet, so resolve it, insert, and retry. Every
    # sibling shim carries this bootstrap; this one was the only shim without it.
    _repo_root = Path(__file__).resolve().parents[2]
    if str(_repo_root) not in sys.path:
        sys.path.insert(0, str(_repo_root))
    from harness.shared.governance.check_traceability import check_traceability as check_traceability

if __name__ == "__main__":
    # Called, not `sys.exit(...)`-wrapped: the gate returns None on success (exit 0)
    # and raises SystemExit with a message on failure, which propagates on its own.
    check_traceability()
