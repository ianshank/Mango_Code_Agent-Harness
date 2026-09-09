"""AQA-004: Regression pin for gaps.json memory integrity (RCA-6 / MEM-1).

Stub entries (``question="q"``, ``what_needed="w"``, ``proposed_approach="p"``)
are produced by failed reasoner runs calling ``knowledge_gap_log`` with
placeholder arguments. They corrupt agent memory and bloat the planner prompt
via ``format_gaps_for_planner`` (DEC-058).

**What this pins, and what it deliberately does not.** The store lives under
``.mango/memory/``, which `.gitignore` excludes: it is runtime state, not
repository content. An earlier version of this module asserted against the
ambient store at the install root and called ``pytest.skip()`` when the file was
absent — a zero-skip violation (INV-2). PR #121 replaced the skip with
``assert GAPS_PATH.is_file()``, which is the opposite error: it makes a green
run depend on a file a clean checkout never has, so it passed on a developer
machine that had run the agent and failed on every CI runner. Both versions
answered "what does *this* machine's memory happen to contain" when the
regression tier's question is "can the defect recur".

So this module drives the **real writer** into a temporary workspace and asserts
the properties the writer actually guarantees. It is deterministic, needs no
ambient state, and fails when the writer regresses.

One property is **not** asserted here because the code does not provide it:
``knowledge_gap_log`` performs no stub-value rejection — handed ``("q", "w",
"p")`` it writes them. ``test_the_stub_detector_is_not_vacuous`` pins the
detector instead, so the shape stays recognised; whether the writer should
refuse stub arguments is a tool-contract change and needs its own decision.
Scanning a live store for accumulated stubs is an operational check, not a test,
and belongs in a ``make`` target rather than the suite.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

import pytest

from harness.shared.meta_tools import knowledge_gap_log, load_open_gaps

logger = logging.getLogger(__name__)

pytestmark = pytest.mark.governance

#: Exact placeholder triple a failed ``knowledge_gap_log`` call writes (MEM-1).
STUB_QUESTION = "q"
STUB_WHAT_NEEDED = "w"
STUB_PROPOSED_APPROACH = "p"

#: Every field the writer puts on an entry. Asserted rather than assumed: a
#: reader (``format_gaps_for_planner``) uses ``question`` and ``what_needed``,
#: and ``id``/``timestamp`` are what make an entry addressable for cleanup.
REQUIRED_FIELDS = frozenset({"id", "timestamp", "question", "what_needed", "proposed_approach"})


def _gaps_file(workspace: Path) -> Path:
    return workspace / ".mango" / "memory" / "gaps.json"


def _is_stub(entry: dict[str, Any]) -> bool:
    """Whether ``entry`` is the MEM-1 placeholder triple."""
    return (
        entry.get("question") == STUB_QUESTION
        and entry.get("what_needed") == STUB_WHAT_NEEDED
        and entry.get("proposed_approach") == STUB_PROPOSED_APPROACH
    )


def test_the_writer_produces_a_json_array(tmp_path: Path) -> None:
    """The store's root must be a list — a scalar or null breaks every reader."""
    knowledge_gap_log("why does the gate pass?", "a run on the head", "read the check runs", workspace_dir=tmp_path)

    raw = json.loads(_gaps_file(tmp_path).read_text(encoding="utf-8"))
    assert isinstance(raw, list), f"gaps.json root must be a JSON array, got {type(raw).__name__}"


def test_every_written_entry_carries_the_required_fields(tmp_path: Path) -> None:
    """A partial entry reaches the planner prompt as a blank line (DEC-058)."""
    for index in range(3):
        knowledge_gap_log(f"question {index}", f"need {index}", f"approach {index}", workspace_dir=tmp_path)

    entries = json.loads(_gaps_file(tmp_path).read_text(encoding="utf-8"))
    assert entries, "the writer wrote nothing, so this assertion would inspect an empty corpus"
    offenders = [
        {"id": entry.get("id", "<no id>"), "missing": sorted(REQUIRED_FIELDS - set(entry))}
        for entry in entries
        if REQUIRED_FIELDS - set(entry)
    ]
    assert not offenders, f"entries missing required fields: {offenders}"


def test_substantive_input_is_never_written_as_a_stub(tmp_path: Path) -> None:
    """The writer must not mangle real arguments into the placeholder triple."""
    knowledge_gap_log("a real question", "real evidence", "a real approach", workspace_dir=tmp_path)

    entries = json.loads(_gaps_file(tmp_path).read_text(encoding="utf-8"))
    assert entries, "nothing was written, so nothing was checked"
    assert not [entry for entry in entries if _is_stub(entry)], (
        "substantive arguments were persisted as the MEM-1 placeholder triple"
    )


def test_the_stub_detector_is_not_vacuous(tmp_path: Path) -> None:
    """The detector must recognise the shape it exists to recognise.

    Without this, every assertion above would keep passing if `_is_stub` were
    changed to `return False` — a check that cannot fail rather than one that
    passed. `knowledge_gap_log` does not reject stub arguments today, so this
    drives them through the real writer and asserts they are detectable in the
    store the writer produced.
    """
    knowledge_gap_log(STUB_QUESTION, STUB_WHAT_NEEDED, STUB_PROPOSED_APPROACH, workspace_dir=tmp_path)

    entries = json.loads(_gaps_file(tmp_path).read_text(encoding="utf-8"))
    assert [entry for entry in entries if _is_stub(entry)], (
        "a stub written by the real writer was not detected; MEM-1 could recur unnoticed"
    )


def test_written_gaps_are_readable_by_the_planner_path(tmp_path: Path) -> None:
    """The store the writer produces must be the store the reader consumes.

    `load_open_gaps` is what `format_gaps_for_planner` calls, so a writer/reader
    disagreement about location or ordering silently empties the planner prompt.
    """
    knowledge_gap_log("oldest", "need-oldest", "approach-oldest", workspace_dir=tmp_path)
    knowledge_gap_log("newest", "need-newest", "approach-newest", workspace_dir=tmp_path)

    gaps = load_open_gaps(tmp_path)
    assert [gap["question"] for gap in gaps] == ["newest", "oldest"], (
        f"the reader did not see the writer's entries most-recent-first: {gaps}"
    )


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))
