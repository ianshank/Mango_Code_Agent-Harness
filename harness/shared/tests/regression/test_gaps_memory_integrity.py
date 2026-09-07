"""AQA-004: Regression pin for gaps.json memory integrity (RCA-6 / MEM-1).

Asserts that no entry in .mango/memory/gaps.json is a stub placeholder
(question="q", what_needed="w", proposed_approach="p").

Stub entries are produced by failed reasoner runs calling knowledge_gap_log
with placeholder arguments. They corrupt the agent memory and bloat the
planner prompt via format_gaps_for_planner() (DEC-058).

If this test fails, a reasoner run has written stub entries and the memory
requires cleanup (human attestation required for .mango/memory/ writes — DEC-007).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

REPO = Path(__file__).resolve().parents[4]
GAPS_PATH = REPO / ".mango" / "memory" / "gaps.json"

# Exact stub values produced by failed knowledge_gap_log calls
_STUB_QUESTION = "q"
_STUB_WHAT_NEEDED = "w"
_STUB_PROPOSED_APPROACH = "p"


def _load_gaps() -> list[dict[str, Any]]:
    if not GAPS_PATH.exists():
        pytest.skip(f"gaps.json not found at {GAPS_PATH}; skipping integrity check")
    try:
        return json.loads(GAPS_PATH.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        pytest.fail(f"gaps.json is not valid JSON: {e}")


def test_gaps_json_has_no_stub_entries() -> None:
    """No entry in gaps.json should be a stub placeholder (MEM-1 defect pin)."""
    gaps = _load_gaps()
    stubs = [
        {"id": entry.get("id"), "timestamp": entry.get("timestamp")}
        for entry in gaps
        if (
            entry.get("question") == _STUB_QUESTION
            and entry.get("what_needed") == _STUB_WHAT_NEEDED
            and entry.get("proposed_approach") == _STUB_PROPOSED_APPROACH
        )
    ]
    assert not stubs, (
        f"gaps.json contains {len(stubs)} stub placeholder entries "
        f"(question={_STUB_QUESTION!r}, what_needed={_STUB_WHAT_NEEDED!r}, "
        f"proposed_approach={_STUB_PROPOSED_APPROACH!r}). "
        "These are produced by failed knowledge_gap_log calls and corrupt the "
        "planner prompt. Remove them (requires infra-reviewed attestation DEC-007). "
        f"Stub entry IDs: {[s['id'] for s in stubs[:5]]}{'...' if len(stubs) > 5 else ''}"
    )


def test_gaps_json_is_valid_list() -> None:
    """gaps.json must be a JSON array (not null or a scalar)."""
    gaps = _load_gaps()
    assert isinstance(gaps, list), (
        f"gaps.json root must be a JSON array, got {type(gaps).__name__}. "
        "Corruption may have been introduced by a failed write."
    )


def test_gaps_json_substantive_entries_have_required_fields() -> None:
    """Every non-stub entry must have id, timestamp, question, what_needed, proposed_approach."""
    gaps = _load_gaps()
    required = {"id", "timestamp", "question", "what_needed", "proposed_approach"}
    offenders = []
    for entry in gaps:
        # Skip stub entries (caught by test_gaps_json_has_no_stub_entries)
        if (
            entry.get("question") == _STUB_QUESTION
            and entry.get("what_needed") == _STUB_WHAT_NEEDED
        ):
            continue
        missing = required - set(entry.keys())
        if missing:
            offenders.append({"id": entry.get("id", "<no id>"), "missing": sorted(missing)})
    assert not offenders, (
        f"The following gaps.json entries are missing required fields: {offenders}"
    )
