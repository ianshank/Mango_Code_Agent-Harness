"""Backward-compatible shim for check_traceability."""

from harness.shared.governance.check_traceability import check_traceability as check_traceability

if __name__ == "__main__":
    check_traceability()
