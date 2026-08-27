"""Backward-compatible shim for pretooluse_guard."""
import sys
from pathlib import Path

_repo_root = Path(__file__).resolve().parent.parent.parent.parent
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
    import sys
    sys.exit(main())
