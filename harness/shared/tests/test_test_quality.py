"""Meta-tests: the test suite's own quality floor.

A test that cannot fail is worse than a missing test, because it converts an
open question into a false assurance. Nine such tests had accumulated in this
suite and none of them showed up in any gate -- coverage counted their lines
as covered, and the run stayed green.

These checks are structural (AST over the suite's own source) rather than
behavioural, because the property under test is "an assertion exists at all",
which is not observable by running the test.

Scope note: this file deliberately scans only this repository's Python test
directories. It is not a general linter, and it does not try to judge whether
an assertion is *good* -- only that a test has one, or is listed below with a
reason.
"""

from __future__ import annotations

import ast
from pathlib import Path

from harness.shared.tests._helpers import REPO

TEST_ROOTS = (
    REPO / "harness" / "shared" / "tests",
    REPO / "harness" / "api_server" / "tests",
    REPO / "harness" / "control-plane" / "tests",
)

# Names that count as making an assertion. `pytest.fail` is a real assertion
# mechanism; `exit` is deliberately NOT here -- it once was, which meant a test
# whose only "assertion" was `sys.exit(...)` or a reference to `proc.exitstatus`
# counted as asserting and slipped through this very check.
_ASSERTING_ATTRS = ("raises", "warns", "deprecated_call", "fail")

# Tests that legitimately assert nothing, each with the reason it is exempt.
# An entry here is a decision, not a shortcut: it must say why the absence of
# an exception is the whole contract. Empty today -- keep it that way.
ASSERTION_FREE_WAIVERS: dict[str, str] = {}


def _test_modules() -> list[Path]:
    files: list[Path] = []
    for root in TEST_ROOTS:
        if root.is_dir():
            files.extend(sorted(root.rglob("test_*.py")))
    return files


def _is_fixture(node: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    """A fixture may be named ``test_files``; pytest will not collect it."""
    for decorator in node.decorator_list:
        target = decorator.func if isinstance(decorator, ast.Call) else decorator
        name = target.attr if isinstance(target, ast.Attribute) else getattr(target, "id", "")
        if name == "fixture":
            return True
    return False


def _asserts_something(node: ast.AST) -> bool:
    for child in ast.walk(node):
        if isinstance(child, ast.Assert):
            return True
        if isinstance(child, ast.Attribute) and (child.attr.startswith("assert") or child.attr in _ASSERTING_ATTRS):
            return True
        if isinstance(child, ast.Name) and child.id.startswith("assert"):
            return True
    return False


def _collected_tests(path: Path) -> list[tuple[str, ast.FunctionDef | ast.AsyncFunctionDef]]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    found = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if node.name.startswith("test") and not _is_fixture(node):
                found.append((f"{path.relative_to(REPO)}::{node.name}", node))
    return found


class TestSuiteHasNoUnfailableTests:
    def test_test_modules_are_discovered(self) -> None:
        """Guards the scan itself: a glob that stopped matching would make
        every check in this file pass while examining nothing.

        Asserted per-root rather than against a total. A hard-coded floor
        breaks on a legitimate consolidation that reduces the file count while
        discovery still works perfectly -- and a threshold nobody can justify
        is the kind of assertion that gets deleted rather than understood.
        """
        for root in TEST_ROOTS:
            assert root.is_dir(), f"test root {root} does not exist"
            found = list(root.rglob("test_*.py"))
            assert found, f"test root {root} contributed no modules to the scan"

    def test_every_test_asserts_something(self) -> None:
        offenders = [
            name
            for path in _test_modules()
            for name, node in _collected_tests(path)
            if not _asserts_something(node) and name.split("::")[-1] not in ASSERTION_FREE_WAIVERS
        ]
        assert not offenders, (
            "these tests contain no assertion, so they can only fail on an unexpected "
            f"exception: {offenders}. Add an assertion about the outcome, or record the "
            "function name in ASSERTION_FREE_WAIVERS with the reason absence-of-exception "
            "is the whole contract."
        )

    def test_waivers_name_tests_that_exist(self) -> None:
        """A waiver for a test that was renamed or deleted is dead weight that
        would silently re-permit a future test with the same name."""
        known = {name.split("::")[-1] for path in _test_modules() for name, _ in _collected_tests(path)}
        assert not set(ASSERTION_FREE_WAIVERS) - known

    def test_each_waiver_has_a_substantive_reason(self) -> None:
        # A loop, not a parametrize: an empty waiver list is the healthy state,
        # and parametrizing over it skipped (R-TDH-19).
        for waived, reason in sorted(ASSERTION_FREE_WAIVERS.items()):
            assert len(reason.strip()) > 60, waived


class TestSuiteHasNoUnfailableAssertions:
    """``assert <local> is not None`` on a value that cannot be None is the
    other shape of the same problem: it looks like a check and is not one."""

    # Names whose binding provably cannot be None at the assertion point
    # (constructor results, module objects). Kept narrow on purpose -- a
    # regex-wide version would flag legitimate Optional narrowing.
    def test_no_assertion_on_a_freshly_imported_module(self) -> None:
        offenders: list[str] = []
        for path in _test_modules():
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for name, node in _collected_tests(path):
                imported = {
                    alias.asname or alias.name.split(".")[0]
                    for child in ast.walk(node)
                    if isinstance(child, (ast.Import, ast.ImportFrom))
                    for alias in child.names
                }
                for child in ast.walk(node):
                    if not isinstance(child, ast.Assert) or not isinstance(child.test, ast.Compare):
                        continue
                    left = child.test.left
                    if (
                        isinstance(left, ast.Name)
                        and left.id in imported
                        and any(isinstance(op, ast.IsNot) for op in child.test.ops)
                        and any(isinstance(c, ast.Constant) and c.value is None for c in child.test.comparators)
                    ):
                        offenders.append(f"{name} (line {child.lineno})")
            del tree
        assert not offenders, f"assertions on a just-imported module cannot fail: {offenders}"
