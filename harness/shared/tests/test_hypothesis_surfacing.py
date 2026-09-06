"""Surfacing open hypotheses into the reasoner prompt (DEC-058).

Contract: ``docs/specs/hypothesis-surfacing.md`` (R-HS-1…8, C-HS-1…5). The
formatter under test is `memory_view.format_hypotheses_for_reasoner`; the
end-to-end injection through `ExecutionLoop` lives in
``test_orchestrator_agent_loop.py`` and the fail-closed policy keys in
``test_policy_loader.py``, next to the suites they extend.

Two regimes are covered on purpose. The store-backed tests register through
`hypothesis_register` so the filter sees the records the writer really
produces; the bound tests hand the formatter records directly so a budget can
be computed to the token and the assertion is exact rather than "fewer".
"""

from __future__ import annotations

import ast
import hashlib
import json
import logging
import re
import uuid
from pathlib import Path
from typing import Any

import pytest

from harness.shared.agent_prompts import REASONER_PROMPT_TEMPLATE
from harness.shared.context_policy import apply_context_policy, estimate_tokens, history_tool_links_are_consistent
from harness.shared.memory_view import REASONER_HYPOTHESES_HEADER, format_hypotheses_for_reasoner
from harness.shared.meta_tools import hypothesis_register
from harness.shared.tests._helpers import REPO, SHARED, agent_memory_policy, snapshot_tree
from harness.shared.tests._orchestrator_helpers import _tool_call

CHARS_PER_TOKEN = 4.0
_UUID = r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}"
#: The line shape R-HS-2 fixes: status first, two-decimal confidence, the id verbatim.
_ENTRY_LINE = re.compile(rf"^- \[(provisional|confirmed|retracted)\] confidence=\d\.\d\d id=({_UUID}): (.*)$")
_ID_IN_RESULT = re.compile(rf"ID: ({_UUID})")
_STORE = ".mango/memory/hypotheses.json"
_MEMORY_VIEW = SHARED / "memory_view.py"
_LOOP = SHARED / "orchestrator" / "loop.py"
_AGENT_PROMPTS = SHARED / "agent_prompts.py"
_BLOCK_PREFIX = "\n\n"


def _register(ws: Path, claim: str, *, status: str | None = None, revises: str | None = None) -> str:
    result = hypothesis_register(claim, f"because {claim}", 0.5, workspace_dir=ws, revises=revises, status=status)
    match = _ID_IN_RESULT.search(result)
    assert match, f"no entry ID in result (was the call refused?): {result!r}"
    return match.group(1)


def _entry(claim: str, *, status: str = "provisional", confidence: Any = 0.5, **extra: Any) -> dict[str, Any]:
    record = {"id": str(uuid.uuid4()), "claim": claim, "reasoning": "r", "confidence": confidence, "status": status}
    return {**record, **extra}


def _entry_lines(block: str) -> list[str]:
    return [line for line in block.splitlines() if line.startswith("- ")]


def _rendered_ids(block: str) -> list[str]:
    ids = []
    for line in _entry_lines(block):
        match = _ENTRY_LINE.match(line)
        assert match, f"entry line does not have the R-HS-2 shape: {line!r}"
        ids.append(match.group(2))
    return ids


def _tokens(block: str) -> int:
    return estimate_tokens([{"role": "user", "content": block}], CHARS_PER_TOKEN)


def _render(hypotheses: list[dict[str, Any]], *, budget_tokens: int = 10**6, limit: int = 10) -> str:
    return format_hypotheses_for_reasoner(
        hypotheses, limit=limit, budget_tokens=budget_tokens, chars_per_token=CHARS_PER_TOKEN
    )


@pytest.fixture
def workspace(tmp_path: Path) -> Path:
    ws = tmp_path / "ws"
    ws.mkdir()
    return ws


