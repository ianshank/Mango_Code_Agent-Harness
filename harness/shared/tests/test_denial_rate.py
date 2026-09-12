"""Tests for harness/shared/governance/denial_rate.py.

The gate measures the usability cost of the command allowlist. Its own failure
mode is vacuity -- a rate over an empty corpus is zero -- so the population floor
gets as much attention here as the ceiling.

Spec: ``docs/specs/attested-execution-isolation.md`` (R-AEI-2, AC-3).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from harness.shared.governance import denial_rate
from harness.shared.tests._helpers import REPO

pytestmark = pytest.mark.governance

_AGENT_POLICY = REPO / "harness" / "shared" / "agent-policy.json"


def _policy(tmp_path: Path, *, rate: object = 0.0, floor: object = 2) -> Path:
    path = tmp_path / "governance-policy.json"
    path.write_text(
        json.dumps({denial_rate.POLICY_BLOCK: {"max_denial_rate": rate, "min_corpus_commands": floor}}),
        encoding="utf-8",
    )
    return path


def _corpus(tmp_path: Path, commands: list[str]) -> Path:
    path = tmp_path / "command-corpus.json"
    path.write_text(json.dumps({"commands": [{"command": c, "why": "test"} for c in commands]}), encoding="utf-8")
    return path


def _run(tmp_path: Path, commands: list[str], *, rate: object = 0.0, floor: object = 2) -> int:
    return denial_rate.main(
        [
            "--corpus",
            str(_corpus(tmp_path, commands)),
            "--policy",
            str(_policy(tmp_path, rate=rate, floor=floor)),
            "--agent-policy",
            str(_AGENT_POLICY),
        ]
    )


class TestCeiling:
    def test_a_corpus_within_the_ceiling_passes(self, tmp_path: Path) -> None:
        assert _run(tmp_path, ["pytest -q", "git status", "cat README.md"]) == 0

    def test_a_corpus_above_the_ceiling_fails(self, tmp_path: Path) -> None:
        """`nosuchprogram` is unmodelled, so it resolves to an action no role holds."""
        assert _run(tmp_path, ["pytest -q", "nosuchprogram --wat"]) == 1

    def test_the_ceiling_is_read_from_policy_not_hard_coded(self, tmp_path: Path) -> None:
        """The same corpus passes or fails purely on the policy value (C-AEI-2)."""
        commands = ["pytest -q", "nosuchprogram --wat"]
        assert _run(tmp_path, commands, rate=0.0) == 1
        assert _run(tmp_path, commands, rate=0.5) == 0


class TestPopulationFloor:
    def test_an_empty_corpus_fails_rather_than_scoring_zero(self, tmp_path: Path) -> None:
        """The vacuity this floor exists for: no commands means no measurement."""
        assert _run(tmp_path, []) == 1

    def test_a_corpus_one_below_the_floor_fails(self, tmp_path: Path) -> None:
        assert _run(tmp_path, ["pytest -q", "git status"], floor=3) == 1

    def test_a_corpus_at_the_floor_passes(self, tmp_path: Path) -> None:
        assert _run(tmp_path, ["pytest -q", "git status"], floor=2) == 0

    def test_deleting_the_denied_entries_cannot_rescue_a_failing_run(self, tmp_path: Path) -> None:
        """Dropping the denial takes the corpus under the floor, so it still fails."""
        assert _run(tmp_path, ["pytest -q", "git status", "nosuchprogram --wat"], floor=3) == 1
        assert _run(tmp_path, ["pytest -q", "git status"], floor=3) == 1


class TestFailsClosed:
    @pytest.mark.parametrize(
        "block",
        [{}, {"max_denial_rate": 0.0}, {"min_corpus_commands": 2}, {"max_denial_rate": "0", "min_corpus_commands": 2}],
    )
    def test_an_absent_or_malformed_threshold_exits_rather_than_defaulting(
        self, tmp_path: Path, block: dict[str, object]
    ) -> None:
        path = tmp_path / "governance-policy.json"
        path.write_text(json.dumps({denial_rate.POLICY_BLOCK: block}), encoding="utf-8")
        with pytest.raises(SystemExit):
            denial_rate.load_thresholds(path)

    def test_a_missing_policy_file_exits(self, tmp_path: Path) -> None:
        with pytest.raises(SystemExit):
            denial_rate.load_thresholds(tmp_path / "absent.json")

    def test_a_corpus_entry_without_a_command_exits(self, tmp_path: Path) -> None:
        path = tmp_path / "command-corpus.json"
        path.write_text(json.dumps({"commands": [{"why": "no command key"}]}), encoding="utf-8")
        with pytest.raises(SystemExit):
            denial_rate.load_corpus(path)

    def test_malformed_json_exits(self, tmp_path: Path) -> None:
        path = tmp_path / "broken.json"
        path.write_text("{not json", encoding="utf-8")
        with pytest.raises(SystemExit):
            denial_rate._load_json_object(path, "probe")

    def test_a_directory_path_is_unreadable_and_exits(self, tmp_path: Path) -> None:
        with pytest.raises(SystemExit):
            denial_rate._load_json_object(tmp_path, "probe")

    def test_a_non_object_root_exits(self, tmp_path: Path) -> None:
        path = tmp_path / "list.json"
        path.write_text("[]", encoding="utf-8")
        with pytest.raises(SystemExit):
            denial_rate._load_json_object(path, "probe")

    @pytest.mark.parametrize("payload", [{"entries": []}, {"commands": {}}])
    def test_a_corpus_without_a_commands_list_exits(self, tmp_path: Path, payload: dict[str, object]) -> None:
        path = tmp_path / "command-corpus.json"
        path.write_text(json.dumps(payload), encoding="utf-8")
        with pytest.raises(SystemExit):
            denial_rate.load_corpus(path)


class TestHeldActions:
    def test_held_actions_come_from_the_authority_model(self) -> None:
        """Restating them here would let a role change leave the gate stale."""
        held = denial_rate.held_actions(_AGENT_POLICY)
        assert "read" in held and "test_execute" in held
        assert "destructive" not in held

    def test_an_authority_model_with_no_agents_exits(self, tmp_path: Path) -> None:
        path = tmp_path / "agent-policy.json"
        path.write_text(json.dumps({"agents": []}), encoding="utf-8")
        with pytest.raises(SystemExit):
            denial_rate.held_actions(path)


class TestShippedCorpus:
    def test_the_repositorys_own_corpus_meets_its_own_thresholds(self) -> None:
        """The live assertion: this is the gate CI runs, on the real files."""
        assert denial_rate.main([]) == 0

    def test_the_shipped_corpus_clears_its_own_floor(self) -> None:
        thresholds = denial_rate.load_thresholds(denial_rate.DEFAULT_POLICY_PATH)
        commands = denial_rate.load_corpus(denial_rate.DEFAULT_CORPUS_PATH)
        assert len(commands) >= thresholds.min_corpus_commands

    def test_every_corpus_entry_carries_a_justification(self) -> None:
        """An entry nobody can justify is not a false denial; it should deny."""
        entries = json.loads(denial_rate.DEFAULT_CORPUS_PATH.read_text(encoding="utf-8"))["commands"]
        assert entries and all(str(e.get("why", "")).strip() for e in entries)
