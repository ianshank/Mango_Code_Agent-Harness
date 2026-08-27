import sys
from pathlib import Path

_repo_root = Path(__file__).resolve().parent.parent.parent.parent
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
    import sys
    sys.exit(main())
