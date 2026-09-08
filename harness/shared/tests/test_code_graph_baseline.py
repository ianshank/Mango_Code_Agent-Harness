"""AC-GEA-8: a recorded baseline gates any code-property graph."""

from __future__ import annotations

import json

import pytest

from harness.shared.tests._helpers import REPO

pytestmark = pytest.mark.governance

BASELINE = REPO / "docs" / "reports" / "subagent-turn-token-baseline.json"


def test_code_graph_is_gated_on_a_recorded_baseline() -> None:
    """Fail a tree that builds a CPG without a measured baseline, and pin the baseline."""
    assert BASELINE.is_file(), "docs/reports/ must hold a tokens/tool-calls baseline before any CPG"
    payload = json.loads(BASELINE.read_text(encoding="utf-8"))
    turns = payload.get("turns")
    assert isinstance(turns, list) and len(turns) >= 3, "baseline must name at least three subagent turns"
    for turn in turns:
        assert isinstance(turn.get("tokens"), int) and turn["tokens"] >= 0
        assert isinstance(turn.get("tool_calls"), int) and turn["tool_calls"] >= 0
        assert turn.get("role")
    cpg = [
        path
        for path in (REPO / "harness").rglob("*.py")
        if path.name in {"cpg.py", "code_property_graph.py"} or "code_property_graph" in path.stem
    ]
    assert not cpg, f"a code-property graph exists before the baseline can justify it: {cpg}"
