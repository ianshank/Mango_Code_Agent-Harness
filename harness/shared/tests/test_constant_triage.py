"""Every operational constant is either a policy value or an accepted decision.

The tech-debt audit found operational limits declared as module literals with
no link to `governance-policy.json` and no decision recording why not. Two
states are allowed and a third is not (tech-debt-hardening-plan R-TDH-16):

* **policy** -- the constant equals a policy value, read through
  `policy_loader` or equality-pinned to it (the adopter-fallback pattern
  `test_policy_consistency.py` already applies).
* **decision** -- the constant is named in one decision-record entry that says
  why it is a true constant (a protocol ceiling, an operator env knob with a
  documented default, a client-local resilience default).
* unlinked -- not allowed. A new constant needs a row here, and a row needs a
  policy key or a `DEC-` id.

The table is the inventory; the test is what stops it rotting.

Every assertion here used to run in one direction only: each *listed* row was
checked for a valid link, and nothing checked that every constant which exists
is listed. So the failure the docstring above warns about -- "a new constant
needs a row here" -- had no enforcement at all: the way to defeat the inventory
was to not write the row, and five live operational defaults had done exactly
that, three of them lock timings on the meta-tool store. That is the same
unbounded-scope shape DEC-032 and DEC-038 found elsewhere: a gate that judges
the set it was handed and never asks whether that set is the set that exists.
`TestTheInventoryIsComplete` closes it by discovering the constants from the
source and requiring each to be triaged or explicitly excluded with a reason.
"""

from __future__ import annotations

import ast
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
DECISIONS_DIR = REPO / "docs" / "decisions"


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
    Row("harness.shared.validate_invariants", "TEST_SIZE_BUDGET_LINES", policy_key="limits.test_size_budget_lines"),
    Row("harness.shared.check_dedup", "DEFAULT_MAX_SHIM_LINES", policy_key="dedup.max_shim_lines"),
    # The adopter fallback for the destination-check timeout duplicated
    # `orchestrator.tool_timeout_sec` with nothing holding the two equal: they
    # agree today at 30 by coincidence, and the only test asserted `> 0`. This
    # is the pattern the docstring calls state (a), applied where it was missing.
    Row(
        "harness.shared.governance.pretooluse_guard",
        "FALLBACK_DESTINATION_CHECK_TIMEOUT_SEC",
        policy_key="orchestrator.tool_timeout_sec",
    ),
    # accepted by decision
    Row("harness.shared.retry_policy", "DEFAULT_BASE_SEC", decision="DEC-025"),
    Row("harness.shared.retry_policy", "DEFAULT_MAX_SEC", decision="DEC-025"),
    Row("harness.shared.retry_policy", "DEFAULT_JITTER_RATIO", decision="DEC-025"),
    Row("harness.shared.shadow_planner", "DEFAULT_SHADOW_TIMEOUT_SEC", decision="DEC-025"),
    Row("harness.shared.cognitive_signal", "MAX_SIGNAL_BYTES", decision="DEC-025"),
    Row("harness.shared.cognitive_signal", "MAX_SINK_BYTES", decision="DEC-025"),
    Row("harness/node/src/ai/nemotron/circuit-breaker.ts", "failureThreshold", decision="DEC-025"),
    Row("harness/node/src/ai/nemotron/nemotron-client.ts", "baseBackoffMs", decision="DEC-025"),
    # DEC-025 accepts five Node resilience constants by name; the inventory
    # registered two. The table is the inventory (see the module docstring), so
    # the other three were unlinked in practice while a reader of the decision
    # would assume otherwise. No decision-log change: DEC-025 already names them.
    Row("harness/node/src/ai/nemotron/circuit-breaker.ts", "resetTimeoutMs", decision="DEC-025"),
    Row("harness/node/src/ai/nemotron/circuit-breaker.ts", "halfOpenSuccessThreshold", decision="DEC-025"),
    Row("harness/node/src/ai/nemotron/nemotron-client.ts", "maxBackoffMs", decision="DEC-025"),
    Row("harness/node/src/ai/nemotron/retry.ts", "JITTER_CEILING_MS", decision="DEC-037"),
    # Found by TestTheInventoryIsComplete below, which is the point of it: every
    # one of these satisfied the old suite by being absent from it (DEC-039).
    Row("harness.shared.meta_tools", "DEFAULT_LOCK_TIMEOUT_S", decision="DEC-039"),
    Row("harness.shared.meta_tools", "DEFAULT_LOCK_POLL_S", decision="DEC-039"),
    Row("harness.shared.meta_tools", "MIN_LOCK_POLL_S", decision="DEC-039"),
    Row("harness.shared.debug_dump", "DUMP_DIR_MODE", decision="DEC-039"),
    Row("harness.shared.debug_dump", "MIN_ENV_CREDENTIAL_LENGTH", decision="DEC-039"),
    Row("harness.shared.tool_dispatch", "DEFAULT_HYPOTHESIS_CONFIDENCE", decision="DEC-039"),
    Row("harness.shared.agent_prompts", "TASK_LOG_PREVIEW_CHARS", decision="DEC-039"),
)


