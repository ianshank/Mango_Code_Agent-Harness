"""Structured and gate logging helpers shared by every stack.

Two distinct sinks, deliberately:

* ``setup_json_logging`` emits JSON on **stdout** for callers that parse output
  (the API server, the Nemotron bridge, MCP consumers).
* ``configure_gate_logging`` emits plain diagnostics on **stderr** for governance
  gate scripts. Those scripts print their PASS/FAIL verdict to stdout, and both CI
  and the test suite assert on those exact strings, so diagnostics must never share
  that channel — raising verbosity has to stay incapable of changing a verdict.
"""

from __future__ import annotations

import json
import logging
import os
import sys
from datetime import datetime, timezone
from typing import Any

# Level is read from the environment so verbosity is operator-controlled rather
# than baked into each script. Only the fallback lives here.
LOG_LEVEL_ENV_VAR = "LOG_LEVEL"
DEFAULT_GATE_LOG_LEVEL = "INFO"
GATE_LOG_FORMAT = "%(levelname)s: %(message)s"


class JSONFormatter(logging.Formatter):
    """
    A custom JSON formatter for structured logging.
    Provides compatibility with MCP and Agent parsing constraints.
    """

    def format(self, record: logging.LogRecord) -> str:
        log_entry: dict[str, Any] = {
            "timestamp": datetime.fromtimestamp(record.created, tz=timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }

        if record.exc_info:
            log_entry["exception"] = self.formatException(record.exc_info)

        return json.dumps(log_entry)


def setup_json_logging(level: int = logging.INFO) -> None:
    """Configures the root logger to use JSONFormatter."""
    root_logger = logging.getLogger()
    # Remove existing handlers
    for handler in root_logger.handlers[:]:
        root_logger.removeHandler(handler)

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JSONFormatter())
    root_logger.addHandler(handler)
    root_logger.setLevel(level)


class _LazyStderrHandler(logging.StreamHandler):  # type: ignore[type-arg]
    """A stderr handler that resolves ``sys.stderr`` at emit time, not construction.

    ``logging.StreamHandler()`` captures the stream object when it is built. A gate
    that configures logging at import time would therefore keep writing to the
    interpreter's original stderr, invisible to pytest's capture and to any caller
    that redirects the stream. Resolving late keeps diagnostics observable.
    """

    @property
    def stream(self) -> Any:
        return sys.stderr

    @stream.setter
    def stream(self, value: Any) -> None:
        # StreamHandler.__init__ assigns the stream; the lazy property is the
        # authority, so the assignment is intentionally discarded.
        return


def resolve_log_level(raw: str | None = None, default: str = DEFAULT_GATE_LOG_LEVEL) -> int:
    """Resolve a logging level from a name, falling back rather than raising.

    Misconfigured verbosity must never fail a governance gate: an unusable
    ``LOG_LEVEL`` degrades to the default instead of turning a passing gate red.
    Accepts level names case-insensitively and numeric strings.
    """
    candidate = (raw if raw is not None else os.environ.get(LOG_LEVEL_ENV_VAR, "")).strip()
    if not candidate:
        candidate = default
    if candidate.isdigit():
        return int(candidate)
    resolved = logging.getLevelName(candidate.upper())
    # getLevelName returns the "Level %s" string for names it does not know.
    if isinstance(resolved, int):
        return resolved
    return logging.getLevelName(default.upper())  # type: ignore[no-any-return]


def configure_gate_logging(name: str | None = None) -> logging.Logger:
    """Return a stderr logger for a governance gate script, level from the env.

    Diagnostics are additive: a gate's stdout (its ``<gate>: passed`` verdict, which
    tests assert on) is untouched at any verbosity. Run a gate with
    ``LOG_LEVEL=DEBUG`` to see what it actually inspected.

    Idempotent: repeated calls do not stack handlers, so importing a gate module
    more than once in a test session cannot duplicate every line.
    """
    level = resolve_log_level()
    logger = logging.getLogger(name if name else __name__)
    logger.setLevel(level)
    # Gates run as standalone scripts; routing to the root logger would let an
    # unrelated basicConfig() redirect diagnostics onto stdout.
    logger.propagate = False
    if not any(getattr(h, "_mango_gate_handler", False) for h in logger.handlers):
        handler: logging.Handler = _LazyStderrHandler()
        handler.setFormatter(logging.Formatter(GATE_LOG_FORMAT))
        handler._mango_gate_handler = True  # type: ignore[attr-defined]
        logger.addHandler(handler)
    for handler in logger.handlers:
        handler.setLevel(level)
    return logger
