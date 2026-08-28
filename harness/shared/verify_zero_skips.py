"""Backward-compatible shim for verify_zero_skips."""
import sys
from pathlib import Path

try:
    from harness.shared.governance.verify_zero_skips import main as verify_zero_skips_main
except ImportError:
    # Bare `python harness/shared/verify_zero_skips.py` from an arbitrary CWD:
    # the repo root is not importable yet, so resolve it, insert, and retry.
    # All shared shims carry this same import-first bootstrap (see
    # check_traceability.py).
    _repo_root = Path(__file__).resolve().parents[2]
    if str(_repo_root) not in sys.path:
        sys.path.insert(0, str(_repo_root))
    from harness.shared.governance.verify_zero_skips import main as verify_zero_skips_main

__all__ = ["verify_zero_skips_main"]

if __name__ == "__main__":
    verify_zero_skips_main()