def _module_names(module: str) -> tuple[str, ...]:
    """Identifiers a decision-record body may legitimately use to name ``module``.

    Rows carry two shapes: a dotted Python module
    (``harness.shared.retry_policy``) and a repo-relative Node path
    (``harness/node/src/ai/nemotron/circuit-breaker.ts``).

    The previous derivation was ``Path(module).name.split(".")[0]``, which for a
    *dotted* module has no path separator to split on and so evaluated to
    ``"harness"`` -- a substring of essentially every line in the log. Combined
    with `or`/`and` precedence that left only the symbol actually checked, so a
    constant could cite a decision discussing an entirely different module, or a
    module that does not exist, and the gate stayed green. R-TDH-16/AC-16's whole
    enforcement rested on that line.
    """
    if "/" in module:
        base = module.rsplit("/", 1)[-1]
        return (module, base, base.rsplit(".", 1)[0])
    return (module, module.rsplit(".", 1)[-1])


def _lookup(policy: dict[str, Any], dotted: str) -> Any:
    node: Any = policy
    for part in dotted.split("."):
        assert isinstance(node, dict) and part in node, f"policy has no key {dotted!r}"
        node = node[part]
    return node


def decision_entries(decisions_dir: Path | None = None) -> dict[str, str]:
    """`DEC-nnn` -> record text (frontmatter + body) from docs/decisions."""
    root = decisions_dir if decisions_dir is not None else DECISIONS_DIR
    entries: dict[str, str] = {}
    for path in sorted(root.glob("DEC-*.md")):
        text = path.read_text(encoding="utf-8")
        match = re.search(r"^id:\s*(DEC-\d+)\s*$", text, re.M)
        if match:
            entries[match.group(1)] = text
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
        return f"{row.decision} is not in the decision records"
    if row.symbol not in line or not any(name in line for name in _module_names(row.module)):
        return f"{row.decision} does not name {row.module} / {row.symbol}"
    return None


@pytest.fixture(scope="module")
def policy() -> dict[str, Any]:
    loaded = json.loads(POLICY.read_text(encoding="utf-8"))
    assert isinstance(loaded, dict), "governance-policy.json must be a JSON object"
    return loaded


@pytest.fixture(scope="module")
def decisions() -> dict[str, str]:
    entries = decision_entries()
    assert entries, "docs/decisions parser found no entries; the format changed or the dir moved"
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


@dataclass(frozen=True)
class Excluded:
    """A discovered constant that is deliberately not an operational limit.

    Carries its reason for the same purpose `.gitleaks.toml`'s `# keep:` lines
    do: the exemption is reviewed beside what it exempts, rather than being an
    anonymous name in a set that quietly grows until the gate covers nothing.
    """

    module: str
    symbol: str
    reason: str


#: Not operational limits, so not triage rows. Each is a *fact* about a format,
#: a protocol, or a data structure -- changing one does not tune behaviour, it
#: describes something that is already true, and a governance threshold for it
#: would be a threshold nobody could act on.
EXCLUDED: tuple[Excluded, ...] = (
    Excluded(
        "harness.control_plane.publish_policy_artifact",
        "POLICY_VERSION_HEX_LEN",
        "width of a hex digest field, fixed by the format it parses",
    ),
    Excluded(
        "harness.control_plane.publish_policy_artifact",
        "SHA256_HEX_LEN",
        "SHA-256 is 64 hex characters; a policy could not change that",
    ),
    Excluded(
        "harness.shared.shadow_planner",
        "POLICY_VERSION_HEX_LEN",
        "width of a hex digest field, fixed by the format it parses",
    ),
    Excluded(
        "harness.shared.shadow_planner", "TASK_ID_HEX_LEN", "width of the generated task id, fixed by its own format"
    ),
    Excluded(
        "harness.shared.governance.pretooluse_guard",
        "ALLOW_EXIT",
        "Claude Code hook protocol exit code; the protocol defines it, not this repo",
    ),
    Excluded(
        "harness.shared.governance.pretooluse_guard",
        "BLOCK_EXIT",
        "Claude Code hook protocol exit code; the protocol defines it, not this repo",
    ),
    Excluded(
        "harness.shared.langgraph.graph",
        "EXPECTED_NODE_COUNT",
        "a structural fact about the compiled graph that a test pins; not a limit",
    ),
    Excluded(
        "harness.shared.langgraph.state",
        "CHANNEL_COUNT",
        "a structural fact about the state schema that a test pins; not a limit",
    ),
)

