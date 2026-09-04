"""Tests for json_logging: JSON formatter, setup, gate logging, log level resolution."""
from __future__ import annotations

import json
import logging
import os
import sys
from collections.abc import Iterator
from contextlib import contextmanager
from io import StringIO
from unittest.mock import patch

import pytest

from harness.shared.json_logging import (
    GATE_LOG_FORMAT,
    LOG_LEVEL_ENV_VAR,
    JSONFormatter,
    _LazyStderrHandler,
    configure_gate_logging,
    configure_gate_process_logging,
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

    def _record_with_extra(self, **extra: object) -> logging.LogRecord:
        """Build the record the way `logger.log(..., extra=...)` does, so the
        standard attributes are exactly the ones a real record carries."""
        return logging.makeLogRecord({"name": "test", "levelno": logging.INFO, "levelname": "INFO",
                                      "msg": "hello", "args": (), **extra})

    def test_extra_fields_become_top_level_keys(self) -> None:
        """`extra=` was dropped on the floor (2026 standards audit H6)."""
        record = self._record_with_extra(run_id="abc123", latency_ms=42, permitted=True, tokens=None)
        parsed = json.loads(JSONFormatter().format(record))
        assert (parsed["run_id"], parsed["latency_ms"], parsed["permitted"], parsed["tokens"]) == (
            "abc123", 42, True, None
        )

    def test_standard_record_attributes_are_not_echoed(self) -> None:
        parsed = json.loads(JSONFormatter().format(self._record_with_extra(run_id="x")))
        assert set(parsed) == {"timestamp", "level", "logger", "message", "run_id"}

    @pytest.mark.parametrize(
        "key", ["api_key", "API_KEY", "token", "auth_token", "secret", "client_secret", "password", "credentials"]
    )
    def test_a_credential_named_extra_is_never_emitted(self, key: str) -> None:
        record = self._record_with_extra(run_id="x", **{key: "nvapi-should-not-appear-0123456789"})
        raw = JSONFormatter().format(record)
        assert key not in json.loads(raw)
        assert "should-not-appear" not in raw

    def test_a_key_that_merely_contains_a_credential_word_is_kept(self) -> None:
        """`prompt_tokens` ends in TOKENS, not TOKEN; `keyspace` starts with key.
        The pattern is `debug_dump`'s, and its boundary rules are its own."""
        record = self._record_with_extra(prompt_tokens=12, keyspace="k")
        parsed = json.loads(JSONFormatter().format(record))
        assert (parsed["prompt_tokens"], parsed["keyspace"]) == (12, "k")

    def test_an_extra_cannot_override_a_base_field(self) -> None:
        record = self._record_with_extra(level="FORGED", logger="forged", timestamp="never")
        parsed = json.loads(JSONFormatter().format(record))
        assert (parsed["level"], parsed["logger"]) == ("INFO", "test")
        assert parsed["timestamp"] != "never"

    def test_a_non_json_value_is_stringified_not_fatal(self) -> None:
        from pathlib import Path

        record = self._record_with_extra(path=Path("/tmp/x"))
        assert json.loads(JSONFormatter().format(record))["path"] == "/tmp/x"


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

    def test_an_explicit_level_wins_over_the_environment(self) -> None:
        with patch.dict(os.environ, {LOG_LEVEL_ENV_VAR: "ERROR"}):
            logger = configure_gate_logging("test_explicit_level", level="DEBUG")
        assert logger.level == logging.DEBUG
        assert all(h.level == logging.DEBUG for h in logger.handlers)

    def test_a_bogus_explicit_level_degrades_rather_than_raises(self) -> None:
        logger = configure_gate_logging("test_bogus_level", level="BOGUS")
        assert logger.level == logging.INFO


# -- configure_gate_process_logging -------------------------------------------

@contextmanager
def _bare_root() -> Iterator[logging.Logger]:
    """The root logger with no handlers and the default level, restored afterwards.

    A context manager entered inside the test body, not a fixture: pytest's
    logging plugin adds a fresh capture handler to the root at the start of
    each *phase*, so a fixture that stripped the root during setup would find
    it populated again by the time the test runs. "Someone configured logging
    before the gate" is exactly the second shape the helper must handle, and
    both are exercised below.
    """
    root = logging.getLogger()
    saved_handlers, saved_level = root.handlers[:], root.level
    root.handlers = []
    root.setLevel(logging.WARNING)
    try:
        yield root
    finally:
        root.handlers = saved_handlers
        root.setLevel(saved_level)


class TestConfigureGateProcessLogging:
    """The `__main__`-block form that replaced `logging.basicConfig` in eight
    gate scripts (2026 standards audit M25)."""

    def test_a_bare_root_gets_the_gate_handler_at_the_env_level(self) -> None:
        with _bare_root() as bare, patch.dict(os.environ, {LOG_LEVEL_ENV_VAR: "DEBUG"}):
            root = configure_gate_process_logging()
            assert root is bare
            assert [type(h) for h in root.handlers] == [_LazyStderrHandler]
            assert root.level == logging.DEBUG and root.handlers[0].level == logging.DEBUG
            formatter = root.handlers[0].formatter
            assert formatter is not None and formatter._fmt == GATE_LOG_FORMAT

    def test_diagnostics_reach_stderr_in_the_gate_format(self, capsys) -> None:
        with _bare_root(), patch.dict(os.environ, {LOG_LEVEL_ENV_VAR: "INFO"}):
            configure_gate_process_logging()
            logging.getLogger("some.imported.module").info("inspected %d files", 3)
        captured = capsys.readouterr()
        assert captured.out == ""
        assert captured.err == "INFO: inspected 3 files\n"

    def test_a_root_someone_else_configured_is_left_alone(self) -> None:
        """The basicConfig contract: an importing process owns its logging."""
        with _bare_root() as bare, patch.dict(os.environ, {LOG_LEVEL_ENV_VAR: "DEBUG"}):
            foreign = logging.NullHandler()
            bare.addHandler(foreign)
            bare.setLevel(logging.ERROR)
            configure_gate_process_logging()
            assert bare.handlers == [foreign]
            assert bare.level == logging.ERROR

    def test_calling_twice_relevels_rather_than_stacking(self) -> None:
        with _bare_root() as bare:
            configure_gate_process_logging("INFO")
            configure_gate_process_logging("WARNING")
            assert len(bare.handlers) == 1
            assert bare.level == logging.WARNING and bare.handlers[0].level == logging.WARNING

    def test_an_explicit_level_wins_and_a_bogus_one_degrades(self) -> None:
        with _bare_root() as bare, patch.dict(os.environ, {LOG_LEVEL_ENV_VAR: "ERROR"}):
            configure_gate_process_logging("debug")
            assert bare.level == logging.DEBUG
            configure_gate_process_logging("BOGUS")
            assert bare.level == logging.INFO

    def test_under_pytest_it_is_a_no_op(self) -> None:
        """The in-process `main()` calls the suite makes must not leave a
        stderr handler on the root for every later test."""
        root = logging.getLogger()
        before = root.handlers[:]
        configure_gate_process_logging("DEBUG")
        assert root.handlers == before


class TestNoGateCallsBasicConfig:
    """The eight call sites M25 counted, pinned so the duplication cannot return."""

    GATES = [
        "harness/shared/check_dedup.py",
        "harness/shared/check_py_compat.py",
        "harness/shared/coverage_gate.py",
        "harness/shared/validate_invariants.py",
        "harness/shared/validate_plan.py",
        "harness/shared/validate_specs.py",
        "harness/shared/governance/attestation.py",
        "harness/shared/governance/check_secret_allowlist.py",
    ]

    @pytest.mark.parametrize("relpath", GATES)
    def test_the_gate_routes_through_the_shared_sink(self, relpath: str) -> None:
        from harness.shared.tests._helpers import REPO

        source = (REPO / relpath).read_text(encoding="utf-8")
        assert "logging.basicConfig(" not in source, f"{relpath} configures logging on its own"
        assert "configure_gate_process_logging(" in source, f"{relpath} does not use the shared sink"
        assert '"%(levelname)s: %(message)s"' not in source, f"{relpath} restates GATE_LOG_FORMAT"
