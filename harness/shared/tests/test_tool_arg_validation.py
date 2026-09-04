"""``tool_arg_validation``: the advertised schema is the enforced schema.

The example tests pin each keyword the validator models; the property-style
tests draw random argument dicts under a fixed seed and check the verdict
against an independent oracle, so the validator is judged on the whole input
space the model can produce and not on the thirteen hand-picked cases the
audit counted (2026 standards audit H7). ``random`` rather than ``hypothesis``:
the latter is not in the hashed lock.
"""

from __future__ import annotations

import random
from collections.abc import Mapping
from typing import Any

import pytest

from harness.shared.tool_arg_validation import (
    invalid_arguments_reason,
    json_type_name,
    parameter_schemas,
)
from harness.shared.tool_schemas import NEMOTRON_TOOLS

WRITE_FILE: dict[str, Any] = {
    "type": "object",
    "properties": {"filepath": {"type": "string"}, "content": {"type": "string"}},
    "required": ["filepath", "content"],
    "additionalProperties": False,
}

READ_FILE: dict[str, Any] = {
    "type": "object",
    "properties": {
        "filepath": {"type": "string"},
        "start_line": {"type": "integer"},
        "end_line": {"type": "integer"},
    },
    "required": ["filepath"],
    "additionalProperties": False,
}


class TestRequiredKeys:
    def test_a_complete_call_is_accepted(self) -> None:
        assert invalid_arguments_reason(WRITE_FILE, {"filepath": "a.py", "content": "x"}) is None

    def test_a_missing_required_key_is_named(self) -> None:
        reason = invalid_arguments_reason(WRITE_FILE, {"content": "x"})
        assert reason == "missing required argument 'filepath'"

    def test_an_empty_call_names_the_first_missing_key(self) -> None:
        reason = invalid_arguments_reason(WRITE_FILE, {})
        assert reason is not None
        assert "filepath" in reason

    def test_a_present_null_is_a_type_failure_not_a_missing_key(self) -> None:
        """``{"filepath": null}`` is what ``.get(key) or ""`` silently turned into
        ``""`` -- the shape that reached the executor."""
        reason = invalid_arguments_reason(WRITE_FILE, {"filepath": None, "content": "x"})
        assert reason == "argument 'filepath' must be string, got null"


class TestAdditionalProperties:
    def test_an_extra_key_is_rejected_when_the_schema_forbids_it(self) -> None:
        reason = invalid_arguments_reason(WRITE_FILE, {"filepath": "a", "content": "b", "mode": "w"})
        assert reason == "unexpected argument 'mode'"

    def test_an_extra_key_is_allowed_when_the_schema_does_not_forbid_it(self) -> None:
        relaxed = {**WRITE_FILE, "additionalProperties": True}
        assert invalid_arguments_reason(relaxed, {"filepath": "a", "content": "b", "mode": "w"}) is None
        absent = {key: value for key, value in WRITE_FILE.items() if key != "additionalProperties"}
        assert invalid_arguments_reason(absent, {"filepath": "a", "content": "b", "mode": "w"}) is None


class TestTypes:
    @pytest.mark.parametrize(
        ("value", "expected_name"),
        [
            (None, "null"),
            (True, "boolean"),
            (3, "integer"),
            (2.5, "number"),
            ("s", "string"),
            ([1], "array"),
            ({"k": 1}, "object"),
        ],
    )
    def test_json_type_names(self, value: Any, expected_name: str) -> None:
        assert json_type_name(value) == expected_name

    def test_a_string_where_an_integer_is_declared_is_rejected(self) -> None:
        reason = invalid_arguments_reason(READ_FILE, {"filepath": "a", "start_line": "1"})
        assert reason == "argument 'start_line' must be integer, got string"

    def test_a_boolean_is_not_an_integer(self) -> None:
        """Python's ``bool`` subclasses ``int``; JSON's does not."""
        reason = invalid_arguments_reason(READ_FILE, {"filepath": "a", "end_line": True})
        assert reason == "argument 'end_line' must be integer, got boolean"

    def test_a_boolean_is_not_a_number(self) -> None:
        schema = {"properties": {"confidence": {"type": "number"}}}
        assert invalid_arguments_reason(schema, {"confidence": False}) is not None

    def test_an_integer_satisfies_number(self) -> None:
        schema = {"properties": {"confidence": {"type": "number"}}}
        assert invalid_arguments_reason(schema, {"confidence": 1}) is None

    def test_optional_keys_are_only_checked_when_present(self) -> None:
        assert invalid_arguments_reason(READ_FILE, {"filepath": "a"}) is None
        assert invalid_arguments_reason(READ_FILE, {"filepath": "a", "start_line": 2, "end_line": 4}) is None

    def test_a_type_list_accepts_any_member(self) -> None:
        schema = {"properties": {"n": {"type": ["integer", "null"]}}}
        assert invalid_arguments_reason(schema, {"n": None}) is None
        assert invalid_arguments_reason(schema, {"n": 3}) is None
        assert invalid_arguments_reason(schema, {"n": "3"}) == "argument 'n' must be integer or null, got string"

    def test_an_unmodelled_type_keyword_is_not_a_denial(self) -> None:
        schema = {"properties": {"n": {"type": "decimal"}}}
        assert invalid_arguments_reason(schema, {"n": "anything"}) is None

    def test_a_property_without_a_type_is_not_checked(self) -> None:
        schema = {"properties": {"n": {"description": "untyped"}}}
        assert invalid_arguments_reason(schema, {"n": object()}) is None

    def test_malformed_schema_parts_are_ignored_rather_than_raised_on(self) -> None:
        schema = {"properties": "not-a-mapping", "required": "filepath", "additionalProperties": False}
        # A string `required` is not a list of keys; a string `properties` has
        # no keys, so any argument is "unexpected" under additionalProperties.
        assert invalid_arguments_reason(schema, {}) is None
        assert invalid_arguments_reason(schema, {"x": 1}) == "unexpected argument 'x'"