#: First-party roots scanned for module-level constants. `harness/control-plane`
#: is hyphenated and unimportable, so it is scanned by path like the Node rows.
SOURCE_ROOTS = ("harness/shared", "harness/api_server", "harness/control-plane")


def module_constants(root: Path) -> list[tuple[str, str]]:
    """`(dotted-ish module, SYMBOL)` for every module-level numeric UPPER constant under `root`.

    Numeric only, and deliberately so: the shape of an operational limit is a
    number. A `str` constant naming a file or a `re.Pattern` is an identifier,
    not a threshold, and demanding a decision for each would bury the real rows
    under noise until the table stopped being read -- which is how an inventory
    dies of over-collection rather than under-collection.

    Parsed with `ast` rather than imported: importing every module to read its
    constants runs their import side effects inside the gate that judges them.
    """
    found: list[tuple[str, str]] = []
    for path in sorted(root.rglob("*.py")):
        parts = set(path.parts)
        if "tests" in parts or "__pycache__" in parts or path.name.startswith("test_"):
            continue
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except (SyntaxError, OSError):  # pragma: no cover - a broken source fails lint first
            continue
        module = str(path.relative_to(REPO).with_suffix("")).replace("/", ".").replace("-", "_")
        for node in tree.body:
            names: list[str]
            # `AnnAssign.value` is optional (`X: int` declares without assigning),
            # so the union is real rather than a typing formality; the `is None`
            # guard below is what makes the narrowing sound.
            value: ast.expr | None
            if isinstance(node, ast.Assign):
                names, value = [t.id for t in node.targets if isinstance(t, ast.Name)], node.value
            elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
                names, value = [node.target.id], node.value
            else:
                continue
            if value is None:
                continue
            # `-1` and friends parse as UnaryOp(USub, Constant); unwrap so a
            # negative default is discovered like any other number.
            if isinstance(value, ast.UnaryOp) and isinstance(value.operand, ast.Constant):
                value = value.operand
            if not isinstance(value, ast.Constant):
                continue
            if isinstance(value.value, bool) or not isinstance(value.value, (int, float)):
                continue
            found.extend((module, name) for name in names if name.isupper() and not name.startswith("_"))
    return found


def discovered_constants() -> list[tuple[str, str]]:
    """Every candidate across `SOURCE_ROOTS`, deduplicated and ordered."""
    found: list[tuple[str, str]] = []
    for root in SOURCE_ROOTS:
        found.extend(module_constants(REPO / root))
    return sorted(set(found))


class TestTheInventoryIsComplete:
    """The direction the original assertions never checked: does every constant have a row?

    Written after finding that `TRIAGE` -- the table whose own docstring calls
    itself the inventory -- was missing `meta_tools`' three lock timings,
    `tool_dispatch.DEFAULT_HYPOTHESIS_CONFIDENCE`, `debug_dump`'s credential
    floor and directory mode, and `agent_prompts.TASK_LOG_PREVIEW_CHARS`. Every
    one satisfied the old suite by being absent from it.
    """

    def test_every_discovered_constant_is_triaged_or_excluded(self) -> None:
        accounted = {(row.module, row.symbol) for row in TRIAGE if row.is_python}
        accounted |= {(item.module, item.symbol) for item in EXCLUDED}
        unaccounted = [
            f"{module}.{symbol}" for module, symbol in discovered_constants() if (module, symbol) not in accounted
        ]
        assert not unaccounted, (
            "these module-level numeric constants are neither triaged nor excluded: "
            f"{', '.join(unaccounted)}. Add a TRIAGE row citing a policy key or a DEC- id, "
            "or an EXCLUDED entry saying why it is a fact rather than a limit."
        )

    def test_discovery_is_not_vacuous(self) -> None:
        """A discovery that finds nothing would make the check above pass silently."""
        found = discovered_constants()
        assert len(found) >= 20, f"discovery found only {len(found)} constants; the parser is broken"
        assert ("harness.shared.retry_policy", "DEFAULT_BASE_SEC") in found
        assert ("harness.shared.validate_invariants", "SIZE_BUDGET_LINES") in found

    def test_discovery_ignores_non_numeric_and_private_names(self) -> None:
        found = discovered_constants()
        assert ("harness.shared.governance.check_secret_allowlist", "CONFIG_NAME") not in found
        assert not [name for _, name in found if name.startswith("_")]

    def test_every_exclusion_states_a_reason(self) -> None:
        for item in EXCLUDED:
            assert item.reason.strip(), f"{item.module}.{item.symbol} is excluded with no reason"

    def test_exclusions_do_not_outnumber_the_triaged_rows(self) -> None:
        """An exclusion list larger than the inventory means the gate covers nothing."""
        assert len(EXCLUDED) < len([row for row in TRIAGE if row.is_python])

    def test_every_excluded_symbol_still_exists(self) -> None:
        """A stale exclusion is a standing permission for a future constant of that name."""
        discovered = set(discovered_constants())
        for item in EXCLUDED:
            assert (item.module, item.symbol) in discovered, (
                f"{item.module}.{item.symbol} is excluded but no longer discovered; remove the entry"
            )


