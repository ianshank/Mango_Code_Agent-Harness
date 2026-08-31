"""Tests for json_logging: JSON formatter, setup, gate logging, log level resolution."""
from __future__ import annotations

import json
import logging
import os
import sys
from io import StringIO
from unittest.mock import patch

from harness.shared.json_logging import (
    LOG_LEVEL_ENV_VAR,
    JSONFormatter,
    _LazyStderrHandler,
    configure_gate_logging,
    resolve_log_level,
    setup_json_logging,
)

# -- JSONFormatter -----------------------------------------------------------

class TestJSONFormatter:
    """JSONFormatter must produce parseable single-line JSON."""

    def _make_record(self, msg: str = "hello", level: int = logging.INFO) -> logging.LogRecord:
        return logging.LogRecord(
            name="test", level=level, pathname="test.py", lineno=1,
            msg=msg, args=(), exc_info=None,
        )

    def test_output_is_valid_json(self) -> None:
        formatter = JSONFormatter()
        record = self._make_record()
        raw = formatter.format(record)
        parsed = json.loads(raw)
        assert parsed["message"] == "hello"
        assert parsed["level"] == "INFO"
        assert "timestamp" in parsed
        assert "logger" in parsed

    def test_exception_included(self) -> None:
        formatter = JSONFormatter()
        try:
            raise ValueError("boom")
        except ValueError:
            record = self._make_record()
            record.exc_info = sys.exc_info()

        raw = formatter.format(record)
        parsed = json.loads(raw)
        assert "exception" in parsed
        assert "boom" in parsed["exception"]

    def test_no_exception_key_when_none(self) -> None:
        formatter = JSONFormatter()
        record = self._make_record()
        raw = formatter.format(record)
        parsed = json.loads(raw)
        assert "exception" not in parsed


# -- resolve_log_level -------------------------------------------------------

class TestResolveLogLevel:
    """Level resolution must never raise, even with garbage input."""

    def test_default_when_empty(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            level = resolve_log_level(None)
            assert level == logging.INFO

    def test_explicit_debug(self) -> None:
        assert resolve_log_level("DEBUG") == logging.DEBUG

    def test_case_insensitive(self) -> None:
        assert resolve_log_level("warning") == logging.WARNING

    def test_numeric_string(self) -> None:
        assert resolve_log_level("10") == 10

    def test_unknown_name_falls_back(self) -> None:
        level = resolve_log_level("NONEXISTENT")
        assert isinstance(level, int)

    def test_env_var_respected(self) -> None:
        with patch.dict(os.environ, {LOG_LEVEL_ENV_VAR: "ERROR"}):
            level = resolve_log_level(None)
            assert level == logging.ERROR

    def test_raw_overrides_env(self) -> None:
        with patch.dict(os.environ, {LOG_LEVEL_ENV_VAR: "ERROR"}):
            level = resolve_log_level("DEBUG")
            assert level == logging.DEBUG

    def test_whitespace_stripped(self) -> None:
        assert resolve_log_level("  WARNING  ") == logging.WARNING


# -- setup_json_logging ------------------------------------------------------

class TestSetupJsonLogging:
    """setup_json_logging must configure the root logger."""

    def test_replaces_existing_handlers(self) -> None:
        root = logging.getLogger()
        original_handlers = root.handlers[:]
        try:
            setup_json_logging(logging.DEBUG)
            assert len(root.handlers) == 1
            assert isinstance(root.handlers[0].formatter, JSONFormatter)
        finally:
            root.handlers = original_handlers


# -- _LazyStderrHandler ------------------------------------------------------

class TestLazyStderrHandler:
    """Handler must resolve sys.stderr at emit time, not construction."""

    def test_stream_is_stderr(self) -> None:
        handler = _LazyStderrHandler()
        assert handler.stream is sys.stderr

    def test_stream_setter_is_noop(self) -> None:
        handler = _LazyStderrHandler()
        handler.stream = StringIO()
        assert handler.stream is sys.stderr


# -- configure_gate_logging --------------------------------------------------

class TestConfigureGateLogging:
    """Gate logging must be idempotent and use stderr."""

    def test_returns_logger(self) -> None:
        logger = configure_gate_logging("test_gate")
        assert isinstance(logger, logging.Logger)

    def test_idempotent(self) -> None:
        logger1 = configure_gate_logging("test_idempotent")
        n = len(logger1.handlers)
        logger2 = configure_gate_logging("test_idempotent")
        assert logger2 is logger1
        assert len(logger2.handlers) == n

    def test_no_propagation(self) -> None:
        logger = configure_gate_logging("test_no_propagate")
        assert logger.propagate is False
