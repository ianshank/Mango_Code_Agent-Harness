"""Backward-compatible shim for pretooluse_guard."""
import sys
from pathlib import Path

try:
    from harness.shared.governance.pretooluse_guard import (
        DANGER,
        UNMODELED,
        destinations,
        main,
        segments,
    )
except ImportError:
    # Bare `python harness/shared/pretooluse_guard.py` from an arbitrary CWD:
    # the repo root is not importable yet, so resolve it, insert, and retry.
    # All shared shims carry this same import-first bootstrap (see
    # check_traceability.py).
    _repo_root = Path(__file__).resolve().parents[2]
    if str(_repo_root) not in sys.path:
        sys.path.insert(0, str(_repo_root))
    from harness.shared.governance.pretooluse_guard import (
        DANGER,
        UNMODELED,
        destinations,
        main,
        segments,
    )

__all__ = [
    "DANGER",
    "UNMODELED",
    "destinations",
    "main",
    "segments",
]

if __name__ == "__main__":
    sys.exit(main())
