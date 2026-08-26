"""Re-export shim: structured JSON logging lives only in harness/shared/json_logging.py.

Per-stack copies are forbidden by the `check-dedup` drift gate (INV single-source-of-truth);
this module exists so `harness/<stack>/scripts/` callers keep working without duplicating logic.
"""

import sys
from pathlib import Path

_repo_root = Path(__file__).resolve().parent.parent.parent.parent
if str(_repo_root) not in sys.path:
    sys.path.insert(0, str(_repo_root))

from harness.shared.json_logging import JSONFormatter, setup_json_logging

__all__ = ["JSONFormatter", "setup_json_logging"]
