"""Verdict and broker statuses are named once, in ``governance/verdict.py``.

Fourteen call sites across six modules restated ``"BLOCKED"``, ``"FAILED"``,
``"VERIFIED"`` and ``"SUCCESS"`` as raw strings while the constants module
existed beside them (tech-debt-hardening-plan R-TDH-14). A restated status is
how a typo (``"BLOCKD"``) becomes a status nothing models, which ``verdict.py``
would then, correctly, refuse to treat as a pass -- a silent conversion of a
denial into a harness fault.

The scan is an AST walk, not a grep: comments and docstrings are free to name
the statuses, ``typing.Literal[...]`` annotations are allowed to enumerate them,
and only a string constant used as a *value* counts.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from harness.shared.governance import verdict
from harness.shared.tests._helpers import REPO

pytestmark = pytest.mark.governance

STATUS_LITERALS = frozenset({verdict.VERIFIED, verdict.FAILED, verdict.BLOCKED, verdict.BROKER_SUCCESS})
SOURCE_ROOTS = (REPO / "harness" / "shared", REPO / "harness" / "api_server", REPO / "harness" / "control-plane")
VOCABULARY_MODULE = REPO / "harness" / "shared" / "governance" / "verdict.py"


def _first_party_modules() -> list[Path]:
    files: list[Path] = []
    for root in SOURCE_ROOTS:
        for path in sorted(root.rglob("*.py")):
            if "tests" in path.parts or path == VOCABULARY_MODULE:
                continue
            files.append(path)
    return files


def _literal_subscript_nodes(tree: ast.AST) -> set[int]:
    """ids of every node inside a ``Literal[...]`` subscript, which may enumerate statuses."""
    inside: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Subscript):
            base = node.value
            name = base.attr if isinstance(base, ast.Attribute) else getattr(base, "id", "")
            if name == "Literal":
                inside.update(id(child) for child in ast.walk(node.slice))
    return inside


def _is_docstring(parent: ast.AST, node: ast.AST) -> bool:
    body: list[ast.stmt] | None = getattr(parent, "body", None)
    if not body:
        return False
    return body[0] is node


def status_literals_in(source: str) -> list[tuple[int, str]]:
    """(line, literal) for every status string used as a value in ``source``."""
    tree = ast.parse(source)
    exempt = _literal_subscript_nodes(tree)
    hits: list[tuple[int, str]] = []
    for parent in ast.walk(tree):
        for child in ast.iter_child_nodes(parent):
            if isinstance(child, ast.Expr) and isinstance(child.value, ast.Constant) and _is_docstring(parent, child):
                continue  # module/class/function docstring
            for node in ast.walk(child):
                if (
                    isinstance(node, ast.Constant)
                    and isinstance(node.value, str)
                    and node.value in STATUS_LITERALS
                    and id(node) not in exempt
                ):
                    hits.append((node.lineno, node.value))
    # ast.walk from every parent re-visits nested nodes; de-duplicate by position.
    return sorted(set(hits))


class TestStatusesAreNamedOnce:
    def test_the_vocabulary_module_defines_the_strings(self) -> None:
        assert verdict.BROKER_SUCCESS == "SUCCESS"
        assert verdict.BROKER_FAILED == verdict.FAILED == "FAILED"
        assert verdict.BROKER_BLOCKED == verdict.BLOCKED == "BLOCKED"

    @pytest.mark.parametrize("path", _first_party_modules(), ids=lambda p: str(p.relative_to(REPO)))
    def test_no_first_party_module_restates_a_status(self, path: Path) -> None:
        hits = status_literals_in(path.read_text(encoding="utf-8"))
        assert not hits, (
            f"{path.relative_to(REPO)} restates verdict/broker statuses as raw strings at {hits}; "
            "import them from harness.shared.governance.verdict instead"
        )

    def test_the_scan_is_not_vacuous(self) -> None:
        assert len(_first_party_modules()) > 20


class TestScannerSemantics:
    def test_a_value_literal_is_reported(self) -> None:
        assert status_literals_in('status = "BLOCKED"\n') == [(1, "BLOCKED")]

    def test_a_literal_annotation_is_exempt(self) -> None:
        src = 'from typing import Literal\nStatus = Literal["SUCCESS", "FAILED", "BLOCKED"]\n'
        assert status_literals_in(src) == []

    def test_docstrings_and_comments_are_exempt(self) -> None:
        src = '"""Returns SUCCESS or FAILED."""\n\n\ndef f():\n    """May be BLOCKED."""\n    return 1  # "VERIFIED"\n'
        assert status_literals_in(src) == []

    def test_a_negative_module_fails_the_gate(self, tmp_path: Path) -> None:
        """The negative case: a module that restates a status is caught."""
        bad = tmp_path / "bad.py"
        bad.write_text('def f(result):\n    return result.status == "BLOCKED"\n', encoding="utf-8")
        assert status_literals_in(bad.read_text(encoding="utf-8")) == [(2, "BLOCKED")]
