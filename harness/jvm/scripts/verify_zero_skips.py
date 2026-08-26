"""Backward-compatible shim for verify_zero_skips."""
import sys
from pathlib import Path

_repo_root = Path(__file__).resolve().parent.parent.parent
if str(_repo_root) not in sys.path:
    sys.path.insert(0, str(_repo_root))

from harness.shared.governance.verify_zero_skips import main as verify_zero_skips_main

if __name__ == "__main__":
    verify_zero_skips_main()