class TestCheckerSemantics:
    """Negative cases: the checker must fail on each way a row can be wrong."""

    def test_unlinked_row_is_rejected(self, policy: dict[str, Any], decisions: dict[str, str]) -> None:
        assert check_row(Row("harness.shared.retry_policy", "DEFAULT_BASE_SEC"), policy, decisions)

    def test_missing_decision_is_rejected(self, policy: dict[str, Any]) -> None:
        reason = check_row(Row("harness.shared.retry_policy", "DEFAULT_BASE_SEC", decision="DEC-999"), policy, {})
        assert reason and "not in the decision records" in reason

    def test_decision_that_does_not_name_the_constant_is_rejected(self, policy: dict[str, Any]) -> None:
        fake = {"DEC-1": "2026-01-01 | DEC-1 | something unrelated | owner"}
        reason = check_row(Row("harness.shared.retry_policy", "DEFAULT_BASE_SEC", decision="DEC-1"), policy, fake)
        assert reason and "does not name" in reason

    def test_policy_mismatch_is_rejected(self, decisions: dict[str, str]) -> None:
        drifted = {"nemotron": {"max_retries": 42}}
        row = Row("harness.shared.retry_policy", "DEFAULT_MAX_RETRIES", policy_key="nemotron.max_retries")
        reason = check_row(row, drifted, decisions)
        assert reason and "but policy" in reason

    def test_parser_reads_decision_records(self, tmp_path: Path) -> None:
        for dec_id, body in (("DEC-007", "first"), ("DEC-008", "second")):
            (tmp_path / f"{dec_id}.md").write_text(
                f"---\nid: {dec_id}\nstatus: accepted\ndate: 2026-01-01\n"
                f"supersedes: []\nowners: [a]\n---\n\n## Context\n\nx\n\n"
                f"## Decision\n\n{body}\n\n## Consequences\n\ny\n",
                encoding="utf-8",
            )
        assert set(decision_entries(tmp_path)) == {"DEC-007", "DEC-008"}


class TestDecisionLinkageIsNotVacuous:
    """The linkage check reduced to matching the string ``harness``.

    ``Path("harness.shared.retry_policy").name.split(".")[0]`` is ``"harness"``
    — a dotted module has no path separator to split on — and that appears in
    essentially every decision-record body. With `or`/`and` precedence only the
    symbol was ever really checked, so a constant could cite a decision about a
    different module, or a module that does not exist, and stay green. AC-16's
    entire enforcement rested on that expression.
    """

    def test_a_decision_naming_a_different_module_is_rejected(self) -> None:
        decisions = {"DEC-999": "2026-01-01 | DEC-999 | harness thing about DEFAULT_BASE_SEC elsewhere | owner"}
        row = Row("harness.shared.cognitive_signal", "DEFAULT_BASE_SEC", decision="DEC-999")
        assert check_row(row, {}, decisions) is not None, "a decision about another module must not satisfy the row"

    def test_a_decision_naming_the_real_module_is_accepted(self) -> None:
        decisions = {"DEC-999": "2026-01-01 | DEC-999 | retry_policy.DEFAULT_BASE_SEC is accepted because | owner"}
        row = Row("harness.shared.retry_policy", "DEFAULT_BASE_SEC", decision="DEC-999")
        assert check_row(row, {}, decisions) is None

    def test_a_node_path_row_matches_on_its_basename(self) -> None:
        decisions = {"DEC-999": "2026-01-01 | DEC-999 | circuit-breaker.ts failureThreshold accepted | owner"}
        row = Row("harness/node/src/ai/nemotron/circuit-breaker.ts", "failureThreshold", decision="DEC-999")
        assert check_row(row, {}, decisions) is None
