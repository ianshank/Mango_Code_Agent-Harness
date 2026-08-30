"""Shared primitive: read a JSON object file, classifying failure without raising.

`governance/broker.py` and `check_dedup.py` each parse a governance JSON file and
turn a missing/unreadable/malformed file into their own distinct fail-closed
behavior (a bare exception in one, a logged ``SystemExit(1)`` with a specific
message in the other). A primitive that itself raised would force one behavior
onto both callers -- exactly the coupling ``docs/specs/policy-single-source.md``
deliberately avoided for the runpy-invoked gate scripts (``validate_invariants.py``
stays standalone for the same reason). This module only classifies; each caller
keeps its own exception type and message.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class JsonObjectResult:
    """Outcome of reading `path` as a JSON object.

    `value` is set on success. Otherwise `error` is one of "not_found",
    "unreadable", or "malformed", with `detail` carrying the underlying reason.
    """

    value: dict[str, Any] | None = None
    error: str | None = None
    detail: str = ""


def read_json_object(path: Path) -> JsonObjectResult:
    """Read and parse `path` as a JSON object. Never raises; callers translate `error`."""
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return JsonObjectResult(error="not_found", detail=str(path))
    except OSError as e:
        return JsonObjectResult(error="unreadable", detail=str(e))
    try:
        parsed = json.loads(text)
    except ValueError as e:
        return JsonObjectResult(error="malformed", detail=str(e))
    if not isinstance(parsed, dict):
        return JsonObjectResult(
            error="malformed", detail=f"root must be a JSON object, got {type(parsed).__name__}"
        )
    return JsonObjectResult(value=parsed)