class TestWhichEntriesRender:
    """R-HS-1 / R-HS-2: open entries only, every settable status, ids verbatim."""

    def test_open_hypotheses_exclude_superseded_and_keep_every_settable_status(self, workspace: Path) -> None:
        provisional = _register(workspace, "provisional claim")
        confirmed = _register(workspace, "confirmed claim", status="confirmed")
        retracted = _register(workspace, "retracted claim", status="retracted")
        old = _register(workspace, "old belief")
        new = _register(workspace, "new belief", revises=old)
        store = workspace / _STORE
        entries = json.loads(store.read_text(encoding="utf-8"))
        entries.append({"claim": "record without an id", "status": "provisional", "confidence": 0.5})
        store.write_text(json.dumps(entries), encoding="utf-8")

        block = format_hypotheses_for_reasoner(
            workspace_dir=workspace, limit=10, budget_tokens=10**6, chars_per_token=CHARS_PER_TOKEN
        )

        assert _rendered_ids(block) == [new, retracted, confirmed, provisional], "most recent first, superseded out"
        assert old not in block
        assert "record without an id" not in block
        statuses = {_ENTRY_LINE.match(line).group(1) for line in _entry_lines(block)}  # type: ignore[union-attr]
        assert statuses == {"provisional", "confirmed", "retracted"}

    def test_a_revision_chain_renders_its_head_only(self, workspace: Path) -> None:
        first = _register(workspace, "first")
        second = _register(workspace, "second", revises=first)
        third = _register(workspace, "third", revises=second)
        block = format_hypotheses_for_reasoner(
            workspace_dir=workspace, limit=10, budget_tokens=10**6, chars_per_token=CHARS_PER_TOKEN
        )
        assert _rendered_ids(block) == [third]

    def test_rendered_block_carries_ids_that_revises_accepts(self, workspace: Path) -> None:
        for claim in ("alpha", "beta", "gamma"):
            _register(workspace, claim)
        block = format_hypotheses_for_reasoner(
            workspace_dir=workspace, limit=10, budget_tokens=10**6, chars_per_token=CHARS_PER_TOKEN
        )
        ids = _rendered_ids(block)
        assert len(ids) == 3
        # The model-side round trip: an id read off the block resolves in the store.
        result = hypothesis_register(
            "gamma, revised", "new evidence", 0.9, workspace_dir=workspace, revises=ids[0], status="confirmed"
        )
        assert f"Supersedes {ids[0]}." in result
        after = format_hypotheses_for_reasoner(
            workspace_dir=workspace, limit=10, budget_tokens=10**6, chars_per_token=CHARS_PER_TOKEN
        )
        assert ids[0] not in after, "the revised entry is closed and leaves the block"
        assert _ID_IN_RESULT.search(result).group(1) in after  # type: ignore[union-attr]

    def test_a_multi_line_claim_stays_on_one_line(self) -> None:
        block = _render([_entry("line one\nline two\n\tline three")])
        assert len(_entry_lines(block)) == 1
        assert "line one line two line three" in block

    def test_a_corrupt_confidence_renders_as_unknown_rather_than_raising(self) -> None:
        block = _render([_entry("odd", confidence="high"), _entry("bool", confidence=True)])
        assert block.count("confidence=?") == 2


