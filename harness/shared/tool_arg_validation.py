"""Schema validation for model-generated tool arguments, at the dispatch boundary.

``tool_schemas.NEMOTRON_TOOLS`` advertises a JSON-schema ``parameters`` object
per tool -- ``required`` keys, per-property ``type``, and
``additionalProperties: false`` -- and nothing enforced any of it.
``_normalize_tool_arguments`` only coerced the field to a dict, so a missing
``filepath`` became ``""`` in the handler and reached the executor, where the
operating system rejected it (``IsADirectoryError`` on ``write_file ""``, a
directory listing on ``read_file ""``); extra keys passed through untouched
(2026 standards audit H7). A schema the model is shown and the harness does not
check is documentation the model has no reason to trust.

This is deliberately a small stdlib validator for the subset those schemas use,
not a ``jsonschema`` dependency: the lock is hashed and protected, and the
subset is four keywords. Keywords outside it are not interpreted, and a schema
that uses one is simply not checked on that axis -- this module narrows what
reaches an executor, it does not claim to be a conforming validator.

The reason strings name the offending *key* and the expected and observed JSON
*types*, never a value: they are returned to the model as a tool result and
logged, and tool arguments are exactly what the observability contract (H6)
says the logs must not carry.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

#: JSON-schema type keyword -> the Python types that satisfy it. ``bool`` is a
#: subclass of ``int`` in Python and a distinct type in JSON, so the integer and
#: number rows are checked with an explicit boolean exclusion in ``_matches``.
_JSON_TYPES: dict[str, tuple[type, ...]] = {
    "string": (str,),
    "integer": (int,),
    "number": (int, float),
    "boolean": (bool,),
    "array": (list,),
    "object": (dict,),
    "null": (type(None),),
}


def json_type_name(value: Any) -> str:
    """The JSON type name of a Python value, for a reason string."""
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, int):
        return "integer"
    if isinstance(value, float):
        return "number"
    if isinstance(value, str):
        return "string"
    if isinstance(value, list):
        return "array"
    if isinstance(value, dict):
        return "object"
    return type(value).__name__


def _matches(value: Any, expected: str) -> bool:
    accepted = _JSON_TYPES.get(expected)
    if accepted is None:
        # A type keyword this validator does not model is not a reason to
        # refuse the call: the axis is unchecked, which the module docstring
        # states, rather than every call under it denied.
        return True
    if expected in ("integer", "number") and isinstance(value, bool):
        return False
    return isinstance(value, accepted)


def invalid_arguments_reason(schema: Mapping[str, Any], args: Mapping[str, Any]) -> str | None:
    """Why ``args`` does not satisfy ``schema``, or ``None`` when it does.

    Checks, in order: every ``required`` key is present; no key outside
    ``properties`` is present when ``additionalProperties`` is ``false``; every
    present property whose schema declares a ``type`` (a name or a list of
    names) holds a value of that type. The first failure is reported, naming
    the key, so the model gets one actionable correction per turn.
    """
    properties = schema.get("properties")
    if not isinstance(properties, Mapping):
        properties = {}

    required = schema.get("required")
    for key in required if isinstance(required, (list, tuple)) else ():
        if key not in args:
            return f"missing required argument {key!r}"

    if schema.get("additionalProperties") is False:
        for key in args:
            if key not in properties:
                return f"unexpected argument {key!r}"

    for key, spec in properties.items():
        if key not in args or not isinstance(spec, Mapping):
            continue
        expected = spec.get("type")
        names = [expected] if isinstance(expected, str) else expected
        if not isinstance(names, (list, tuple)) or not names:
            continue
        value = args[key]
        if not any(isinstance(name, str) and _matches(value, name) for name in names):
            wanted = " or ".join(str(name) for name in names)
            return f"argument {key!r} must be {wanted}, got {json_type_name(value)}"
    return None


def parameter_schemas(tools: list[dict[str, Any]]) -> dict[str, Mapping[str, Any]]:
    """Index a tool list by function name onto its ``parameters`` schema.

    Entries that do not carry a ``function.name`` and a ``function.parameters``
    object are skipped: a tool with no schema is a tool the dispatcher cannot
    validate, and it decides what to do about that.
    """
    index: dict[str, Mapping[str, Any]] = {}
    for tool in tools:
        function = tool.get("function") if isinstance(tool, Mapping) else None
        if not isinstance(function, Mapping):
            continue
        name = function.get("name")
        schema = function.get("parameters")
        if isinstance(name, str) and name and isinstance(schema, Mapping):
            index[name] = schema
    return index


__all__ = ["invalid_arguments_reason", "json_type_name", "parameter_schemas"]
