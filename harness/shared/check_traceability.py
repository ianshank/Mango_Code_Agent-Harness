"""Backward-compatible shim for check_traceability."""
from harness.shared.governance.check_traceability import check_traceability as check_traceability

if __name__ == "__main__":
    # Called, not `sys.exit(...)`-wrapped: the gate returns None on success (exit 0)
    # and raises SystemExit with a message on failure, which propagates on its own.
    check_traceability()