class TestParameterSchemas:
    def test_every_advertised_tool_is_indexed(self) -> None:
        tools: list[dict[str, Any]] = NEMOTRON_TOOLS
        index = parameter_schemas(tools)
        assert set(index) == {tool["function"]["name"] for tool in tools}

    def test_entries_without_a_schema_are_skipped(self) -> None:
        tools: list[dict[str, Any]] = [
            {"type": "function"},
            {"type": "function", "function": {"name": "no_params"}},
            {"type": "function", "function": {"name": "", "parameters": {}}},
            {"type": "function", "function": {"name": "ok", "parameters": {"type": "object"}}},
        ]
        assert set(parameter_schemas(tools)) == {"ok"}


# --- property-style: random argument dicts against an independent oracle -----

_PROPERTY_KEYS = ("filepath", "content", "start_line", "end_line")
_JUNK_KEYS = ("mode", "encoding", "extra", "")
_TYPE_OK: dict[str, tuple[type, ...]] = {"string": (str,), "integer": (int,), "number": (int, float)}


def _random_value(rng: random.Random) -> Any:
    kind = rng.randrange(8)
    if kind == 0:
        return None
    if kind == 1:
        return rng.choice([True, False])
    if kind == 2:
        return rng.randrange(-5, 50)
    if kind == 3:
        return rng.random() * 10
    if kind == 4:
        return "".join(rng.choice("abc/._") for _ in range(rng.randrange(0, 6)))
    if kind == 5:
        return [rng.randrange(3) for _ in range(rng.randrange(3))]
    if kind == 6:
        return {"k": rng.randrange(3)}
    return rng.choice(["", "x", 0, 1])


_LIKELY: dict[str, tuple[Any, ...]] = {
    "filepath": ("a.py", "src/b.txt", ""),
    "content": ("", "x", "line\n"),
    "start_line": (1, 2, 10),
    "end_line": (1, 4, 20),
}


def _random_args(rng: random.Random, schema: Mapping[str, Any]) -> dict[str, Any]:
    """The schema's own keys are present often and well-typed most of the time;
    foreign keys -- the other schema's properties and outright junk -- are
    rare. Biased on purpose, so both verdicts are reached in bulk rather than
    the accepting one being a lottery ticket."""
    args: dict[str, Any] = {}
    own = tuple(schema["properties"])
    for key in own:
        if rng.random() < 0.75:
            args[key] = rng.choice(_LIKELY[key]) if rng.random() < 0.7 else _random_value(rng)
    for key in tuple(k for k in _PROPERTY_KEYS if k not in own) + _JUNK_KEYS:
        if rng.random() < 0.08:
            args[key] = _random_value(rng)
    return args


def _oracle(schema: Mapping[str, Any], args: Mapping[str, Any]) -> bool:
    """A second opinion written without looking at the validator's control flow."""
    properties = schema["properties"]
    if any(key not in args for key in schema["required"]):
        return False
    if schema.get("additionalProperties") is False and any(key not in properties for key in args):
        return False
    for key, spec in properties.items():
        if key in args:
            value = args[key]
            if isinstance(value, bool) and spec["type"] in ("integer", "number"):
                return False
            if not isinstance(value, _TYPE_OK[spec["type"]]):
                return False
    return True


class TestProperties:
    SEED = 20260904
    CASES = 2000

    @pytest.mark.parametrize("schema", [WRITE_FILE, READ_FILE], ids=["write_file", "read_file"])
    def test_verdict_agrees_with_the_oracle_and_never_raises(self, schema: dict[str, Any]) -> None:
        rng = random.Random(self.SEED)
        accepted = rejected = 0
        for _ in range(self.CASES):
            args = _random_args(rng, schema)
            reason = invalid_arguments_reason(schema, args)
            assert (reason is None) == _oracle(schema, args), (args, reason)
            if reason is None:
                accepted += 1
            else:
                rejected += 1
                # The reason names a key and never a value: a value could be
                # file content or a command line, which the logs must not carry.
                assert any(f"{key!r}" in reason for key in _PROPERTY_KEYS + _JUNK_KEYS), reason
                for value in args.values():
                    if isinstance(value, str) and len(value) > 2:
                        assert value not in reason
        # The generator has to reach both verdicts, or the agreement is vacuous.
        assert accepted > 50 and rejected > 50, (accepted, rejected)

    def test_an_accepted_dict_satisfies_every_modelled_keyword(self) -> None:
        """The positive direction stated on its own: whatever passes has every
        required key, no foreign key, and the declared type on every property."""
        rng = random.Random(self.SEED + 1)
        seen = 0
        for _ in range(self.CASES):
            args = _random_args(rng, READ_FILE)
            if invalid_arguments_reason(READ_FILE, args) is not None:
                continue
            seen += 1
            assert "filepath" in args and isinstance(args["filepath"], str)
            assert set(args) <= set(READ_FILE["properties"])
            for key in ("start_line", "end_line"):
                if key in args:
                    assert isinstance(args[key], int) and not isinstance(args[key], bool)
        assert seen > 20
