"""Structured and gate logging helpers shared by every stack.

Two distinct sinks, deliberately:

* ``setup_json_logging`` emits JSON on **stdout** for callers that parse output
  (the API server, the Nemotron bridge, MCP consumers).
* ``configure_gate_logging`` emits plain diagnostics on **stderr** for governance
  gate scripts. Those scripts print their PASS/FAIL verdict to stdout, and both CI
  and the test suite assert on those exact strings, so diagnostics must never share
  that channel — raising verbosity has to stay incapable of changing a verdict.
  ``configure_gate_process_logging`` is the same sink for a gate's ``__main__``
  block, where the whole process is the gate and every module it imports should
  report through the one handler.
"""

from __future__ import annotations

import json
import logging
import os
import sys
from datetime import datetime, timezone
from typing import Any

try:
    from harness.shared.debug_dump import CREDENTIAL_NAME_PATTERN
except ImportError:  # pragma: no cover - sibling import for `python harness/shared/<gate>.py`
    from debug_dump import CREDENTIAL_NAME_PATTERN  # type: ignore[no-redef]

# Level is read from the environment so verbosity is operator-controlled rather
# than baked into each script. Only the fallback lives here.
LOG_LEVEL_ENV_VAR = "LOG_LEVEL"
DEFAULT_GATE_LOG_LEVEL = "INFO"
GATE_LOG_FORMAT = "%(levelname)s: %(message)s"

#: Every attribute a bare ``LogRecord`` carries, plus the two ``Formatter`` adds.
#: Whatever else is on a record arrived through ``extra=`` and is the caller's
#: structured payload -- the fields ``JSONFormatter`` used to drop on the floor
#: (2026 standards audit H6). Computed from a real record rather than listed, so
#: an attribute a future Python adds (``taskName`` in 3.12) is excluded too.
_STANDARD_RECORD_ATTRIBUTES = frozenset(
    vars(logging.LogRecord("", logging.NOTSET, "", 0, "", (), None))
) | {"message", "asctime"}


def _is_credential_key(key: str) -> bool:
    """Whether an ``extra`` key names a credential by the shape of its name.

    The same pattern ``debug_dump`` uses to strip credential-bearing variables
    from a spawned environment, applied to the upper-cased key: a caller that
    logs ``api_key=...`` has made the same mistake as one that exports it, and
    the formatter is the last place it can be caught.
    """
    return CREDENTIAL_NAME_PATTERN.search(key.upper()) is not None


class JSONFormatter(logging.Formatter):
    """
    A custom JSON formatter for structured logging.
    Provides compatibility with MCP and Agent parsing constraints.

    Fields passed through ``extra=`` become top-level keys. A key that names a
    credential (``api_key``, ``token``, ``secret``, ...) is never emitted, and a
    key that collides with one of the four base fields does not override it.
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

        for key, value in vars(record).items():
            if key in _STANDARD_RECORD_ATTRIBUTES or key.startswith("_") or _is_credential_key(key):
                continue
            log_entry.setdefault(key, value)

        return json.dumps(log_entry, default=str)


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


def _gate_handler(level: int) -> logging.Handler:
    """The one stderr handler every gate shares: lazy stream, ``GATE_LOG_FORMAT``."""
    handler: logging.Handler = _LazyStderrHandler()
    handler.setFormatter(logging.Formatter(GATE_LOG_FORMAT))
    handler.setLevel(level)
    handler._mango_gate_handler = True  # type: ignore[attr-defined]
    return handler


def _is_gate_handler(handler: logging.Handler) -> bool:
    return bool(getattr(handler, "_mango_gate_handler", False))


def configure_gate_logging(name: str | None = None, *, level: str | int | None = None) -> logging.Logger:
    """Return a stderr logger for a governance gate script, level from the env.

    Diagnostics are additive: a gate's stdout (its ``<gate>: passed`` verdict, which
    tests assert on) is untouched at any verbosity. Run a gate with
    ``LOG_LEVEL=DEBUG`` to see what it actually inspected. ``level`` -- a
    ``--log-level`` flag, typically -- takes precedence over the environment and
    goes through ``resolve_log_level``, so a bad value degrades rather than raises.

    Idempotent: repeated calls do not stack handlers, so importing a gate module
    more than once in a test session cannot duplicate every line.
    """
    resolved = resolve_log_level(None if level is None else str(level))
    logger = logging.getLogger(name if name else __name__)
    logger.setLevel(resolved)
    # Gates run as standalone scripts; routing to the root logger would let an
    # unrelated basicConfig() redirect diagnostics onto stdout.
    logger.propagate = False
    if not any(_is_gate_handler(h) for h in logger.handlers):
        logger.addHandler(_gate_handler(resolved))
    for handler in logger.handlers:
        handler.setLevel(resolved)
    return logger


def configure_gate_process_logging(level: str | int | None = None) -> logging.Logger:
    """Configure the root logger for a gate running as the process entry point.

    This is what every gate's ``__main__`` block did with ``logging.basicConfig``
    -- eight of them, each restating ``GATE_LOG_FORMAT`` and one hard-coding
    ``INFO`` (2026 standards audit M25) -- expressed once: the shared stderr
    handler on the root logger, so diagnostics from every module the gate
    imports arrive in the one format, at the level ``LOG_LEVEL`` (or ``level``)
    resolves to.

    Like ``basicConfig``, it defers to a root logger that already has handlers.
    A process that configured logging before importing a gate -- pytest, an
    adopter's own harness -- owns that configuration; only a handler this
    function installed earlier is re-levelled, which keeps the call idempotent.
    """
    resolved = resolve_log_level(None if level is None else str(level))
    root = logging.getLogger()
    ours = [handler for handler in root.handlers if _is_gate_handler(handler)]
    if not root.handlers:
        root.addHandler(_gate_handler(resolved))
        root.setLevel(resolved)
    elif ours:
        for handler in ours:
            handler.setLevel(resolved)
        root.setLevel(resolved)
    return root
