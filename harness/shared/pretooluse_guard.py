"""Backward-compatible shim for pretooluse_guard."""
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
