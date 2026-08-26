#!/usr/bin/env python3
"""Stack-local entry point; delegates to the shared governance kernel.

This file is a thin shim: the governance LOGIC lives only in
harness/shared/<name>.py (single source of truth). It resolves that shared
module relative to its own location and runs it as ``__main__`` so that
``python harness/<stack>/scripts/remotes.py`` is behaviorally identical to
``python harness/shared/remotes.py`` (same CLI, same CWD-relative path
resolution, same exit codes, same stdout/stderr).
"""
import runpy
import sys
from pathlib import Path

# harness/<stack>/scripts/<name>.py  ->  harness/shared
_SHARED = Path(__file__).resolve().parents[2] / "shared"
if str(_SHARED) not in sys.path:
    sys.path.insert(0, str(_SHARED))
runpy.run_path(str(_SHARED / "remotes.py"), run_name="__main__")