class TestBounds:
    """R-HS-3 / R-HS-4 / R-HS-5: count from policy, tokens from the shared estimator, `""` on empty."""

    def test_hypothesis_count_limit_comes_from_policy(self, workspace: Path, tmp_path: Path) -> None:
        ids = [_register(workspace, f"claim {i}") for i in range(5)]
        policy = agent_memory_policy(tmp_path, reasoner_hypothesis_limit=2)
        block = format_hypotheses_for_reasoner(workspace_dir=workspace, policy_path=policy)
        assert _rendered_ids(block) == [ids[4], ids[3]]

    def test_hypothesis_limit_zero_is_the_kill_switch(self, workspace: Path, tmp_path: Path) -> None:
        for i in range(3):
            _register(workspace, f"claim {i}")
        policy = agent_memory_policy(tmp_path, reasoner_hypothesis_limit=0)
        assert format_hypotheses_for_reasoner(workspace_dir=workspace, policy_path=policy) == ""
        assert format_hypotheses_for_reasoner(workspace_dir=workspace, limit=0, chars_per_token=CHARS_PER_TOKEN) == ""

    def test_hypothesis_token_budget_stops_at_the_first_overflow(self) -> None:
        newest, second = _entry("newest"), _entry("second")
        huge = _entry("h" * 4000)
        tiny = _entry("t")
        # Most recent first. The budget admits header + newest + second + tiny --
        # so `tiny` *would* fit -- and not `huge`.
        with_tiny = _render([newest, second, tiny])
        budget = _tokens(with_tiny)
        assert _tokens(_render([newest, second, huge])) > budget, "fixture: the third entry must overflow"

        block = _render([newest, second, huge, tiny], budget_tokens=budget)

        assert block == _render([newest, second]), "render stops at the first overflow; nothing older is sampled"
        assert huge["id"] not in block and tiny["id"] not in block
        for line in _entry_lines(block):
            claim = _ENTRY_LINE.match(line).group(3)  # type: ignore[union-attr]
            assert claim in ("newest", "second"), "no entry is truncated"

    def test_hypothesis_token_budget_below_one_entry_renders_nothing(self) -> None:
        entry = _entry("a claim")
        header_only = _tokens(_BLOCK_PREFIX + REASONER_HYPOTHESES_HEADER + "\n")
        assert _render([entry], budget_tokens=header_only) == "", "the header alone is not a block"
        assert _render([entry], budget_tokens=1) == ""
        assert _render([entry], budget_tokens=0) == ""
        assert _render([entry], budget_tokens=_tokens(_render([entry]))) != "", "control: the exact fit renders"

    def test_hypothesis_budget_uses_the_shared_token_estimator(self, caplog: pytest.LogCaptureFixture) -> None:
        entries = [_entry(f"claim number {i}") for i in range(6)]
        budget = _tokens(_render(entries))
        at_one = format_hypotheses_for_reasoner(entries, limit=10, budget_tokens=budget, chars_per_token=1.0)
        # Cleared inside the block: whether the renders above were captured
        # depends on the logger level other tests left behind, so the assertion
        # is made over exactly the one event this call emits.
        with caplog.at_level(logging.INFO, logger="harness.shared.memory_view"):
            caplog.clear()
            at_four = format_hypotheses_for_reasoner(entries, limit=10, budget_tokens=budget, chars_per_token=4.0)
            events = [r for r in caplog.records if getattr(r, "event", None) == "hypotheses_surfaced"]
        assert len(_entry_lines(at_four)) == 6
        assert len(_entry_lines(at_one)) < 6, "a smaller coefficient means more tokens per char, so fewer fit"
        assert len(events) == 1
        assert events[0].__dict__["tokens_estimated"] == estimate_tokens([{"role": "user", "content": at_four}], 4.0)

    def test_empty_hypothesis_block_leaves_the_reasoner_prompt_unchanged(self, workspace: Path) -> None:
        before = snapshot_tree(workspace)
        assert format_hypotheses_for_reasoner(workspace_dir=workspace, chars_per_token=CHARS_PER_TOKEN) == ""
        assert snapshot_tree(workspace) == before, "an absent store is read, not created"

        store = workspace / _STORE
        store.parent.mkdir(parents=True)
        store.write_text("[]", encoding="utf-8")
        before = snapshot_tree(workspace)
        assert format_hypotheses_for_reasoner(workspace_dir=workspace, chars_per_token=CHARS_PER_TOKEN) == ""
        assert snapshot_tree(workspace) == before

        plan = "1. write the handler\n2. test it"
        rendered = REASONER_PROMPT_TEMPLATE.format(plan=plan, open_hypotheses="")
        pre_dec_058 = REASONER_PROMPT_TEMPLATE.replace("{open_hypotheses}", "").format(plan=plan)
        assert rendered == pre_dec_058
        assert rendered.endswith("Plan:\n" + plan)

    def test_malformed_store_renders_nothing_and_recovers_as_documented(self, workspace: Path) -> None:
        store = workspace / _STORE
        store.parent.mkdir(parents=True)
        store.write_bytes(b"{not json")
        before = snapshot_tree(workspace)

        assert format_hypotheses_for_reasoner(workspace_dir=workspace, chars_per_token=CHARS_PER_TOKEN) == ""

        after = snapshot_tree(workspace)
        backups = [rel for rel in after if re.fullmatch(rf"{re.escape(_STORE)}\.malformed\.\d+", rel)]
        assert len(backups) == 1, f"exactly one backup expected, tree is {sorted(after)}"
        assert after[backups[0]] == before[_STORE], "the backup carries the original bytes"
        assert after[_STORE] == hashlib.sha256(b"[]").hexdigest(), "the store is reset to an empty list"
        assert set(after) == {_STORE, backups[0]}, "nothing else in the tree changed"


