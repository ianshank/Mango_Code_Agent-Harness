"""Tests for tool_dispatch: argument normalisation and constants."""

from __future__ import annotations

import json

import pytest

from harness.shared.tool_dispatch import (
    DEFAULT_HYPOTHESIS_CONFIDENCE,
    _normalize_tool_arguments,
)

# -- DEFAULT_HYPOTHESIS_CONFIDENCE -------------------------------------------


class TestDefaultHypothesisConfidence:
    """Constant must be a valid probability in [0, 1]."""

    def test_value_is_float(self) -> None:
        assert isinstance(DEFAULT_HYPOTHESIS_CONFIDENCE, (int, float))

    def test_value_in_unit_interval(self) -> None:
        assert 0.0 <= DEFAULT_HYPOTHESIS_CONFIDENCE <= 1.0


# -- _normalize_tool_arguments -----------------------------------------------


class TestNormalizeToolArguments:
    """Every shape a model can send must degrade to a dict, never raise."""

    def test_dict_passthrough(self) -> None:
        d = {"filepath": "a.py", "content": "x"}
        assert _normalize_tool_arguments(d, "write_file") is d

    def test_valid_json_string(self) -> None:
        raw = json.dumps({"filepath": "a.py"})
        result = _normalize_tool_arguments(raw, "write_file")
        assert result == {"filepath": "a.py"}

    def test_none_returns_empty(self) -> None:
        assert _normalize_tool_arguments(None, "write_file") == {}

    def test_empty_string_returns_empty(self) -> None:
        assert _normalize_tool_arguments("", "write_file") == {}

    def test_whitespace_string_returns_empty(self) -> None:
        assert _normalize_tool_arguments("   ", "write_file") == {}

    def test_json_list_returns_empty(self) -> None:
        """JSON array is not a valid arguments object."""
        assert _normalize_tool_arguments("[]", "write_file") == {}

    def test_json_scalar_returns_empty(self) -> None:
        assert _normalize_tool_arguments('"hello"', "write_file") == {}

    def test_invalid_json_returns_empty(self) -> None:
        assert _normalize_tool_arguments("{broken", "write_file") == {}

    def test_numeric_raw_returns_empty(self) -> None:
        """An integer is not a string — degrade safely."""
        assert _normalize_tool_arguments(42, "write_file") == {}

    def test_nested_object_passthrough(self) -> None:
        raw = json.dumps({"command": "echo 1", "options": {"verbose": True}})
        result = _normalize_tool_arguments(raw, "run_command")
        assert result["command"] == "echo 1"
        assert result["options"]["verbose"] is True

    @pytest.mark.parametrize("func_name", ["write_file", "read_file", "run_command", "apply_patch"])
    def test_none_for_every_tool(self, func_name: str) -> None:
        """None is a valid model output for any tool — must not raise."""
        assert _normalize_tool_arguments(None, func_name) == {}
