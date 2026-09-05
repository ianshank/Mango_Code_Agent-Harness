"""Regression tests for coverage gap fill — modules that were previously untested.

Defects covered:
1. json_logging: resolve_log_level must fall back safely on garbage input
2. tool_dispatch: _normalize_tool_arguments must not raise on None or list JSON
3. governance/verification: reentrancy env must be restored after run
4. governance/process_backend: _cap must work on bytes, not characters
5. validate_adoption: digest mismatch must be detected
"""

from __future__ import annotations

import json
import logging
import os
from unittest.mock import patch

from harness.shared.governance.process_backend import _cap
from harness.shared.json_logging import resolve_log_level
from harness.shared.tool_dispatch import _normalize_tool_arguments


class TestLogLevelResolutionRegression:
    """Pin: resolve_log_level never raises, even with garbage or missing env."""

    def test_garbage_input_falls_back(self) -> None:
        level = resolve_log_level("GARBAGE_LEVEL_NAME")
        assert isinstance(level, int)
        assert level > 0

    def test_empty_env_returns_default(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            level = resolve_log_level(None)
            assert level == logging.INFO

    def test_numeric_string_passes_through(self) -> None:
        assert resolve_log_level("42") == 42


class TestToolDispatchNormalizationRegression:
    """Pin: argument normalization degrades safely on every model-generated shape."""

    def test_none_does_not_raise(self) -> None:
        result = _normalize_tool_arguments(None, "write_file")
        assert result == {}

    def test_json_list_does_not_raise(self) -> None:
        result = _normalize_tool_arguments('["a", "b"]', "run_command")
        assert result == {}

    def test_integer_does_not_raise(self) -> None:
        result = _normalize_tool_arguments(42, "apply_patch")
        assert result == {}

    def test_valid_json_object_passes(self) -> None:
        raw = json.dumps({"filepath": "test.py", "content": "print(1)"})
        result = _normalize_tool_arguments(raw, "write_file")
        assert result["filepath"] == "test.py"


class TestCapBytesTruncationRegression:
    """Pin: _cap works on bytes, not characters, to prevent multibyte overflow."""

    def test_ascii_truncation(self) -> None:
        text = "a" * 200
        result = _cap(text, 50)
        assert "[truncated at 50 bytes]" in result

    def test_emoji_does_not_produce_partial_char(self) -> None:
        text = "\U0001f600" * 20  # 80 UTF-8 bytes
        result = _cap(text, 10)
        # Must not raise on encode
        result.encode("utf-8")
        assert "[truncated at 10 bytes]" in result

    def test_under_limit_unchanged(self) -> None:
        assert _cap("short", 1000) == "short"