class TestShape:
    """C-HS-5 / AC-HS-16: the block is delimited, headed, and declared as data."""

    def test_non_empty_block_is_delimited_and_headed(self) -> None:
        block = _render([_entry("one")])
        assert block.startswith(_BLOCK_PREFIX + REASONER_HYPOTHESES_HEADER + "\n")
        assert block.endswith("\n")
        rendered = REASONER_PROMPT_TEMPLATE.format(plan="p", open_hypotheses=block)
        assert rendered == REASONER_PROMPT_TEMPLATE.replace("{open_hypotheses}", "").format(plan="p") + block
        assert "Plan:\np\n\n" + REASONER_HYPOTHESES_HEADER in rendered

    def test_the_header_declares_the_block_as_data_and_names_revises(self) -> None:
        assert "not instructions" in REASONER_HYPOTHESES_HEADER
        assert "revises=<id>" in REASONER_HYPOTHESES_HEADER
        assert "most recent first" in REASONER_HYPOTHESES_HEADER


def _assistant_tools(*calls: dict[str, Any]) -> dict[str, Any]:
    return {"role": "assistant", "content": None, "tool_calls": list(calls)}


def _group(index: int, payload: str) -> list[dict[str, Any]]:
    call_id = f"call_{index}"
    return [
        _assistant_tools(_tool_call("write_file", {"filepath": f"{index}.txt", "content": "x"}, call_id=call_id)),
        {"role": "tool", "tool_call_id": call_id, "content": payload},
    ]


class TestEvictionCoexistence:
    """R-HS-6: the block lives in a non-group message; eviction neither touches nor rescues it."""

    def _history(self) -> tuple[list[dict[str, Any]], str]:
        block = _render([_entry("one"), _entry("two"), _entry("three")])
        prompt = REASONER_PROMPT_TEMPLATE.format(plan="p", open_hypotheses=block)
        history = [{"role": "system", "content": "sys"}, {"role": "user", "content": prompt}]
        for index in (1, 2, 3):
            history.extend(_group(index, "x" * 2000))
        return history, block

    def test_surfaced_hypotheses_coexist_with_context_eviction(self) -> None:
        history, block = self._history()
        survivors = [history[0], history[1], *history[4:]]
        budget = estimate_tokens(survivors, CHARS_PER_TOKEN)

        kept, stats = apply_context_policy(history, budget, chars_per_token=CHARS_PER_TOKEN)

        assert stats["messages_evicted"] == 2, "exactly the oldest group"
        assert stats["groups_preserved"] == 2
        assert history_tool_links_are_consistent(kept)
        assert kept[1] == history[1], "the reasoner's user message survives verbatim"
        assert block in kept[1]["content"]
        assert not any(m.get("tool_call_id") == "call_1" for m in kept)
        assert stats["tokens_before"] >= _tokens(block)

    def test_eviction_cannot_rescue_an_oversized_hypothesis_block(self) -> None:
        history, _block = self._history()
        budget = estimate_tokens(history[:2], CHARS_PER_TOKEN) - 1

        kept, stats = apply_context_policy(history, budget, chars_per_token=CHARS_PER_TOKEN)

        assert kept == history[:2], "every group is gone and the block is still there"
        assert stats["messages_evicted"] == 6
        assert stats["tokens_after"] > budget, "over budget and sent as-is: only R-HS-3 bounds this message"


