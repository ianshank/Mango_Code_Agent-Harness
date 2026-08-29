"""An invariant whose enforcement mechanism has no caller enforces nothing.

``harness/CONTRACT.md`` warns about this shape for path patterns: *"a pattern
written for a repository layout that does not exist matches nothing and protects
nothing -- silently."* ``test_protected_path_liveness.py`` turned that insight
into a gate. The same failure exists one layer up and had no gate at all:
``INV-8`` required generated code to execute through an approved execution
broker, and ``ExecutionBroker`` had **zero production callers** while
``execute_command`` ended at ``FAILED: Execution engine not fully implemented``.
The invariant was published as an unqualified MUST and enforced by nothing.

This gate asserts on **resolved imports**, parsed from the AST rather than
grepped: a text scan is satisfied by the symbol appearing in a comment, which is
precisely the false assurance being guarded against.

Spec: ``docs/specs/agent-containment.md`` (C-AC-3).
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

from harness.shared.tests._helpers import CONTROL_PLANE, HARNESS, REPO, SHARED

pytestmark = pytest.mark.governance

CONTRACT = HARNESS / "CONTRACT.md"

#: Invariant -> (module that defines the mechanism, symbol that must be reached).
#: Only invariants whose enforcement is a concrete Python symbol appear here.
#: Claiming to check one that is enforced elsewhere -- INV-2 is a Vitest/JUnit
#: gate, INV-4 is a shell installer -- would be the same false assurance in a
#: different place.
INVARIANT_MECHANISMS = {
    "INV-8": ("harness.shared.governance.broker", "ExecutionBroker"),
    "INV-9": ("harness.shared.governance.broker", "ExecutionBroker"),
    "INV-16": ("harness.shared.cognitive_signal", "CognitiveSignalSink"),
}

#: Invariants whose mechanism is knowingly unreached, each with a reason.
#:
#: **Empty, and it should stay that way.** A waiver here says an invariant this
#: repository publishes as a MUST is not enforced, which is exactly the gap the
#: gate exists to surface. It is not the place to record that enforcement is
#: coming: an entry added alongside its own fix can never fire, and an entry
#: added without one outlives the intent that justified it.
DORMANT_INVARIANTS: dict[str, str] = {}


def _first_party_modules() -> list[Path]:
    """Non-test first-party Python, i.e. the code that can hold a live caller."""
    found: list[Path] = []
    for root in (SHARED, CONTROL_PLANE, HARNESS / "api_server"):
        for path in root.rglob("*.py"):
            if "tests" in path.parts or path.name.startswith("test_"):
                continue
            found.append(path)
    return found


def _imports(path: Path) -> set[tuple[str, str]]:
    """(module, name) pairs a file imports. AST, not text: a symbol named in a
    comment or a docstring is not a caller."""
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except SyntaxError:  # pragma: no cover - the compat gate would have failed first
        return set()

    package = ".".join(path.relative_to(REPO).with_suffix("").parts)
    pairs: set[tuple[str, str]] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            module = node.module or ""
            if node.level:  # relative import: resolve against this file's package
                parent = package.rsplit(".", node.level)[0]
                module = f"{parent}.{module}" if module else parent
            for alias in node.names:
                pairs.add((module, alias.name))
        elif isinstance(node, ast.Import):
            for alias in node.names:
                pairs.add((alias.name, ""))
    return pairs


def _live_callers(module: str, symbol: str) -> list[str]:
    """Modules that import ``symbol``, excluding the one that defines it and its
    own package re-exports -- a package `__init__` that re-exports a symbol is not
    a caller, it is the same layer."""
    defining = module.replace(".", "/")
    callers = []
    for path in _first_party_modules():
        rel = str(path.relative_to(REPO).with_suffix(""))
        if rel == defining or rel.endswith("/__init__"):
            continue
        if (module, symbol) in _imports(path):
            callers.append(rel)
    return callers


def _declared_invariants() -> set[str]:
    return set(re.findall(r"\*\*(INV-\d+):\*\*", CONTRACT.read_text(encoding="utf-8")))


class TestTheScanWorks:
    """Positive controls. Without these, a CONTRACT.md reformat or a moved
    directory would make every assertion below vacuously true."""

    def test_the_contract_declares_invariants(self) -> None:
        assert len(_declared_invariants()) >= 16

    def test_the_module_scan_finds_first_party_code(self) -> None:
        assert len(_first_party_modules()) >= 30

    def test_the_import_parser_resolves_a_known_import(self) -> None:
        pairs = _imports(SHARED / "mango_mas_orchestrator.py")
        assert ("harness.shared.governance.broker", "ExecutionBroker") in pairs


class TestEveryDeclaredMechanismIsReached:
    @pytest.mark.parametrize(("invariant", "target"), sorted(INVARIANT_MECHANISMS.items()))
    def test_mechanism_has_a_live_caller(self, invariant: str, target: tuple[str, str]) -> None:
        module, symbol = target
        if invariant in DORMANT_INVARIANTS:
            pytest.skip(f"{invariant} is declared dormant")  # pragma: no cover - dict is empty
        callers = _live_callers(module, symbol)
        assert callers, (
            f"{invariant} names {module}.{symbol} as its enforcement mechanism, and no non-test module "
            f"imports it. An invariant whose mechanism has no caller enforces nothing."
        )

    def test_every_named_invariant_is_one_the_contract_declares(self) -> None:
        unknown = set(INVARIANT_MECHANISMS) - _declared_invariants()
        assert not unknown, f"{unknown} are not declared in harness/CONTRACT.md"


class TestWaiversStayHonest:
    def test_no_invariant_is_currently_waived(self) -> None:
        """The gate ships with an empty waiver dict, and a waiver added later has
        to argue for itself against this assertion."""
        assert DORMANT_INVARIANTS == {}, (
            f"{sorted(DORMANT_INVARIANTS)} are waived. An invariant this repository publishes as a MUST "
            "is not enforced; either enforce it or amend the contract to stop claiming it."
        )

    def test_a_waiver_would_have_to_name_a_real_invariant(self) -> None:
        assert set(DORMANT_INVARIANTS) <= _declared_invariants()

    def test_a_waiver_would_have_to_carry_a_substantive_reason(self) -> None:
        for invariant, reason in DORMANT_INVARIANTS.items():
            assert len(reason.strip()) > 80, f"{invariant} is waived without a substantive reason"

    def test_a_waived_invariant_may_not_also_be_claimed_enforced(self) -> None:
        """Without this, a waiver leaves ``CONTRACT.md`` asserting enforcement to
        every reader while the gate quietly records that there is none."""
        text = CONTRACT.read_text(encoding="utf-8")
        for invariant in DORMANT_INVARIANTS:
            marker = re.search(rf"\*\*{invariant}:\*\*[^\n]*", text)
            assert marker and "not yet enforced" in marker.group(0).lower(), (
                f"{invariant} is waived here but published as an unqualified requirement in CONTRACT.md"
            )
