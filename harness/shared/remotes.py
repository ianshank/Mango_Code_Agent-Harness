"""Backward-compatible shim for remotes."""

import sys
from pathlib import Path

try:
    from harness.shared.governance.remotes import (
        NormalizedRemote,
        RemoteParseError,
        check_url,
        current_push_urls,
        load_allowlist,
        main,
        normalize_remote_url,
        parse_allowlist,
    )
except ImportError:
    # Bare `python harness/shared/remotes.py` from an arbitrary CWD: the repo
    # root is not importable yet, so resolve it, insert, and retry. All shared
    # shims carry this same import-first bootstrap (see check_traceability.py).
    _repo_root = Path(__file__).resolve().parents[2]
    if str(_repo_root) not in sys.path:
        sys.path.insert(0, str(_repo_root))
    from harness.shared.governance.remotes import (
        NormalizedRemote,
        RemoteParseError,
        check_url,
        current_push_urls,
        load_allowlist,
        main,
        normalize_remote_url,
        parse_allowlist,
    )

__all__ = [
    "NormalizedRemote",
    "check_url",
    "current_push_urls",
    "RemoteParseError",
    "load_allowlist",
    "main",
    "normalize_remote_url",
    "parse_allowlist",
]

if __name__ == "__main__":
    sys.exit(main())
