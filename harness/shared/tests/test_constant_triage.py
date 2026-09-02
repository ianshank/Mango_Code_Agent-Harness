"""Every operational constant is either a policy value or an accepted decision.

The tech-debt audit found operational limits declared as module literals with
no link to `governance-policy.json` and no decision recording why not. Two
states are allowed and a third is not (tech-debt-hardening-plan R-TDH-16):

* **policy** -- the constant equals a policy value, read through
  `policy_loader` or equality-pinned to it (the adopter-fallback pattern
  `test_policy_consistency.py` already applies).
* **decision** -- the constant is named in one decision-log entry that says
  why it is a true constant (a protocol ceiling, an operator env knob with a
  documented default, a client-local resilience default).
* unlinked -- not allowed. A new constant needs a row here, and a row needs a
  policy key or a `DEC-` id.

The table is the inventory; the test is what stops it rotting.
"""

from __future__ import annotations

import importlib
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest

from harness.shared.tests._helpers import REPO

pytestmark = pytest.mark.governance

POLICY = REPO / "harness" / "shared" / "governance-policy.json"
DECISION_LOG = REPO / "harness" / "node" / ".governance" / "decision-log.md"


@dataclass(frozen=True)
class Row:
    """One constant. `module` is dotted for Python, a repo-relative path for other stacks."""

    module: str
    symbol: str
    policy_key: str | None = None
    decision: str | None = None

    @property
    def is_python(self) -> bool:
        return not self.module.endswith((".ts", ".js"))


TRIAGE: tuple[Row, ...] = (
    # policy-linked
    Row(
        "harness.shared.governance.process_backend",
        "DEFAULT_MAX_OUTPUT_BYTES",
        policy_key="orchestrator.max_output_bytes",
    ),
    Row("harness.shared.governance.process_backend", "DEFAULT_TIMEOUT_SEC", policy_key="orchestrator.tool_timeout_sec"),
    Row("harness.shared.retry_policy", "DEFAULT_MAX_RETRIES", policy_key="nemotron.max_retries"),
    Row("harness.shared.validate_invariants", "SIZE_BUDGET_LINES", policy_key="limits.size_budget_lines"),
    Row("harness.shared.check_dedup", "DEFAULT_MAX_SHIM_LINES", policy_key="dedup.max_shim_lines"),
    # accepted by decision
    Row("harness.shared.retry_policy", "DEFAULT_BASE_SEC", decision="DEC-025"),
    Row("harness.shared.retry_policy", "DEFAULT_MAX_SEC", decision="DEC-025"),
    Row("harness.shared.retry_policy", "DEFAULT_JITTER_RATIO", decision="DEC-025"),
    Row("harness.shared.shadow_planner", "DEFAULT_SHADOW_TIMEOUT_SEC", decision="DEC-025"),
    Row("harness.shared.cognitive_signal", "MAX_SIGNAL_BYTES", decision="DEC-025"),
    Row("harness.shared.cognitive_signal", "MAX_SINK_BYTES", decision="DEC-025"),
    Row("harness/node/src/ai/nemotron/circuit-breaker.ts", "failureThreshold", decision="DEC-025"),
    Row("harness/node/src/ai/nemotron/nemotron-client.ts", "baseBackoffMs", decision="DEC-025"),
)


def _lookup(policy: dict[str, Any], dotted: str) -> Any:
    node: Any = policy
    for part in dotted.split("."):
        assert isinstance(node, dict) and part in node, f"policy has no key {dotted!r}"
        node = node[part]
    return node


def decision_entries(log_text: str) -> dict[str, str]:
    """`DEC-nnn` -> the full log line, for the pipe-delimited log format."""
    entries: dict[str, str] = {}
    for line in log_text.splitlines():
        match = re.match(r"^\d{4}-\d{2}-\d{2}\s*\|\s*(DEC-\d+)\s*\|", line)
        if match:
            entries[match.group(1)] = line
    return entries


def check_row(row: Row, policy: dict[str, Any], decisions: dict[str, str]) -> str | None:
    """None when the row is satisfied, else a reason."""
    if (row.policy_key is None) == (row.decision is None):
        return "a row needs exactly one of policy_key or decision"
    if row.policy_key is not None:
        if not row.is_python:
            return "policy-linked rows must be Python modules this test can import"
        value = getattr(importlib.import_module(row.module), row.symbol)
        expected = _lookup(policy, row.policy_key)
        if value != expected:
            return f"{row.module}.{row.symbol} is {value!r} but policy {row.policy_key} is {expected!r}"
        return None
    assert row.decision is not None
    line = decisions.get(row.decision)
    if line is None:
        return f"{row.decision} is not in the decision log"
    if row.symbol not in line or Path(row.module).name.split(".")[0] not in line and row.module not in line:
        return f"{row.decision} does not name {row.module} / {row.symbol}"
    return None


@pytest.fixture(scope="module")
def policy() -> dict[str, Any]:
    loaded = json.loads(POLICY.read_text(encoding="utf-8"))
    assert isinstance(loaded, dict), "governance-policy.json must be a JSON object"
    return loaded


@pytest.fixture(scope="module")
def decisions() -> dict[str, str]:
    entries = decision_entries(DECISION_LOG.read_text(encoding="utf-8"))
    assert entries, "the decision-log parser found no entries; the format changed or the file moved"
    return entries


class TestEveryConstantIsPolicyOrDecision:
    @pytest.mark.parametrize("row", TRIAGE, ids=lambda r: f"{r.module}:{r.symbol}")
    def test_row_is_satisfied(self, row: Row, policy: dict[str, Any], decisions: dict[str, str]) -> None:
        reason = check_row(row, policy, decisions)
        assert reason is None, reason

    def test_the_table_is_not_empty(self) -> None:
        assert len(TRIAGE) >= 10

    def test_every_python_symbol_exists(self) -> None:
        for row in TRIAGE:
            if row.is_python:
                assert hasattr(importlib.import_module(row.module), row.symbol), f"{row.module}.{row.symbol} is gone"


class TestCheckerSemantics:
    """Negative cases: the checker must fail on each way a row can be wrong."""

    def test_unlinked_row_is_rejected(self, policy: dict[str, Any], decisions: dict[str, str]) -> None:
        assert check_row(Row("harness.shared.retry_policy", "DEFAULT_BASE_SEC"), policy, decisions)

    def test_missing_decision_is_rejected(self, policy: dict[str, Any]) -> None:
        reason = check_row(Row("harness.shared.retry_policy", "DEFAULT_BASE_SEC", decision="DEC-999"), policy, {})
        assert reason and "not in the decision log" in reason

    def test_decision_that_does_not_name_the_constant_is_rejected(self, policy: dict[str, Any]) -> None:
        fake = {"DEC-1": "2026-01-01 | DEC-1 | something unrelated | owner"}
        reason = check_row(Row("harness.shared.retry_policy", "DEFAULT_BASE_SEC", decision="DEC-1"), policy, fake)
        assert reason and "does not name" in reason

    def test_policy_mismatch_is_rejected(self, decisions: dict[str, str]) -> None:
        drifted = {"nemotron": {"max_retries": 42}}
        row = Row("harness.shared.retry_policy", "DEFAULT_MAX_RETRIES", policy_key="nemotron.max_retries")
        reason = check_row(row, drifted, decisions)
        assert reason and "but policy" in reason

    def test_parser_reads_the_log_format(self) -> None:
        text = "# Log\n\n2026-01-01 | DEC-007 | first | a\n2026-01-02 | DEC-008 | second | b\n"
        assert set(decision_entries(text)) == {"DEC-007", "DEC-008"}
