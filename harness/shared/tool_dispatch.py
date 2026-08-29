"""Tool call argument normalization and dispatch utilities."""

from __future__ import annotations

import json
import logging
from typing import Any

logger = logging.getLogger(__name__)

# Default confidence when the model omits it from a hypothesis_register call.
DEFAULT_HYPOTHESIS_CONFIDENCE = 0.5


def _normalize_tool_arguments(raw: Any, func_name: Any) -> dict[str, Any]:
    """Coerce a tool call's ``arguments`` field into a dict of keyword args.

    The field is model-generated and only conventionally a JSON object string.
    Two shapes crashed the previous implementation:

    * ``null`` -> ``json.loads(None)`` raises TypeError, which the surrounding
      ``except json.JSONDecodeError`` did not catch;
    * ``"[]"`` -> parses cleanly to a list, then every registry lambda dies on
      ``.get``.

    Both now degrade to no arguments, so a malformed call produces a tool
    result the model can react to rather than an unhandled exception.
    """
    if isinstance(raw, dict):
        return raw
    if not isinstance(raw, str) or not raw.strip():
        if raw is not None:
            logger.warning("Tool %s sent non-string arguments %r; treating as empty", func_name, type(raw).__name__)
        return {}
    try:
        parsed = json.loads(raw)
    except (json.JSONDecodeError, TypeError, ValueError):
        logger.warning("Tool %s sent unparseable arguments; treating as empty", func_name)
        return {}
    if not isinstance(parsed, dict):
        logger.warning(
            "Tool %s sent JSON %s arguments, expected an object; treating as empty",
            func_name, type(parsed).__name__,
        )
        return {}
    return parsed


__all__ = [
    "DEFAULT_HYPOTHESIS_CONFIDENCE",
    "_normalize_tool_arguments",
]
