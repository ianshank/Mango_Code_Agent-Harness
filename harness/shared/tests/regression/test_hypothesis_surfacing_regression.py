"""Regression pins: DEC-058 hypothesis surfacing survives its two defect classes.

`docs/specs/hypothesis-surfacing.md` / DEC-058 put the reasoner's open
hypotheses into a user message that `context_policy` never evicts. Two
properties make that affordable and reversible, and both are the kind a later
refactor breaks silently -- every unit test that renders a small store would
still pass -- so they are pinned in the regression tier (CONTRACT.md) as a
defect-class survival contract, the shape H4 set in
``test_context_window_budget_regression.py``:

1. **Eviction cannot rescue an oversized block.** Only the two `agent_memory`
   bounds stand between the store and the context budget. A "let eviction
   handle it" loosening of the bounds would fail only in production.
2. **An empty block leaves the reasoner prompt byte-identical** to the
   pre-DEC-058 prompt -- the promise every existing run and test relies on.

Unit coverage lives in ``test_hypothesis_surfacing.py``.
"""

from __future__ import annotations

import uuid
from pathlib import Path
from typing import Any

import pytest

from harness.shared.agent_prompts import REASONER_PROMPT_TEMPLATE
from harness.shared.context_policy import apply_context_policy, estimate_tokens
from harness.shared.memory_view import format_hypotheses_for_reasoner
from harness.shared.tests._helpers import snapshot_tree
from harness.shared.tests._orchestrator_helpers import _assistant_tools, _tool_call

pytestmark = pytest.mark.governance

CHARS_PER_TOKEN = 4.0
_STORE = ".mango/memory/hypotheses.json"


def _entry(claim: str) -> dict[str, Any]:
    return {"id": str(uuid.uuid4()), "claim": claim, "reasoning": "r", "confidence": 0.5, "status": "provisional"}


def _group(index: int, payload: str) -> list[dict[str, Any]]:
    call_id = f"call_{index}"
    return [
        _assistant_tools(_tool_call("write_file", {"filepath": f"{index}.txt", "content": "x"}, call_id=call_id)),
        {"role": "tool", "tool_call_id": call_id, "content": payload},
    ]


def test_eviction_cannot_rescue_an_oversized_hypothesis_block() -> None:
    """R-HS-6 degenerate case: the block survives every eviction and is sent over budget.

    This is why R-HS-3's bounds are load-bearing rather than defence in depth:
    the history has nothing left to shed once the groups are gone.
    """
    block = format_hypotheses_for_reasoner(
        [_entry("one"), _entry("two"), _entry("three")], limit=10, budget_tokens=10**6, chars_per_token=CHARS_PER_TOKEN
    )
    prompt = REASONER_PROMPT_TEMPLATE.format(plan="p", open_hypotheses=block)
    history: list[dict[str, Any]] = [{"role": "system", "content": "sys"}, {"role": "user", "content": prompt}]
    for index in (1, 2, 3):
        history.extend(_group(index, "x" * 2000))
    budget = estimate_tokens(history[:2], CHARS_PER_TOKEN) - 1

    kept, stats = apply_context_policy(history, budget, chars_per_token=CHARS_PER_TOKEN)

    assert kept == history[:2], "every group is gone and the block is still there"
    assert stats["messages_evicted"] == 6
    assert stats["tokens_after"] > budget, "over budget and sent as-is: only the policy bounds limit this message"
    assert block in kept[1]["content"]


def test_empty_hypothesis_block_leaves_the_reasoner_prompt_unchanged(tmp_path: Path) -> None:
    """R-HS-5: absent store, empty store, and the rendered prompt, byte for byte."""
    workspace = tmp_path / "ws"
    workspace.mkdir()
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
