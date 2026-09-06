"""Rendering the agent memory stores for a human reader.

The third layer of the memory split, and the one that keeps `meta_tools` inside
`limits.size_budget_lines`. `memory_store` is *how a store behaves*,
`meta_tools` is *what a record means and how the model writes one*, and this is
*how a person reads them back*. Presentation depends on both and neither
depends on it, so the layering stays one-directional:

    memory_store  <-  meta_tools  <-  memory_view  <-  show_memory (CLI)

Nothing here is reachable from the agent loop. `C-HR-2` pins that no prompt
builder reads the hypothesis store -- surfacing it into the reasoner is phase 2,
deferred behind the context-window budget (DEC-057) -- and rendering it to a
terminal on request costs no tokens on any run.
"""

from __future__ import annotations

from pathlib import Path

from harness.shared.meta_tools import (
    HYPOTHESIS_SUPERSEDED_BY,
    _hypotheses_path,
    _read_json_safe,
)


def successors_of(entry: dict) -> list:
    """The ids that revised ``entry``, oldest first; empty when none did.

    One definition of "what superseded this", used by every reader. The writer
    tolerates a scalar left by an earlier build of this branch, so a reader that
    assumed a list would iterate a uuid character by character; normalising in
    one place is what stops that from being three separate near-misses.
    """
    successors = entry.get(HYPOTHESIS_SUPERSEDED_BY)
    if isinstance(successors, str):
        return [successors]
    if isinstance(successors, list):
        return list(successors)
    return []


def load_hypotheses(workspace_dir: Path | None = None) -> list:
    """Return hypotheses most-recent-first (empty list when the store is absent).

    The read counterpart to ``hypothesis_register``, symmetric with
    ``load_open_gaps``. It feeds no prompt -- ``C-HR-2`` pins that, and phase 2
    is deferred behind the context-window budget (DEC-057) -- but a record
    nothing can read is not evidence, and DEC-057 claims the store gives the
    verifier and the debug dump a durable trail. This is what makes that claim
    checkable: it costs no tokens on any run, because only an operator (via
    ``make memory-show``) or a test ever calls it.
    """
    hypotheses_file = _hypotheses_path(workspace_dir)
    if not hypotheses_file.exists():
        return []
    return list(reversed(_read_json_safe(hypotheses_file)))


def format_hypotheses_for_review(
    hypotheses: list | None = None,
    *,
    workspace_dir: Path | None = None,
    limit: int | None = None,
) -> str:
    """Render the hypothesis store for a human, most recent first.

    Shows each entry's settled verdict and its place in the revision graph --
    the two things the record exists to preserve. ``limit`` truncates; ``None``
    shows everything, because an operator reading the store deliberately is not
    the prompt-size case ``planner_gap_limit`` exists to bound.
    """
    if hypotheses is None:
        hypotheses = load_hypotheses(workspace_dir)
    selected = list(hypotheses)[:limit] if limit is not None else list(hypotheses)
    if not selected:
        return "No hypotheses recorded.\n"
    lines = [f"Hypotheses ({len(selected)} shown, most recent first):"]
    for entry in selected:
        entry_id = entry.get("id", "?")
        marks = [str(entry.get("status", "?"))]
        if entry.get("revises"):
            marks.append(f"revises {entry['revises']}")
        successors = successors_of(entry)
        if successors:
            marks.append(f"superseded by {', '.join(str(s) for s in successors)}")
        lines.append(f"- [{entry_id}] ({'; '.join(marks)}) {entry.get('claim', '')}")
        lines.append(f"    confidence={entry.get('confidence', '?')} because: {entry.get('reasoning', '')}")
    return "\n".join(lines) + "\n"
