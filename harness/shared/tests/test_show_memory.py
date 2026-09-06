"""The operator read path over the agent memory stores (`make memory-show`).

DEC-057 justifies hypothesis revision by the trail it leaves for the verifier
and the debug dump. Nothing read that trail, so the justification was not
checkable; these cover the reader that makes it so. The reader is deliberately
outside every prompt (C-HR-2) -- one of these tests pins that.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from harness.shared.memory_view import format_hypotheses_for_review, load_hypotheses, successors_of
from harness.shared.meta_tools import hypothesis_register, knowledge_gap_log
from harness.shared.show_memory import build_parser, main


def _entry_id(result: str) -> str:
    return result.split("ID: ", 1)[1].split(".", 1)[0]


@pytest.fixture
def workspace(tmp_path: Path) -> Path:
    ws = tmp_path / "ws"
    ws.mkdir()
    return ws


class TestLoadHypotheses:
    def test_absent_store_is_empty_not_an_error(self, workspace: Path) -> None:
        assert load_hypotheses(workspace) == []

    def test_entries_come_back_most_recent_first(self, workspace: Path) -> None:
        for claim in ("oldest", "middle", "newest"):
            hypothesis_register(claim, "r", 0.5, workspace_dir=workspace)
        assert [h["claim"] for h in load_hypotheses(workspace)] == ["newest", "middle", "oldest"]

    def test_a_malformed_store_is_recovered_rather_than_raising(self, workspace: Path) -> None:
        hypothesis_register("a", "r", 0.5, workspace_dir=workspace)
        store = workspace / ".mango" / "memory" / "hypotheses.json"
        store.write_text("{ not json", encoding="utf-8")
        assert load_hypotheses(workspace) == []
        assert list(store.parent.glob("hypotheses.json.malformed.*"))


class TestFormatHypothesesForReview:
    def test_empty_store_says_so_rather_than_rendering_nothing(self) -> None:
        assert "No hypotheses recorded" in format_hypotheses_for_review([])

    def test_the_revision_graph_is_legible_from_both_ends(self, workspace: Path) -> None:
        first = _entry_id(hypothesis_register("cache is stale", "timestamps differ", 0.6, workspace_dir=workspace))
        second = _entry_id(
            hypothesis_register(
                "the clock was wrong", "ntp drift", 0.95, workspace_dir=workspace, revises=first, status="retracted"
            )
        )
        rendered = format_hypotheses_for_review(load_hypotheses(workspace))

        assert f"revises {first}" in rendered
        assert f"superseded by {second}" in rendered
        # The whole point of the shape: the superseded entry still shows the
        # verdict it was written with, not a lifecycle word that replaced it.
        assert "provisional" in rendered and "retracted" in rendered
        assert "confidence=0.6" in rendered and "ntp drift" in rendered

    def test_limit_truncates_most_recent_first(self, workspace: Path) -> None:
        for claim in ("a", "b", "c"):
            hypothesis_register(claim, "r", 0.5, workspace_dir=workspace)
        rendered = format_hypotheses_for_review(load_hypotheses(workspace), limit=1)
        assert "1 shown" in rendered and "] (provisional) c" in rendered
        assert "] (provisional) a" not in rendered

    def test_a_scalar_superseded_by_from_an_older_build_still_renders(self, workspace: Path) -> None:
        """The store outlives the code, so the reader tolerates the pre-fix
        scalar rather than printing a character-by-character list."""
        hypothesis_register("a", "r", 0.5, workspace_dir=workspace)
        store = workspace / ".mango" / "memory" / "hypotheses.json"
        data = json.loads(store.read_text(encoding="utf-8"))
        data[0]["superseded_by"] = "legacy-id"
        store.write_text(json.dumps(data), encoding="utf-8")
        assert "superseded by legacy-id" in format_hypotheses_for_review(load_hypotheses(workspace))

    def test_a_partial_record_renders_without_raising(self) -> None:
        """Every field is read with a default: a hand-edited store must not
        crash the one tool an operator uses to inspect it."""
        rendered = format_hypotheses_for_review([{"claim": "only a claim"}])
        assert "only a claim" in rendered and "?" in rendered


class TestCli:
    def test_defaults_read_the_legacy_root_and_print_both_stores(self, capsys) -> None:
        assert main([]) == 0
        out = capsys.readouterr().out
        assert "Memory store:" in out
        assert "knowledge gaps" in out.lower()
        assert "hypothes" in out.lower()

    def test_an_empty_gap_store_is_reported_rather_than_blank(self, workspace: Path, capsys) -> None:
        """`format_gaps_for_planner` returns "" for an empty store because it
        feeds a prompt. A human who asked to see the store gets told instead."""
        assert main(["--workspace", str(workspace)]) == 0
        assert "No knowledge gaps recorded" in capsys.readouterr().out

    def test_store_selector_prints_only_what_was_asked_for(self, workspace: Path, capsys) -> None:
        knowledge_gap_log("q", "n", "a", workspace_dir=workspace)
        hypothesis_register("a claim", "r", 0.5, workspace_dir=workspace)

        assert main(["--workspace", str(workspace), "--store", "gaps"]) == 0
        gaps_only = capsys.readouterr().out
        assert "q" in gaps_only and "a claim" not in gaps_only

        assert main(["--workspace", str(workspace), "--store", "hypotheses"]) == 0
        hyp_only = capsys.readouterr().out
        assert "a claim" in hyp_only and "knowledge gaps" not in hyp_only.lower()

    def test_limit_is_applied_to_both_stores(self, workspace: Path, capsys) -> None:
        for i in range(3):
            knowledge_gap_log(f"q{i}", "n", "a", workspace_dir=workspace)
            hypothesis_register(f"claim{i}", "r", 0.5, workspace_dir=workspace)
        assert main(["--workspace", str(workspace), "--limit", "1"]) == 0
        out = capsys.readouterr().out
        assert out.count("- Q:") == 1
        assert "1 shown" in out

    def test_the_parser_rejects_an_unknown_store(self) -> None:
        with pytest.raises(SystemExit):
            build_parser().parse_args(["--store", "not-a-store"])


def test_the_reader_is_not_wired_into_any_prompt_or_gate() -> None:
    """C-HS-1 (narrowed from C-HR-2) and INV-5. The *operator* reader stays
    outside the agent loop: the CLI and the unbounded formatter must not appear
    in a prompt builder. Phase 2 (DEC-058) wired the *bounded* formatter from
    the same module into `loop.py`, so `memory_view` itself is no longer a
    forbidden name here; the call-graph pin in `test_hypothesis_revision.py`
    grades which of its functions a prompt builder may reach."""
    from harness.shared.tests._helpers import REPO

    for rel in ("harness/shared/agent_prompts.py", "harness/shared/orchestrator/loop.py"):
        text = (REPO / rel).read_text(encoding="utf-8")
        assert "show_memory" not in text
        assert "load_hypotheses" not in text
        assert "format_hypotheses_for_review" not in text


def test_successors_of_normalises_every_shape() -> None:
    """One definition of "what superseded this", so a reader cannot iterate a
    uuid character by character by assuming the list shape."""
    assert successors_of({}) == []
    assert successors_of({"superseded_by": None}) == []
    assert successors_of({"superseded_by": "legacy-scalar"}) == ["legacy-scalar"]
    assert successors_of({"superseded_by": ["a", "b"]}) == ["a", "b"]
    # A copy, not the stored list: a caller must not be able to mutate the record.
    entry = {"superseded_by": ["a"]}
    successors_of(entry).append("b")
    assert entry["superseded_by"] == ["a"]