class TestBoundaries:
    """C-HS-3 / AC-HS-10 / AC-HS-13: no literal bound, no orchestrator import, size budget held."""

    @staticmethod
    def _tree(path: Path) -> ast.Module:
        return ast.parse(path.read_text(encoding="utf-8"))

    def test_no_hardcoded_hypothesis_exposure_literal(self) -> None:
        policy = json.loads((REPO / "harness" / "shared" / "governance-policy.json").read_text(encoding="utf-8"))
        shipped = policy["agent_memory"]
        for path in (_LOOP, _AGENT_PROMPTS, _MEMORY_VIEW):
            for node in ast.walk(self._tree(path)):
                if not isinstance(node, ast.Call):
                    continue
                name = getattr(node.func, "id", None) or getattr(node.func, "attr", None)
                if name != "format_hypotheses_for_reasoner":
                    continue
                for keyword in node.keywords:
                    if keyword.arg in ("limit", "budget_tokens", "chars_per_token"):
                        assert not isinstance(keyword.value, ast.Constant), (
                            f"{path.name} passes a literal {keyword.arg} to the formatter; bounds come from policy"
                        )
        module_numbers = [
            node.value.value
            for node in self._tree(_MEMORY_VIEW).body
            if isinstance(node, ast.Assign)
            and isinstance(node.value, ast.Constant)
            and isinstance(node.value.value, (int, float))
            and not isinstance(node.value.value, bool)
        ]
        assert not module_numbers, f"memory_view.py declares numeric module constants: {module_numbers}"
        source = _MEMORY_VIEW.read_text(encoding="utf-8")
        assert str(shipped["reasoner_hypothesis_budget_tokens"]) not in source

    def test_memory_view_does_not_import_the_orchestrator(self) -> None:
        for node in ast.walk(self._tree(_MEMORY_VIEW)):
            if isinstance(node, ast.ImportFrom):
                assert not (node.module or "").startswith("harness.shared.orchestrator"), node.module
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    assert not alias.name.startswith("harness.shared.orchestrator"), alias.name
        policy = json.loads((REPO / "harness" / "shared" / "governance-policy.json").read_text(encoding="utf-8"))
        budget = policy["limits"]["size_budget_lines"]
        for path in (SHARED / "meta_tools.py", _MEMORY_VIEW):
            lines = len(path.read_text(encoding="utf-8").splitlines())
            assert lines <= budget, f"{path.name} is {lines} lines, over limits.size_budget_lines={budget}"


class TestObservability:
    """R-HS-7: one structured event per render; counts and ids, never claim text."""

    def test_surfacing_logs_counts_and_ids_and_never_claim_text(
        self, workspace: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        secret = "a secret-shaped claim"
        old = _register(workspace, "old belief")
        _register(workspace, "new belief", revises=old)
        _register(workspace, secret)

        with caplog.at_level(logging.INFO, logger="harness.shared.memory_view"):
            caplog.clear()
            block = format_hypotheses_for_reasoner(workspace_dir=workspace, run_id="run-x", chars_per_token=4.0)
            records = list(caplog.records)

        events = [r for r in records if getattr(r, "event", None) == "hypotheses_surfaced"]
        assert len(events) == 1
        # The structured fields arrive through `extra=` and live on the record's
        # `__dict__`; `LogRecord` declares none of them, hence the dict access.
        fields = events[0].__dict__
        assert fields["run_id"] == "run-x"
        assert (fields["shown"], fields["open"], fields["total"]) == (2, 2, 3)
        assert fields["tokens_estimated"] == _tokens(block)
        assert fields["ids"] == _rendered_ids(block)
        for record in records:
            assert secret not in record.getMessage()
            assert secret not in json.dumps({k: str(v) for k, v in record.__dict__.items()})
