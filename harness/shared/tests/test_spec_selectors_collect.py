"""A ticked acceptance criterion must name a pytest selector that collects something.

Found by hand during the 2026 standards audit (`docs/reports/2026-STANDARDS-AUDIT.md`,
revision record): three ticked criteria in the program plan cited ``-k`` selectors
that collected **zero tests** -- the tests existed under other names, so the boxes
were ticked on commands that could not fail. A criterion that cannot fail is worse
than one that is merely wrong (that spec's own AC-10 says so), and nothing
mechanical caught it because ``make specs`` judges the *shape* of a plan, never
whether its commands reach a test.

This module closes that gap statically. For every ``- [x] AC-*`` bullet under
``## Acceptance criteria`` in ``docs/specs/*.md``, every backticked ``pytest ...``
span is parsed, its paths resolved, its ``-k`` expression evaluated with pytest's
own expression grammar against the test names the named files declare, and the
match count asserted to be at least one. Unticked criteria are not judged: their
tests may legitimately not exist yet.

Static rather than ``--collect-only`` per selector because the suite has ~80
ticked selectors and a subprocess collection each is minutes of wall-clock for a
gate that runs on every PR. The approximation is pytest's documented ``-k``
semantics: a case-insensitive substring match of each identifier against the
item's function, class and module names.
"""

from __future__ import annotations

import ast
import re
import shlex
from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from pathlib import Path

import pytest
from _pytest.mark.expression import Expression

from harness.shared.plan_rules import split_bullets, split_sections

pytestmark = pytest.mark.governance

REPO = Path(__file__).resolve().parents[3]
SPEC_DIR = REPO / "docs" / "specs"
TEMPLATE_NAME = "SPEC_TEMPLATE.md"

TICKED = re.compile(r"^\s*[-*]\s*\[x\]\s*(AC-[A-Za-z0-9_-]+)", re.IGNORECASE)
CODE_SPAN = re.compile(r"`([^`]+)`")
PYTEST_PREFIX = re.compile(r"^(?:python(?:3)?\s+-m\s+)?pytest\b")


@dataclass(frozen=True)
class Selector:
    """One ``pytest`` invocation cited by a ticked criterion."""

    spec: str
    criterion: str
    command: str
    paths: tuple[str, ...]
    node_ids: tuple[str, ...]
    keyword: str | None


@dataclass(frozen=True)
class Item:
    """A statically discovered test function and the names ``-k`` can see."""

    path: Path
    class_name: str
    func_name: str

    @property
    def keywords(self) -> tuple[str, ...]:
        return (self.func_name, self.class_name, self.path.name, self.path.stem)


def _pytest_spans(bullet: str) -> Iterator[str]:
    for span in CODE_SPAN.findall(bullet):
        if PYTEST_PREFIX.search(span.strip()):
            yield span.strip()


def _parse(command: str, spec: str, criterion: str) -> Selector | None:
    """Split a command into paths, node ids and the ``-k`` expression.

    Returns ``None`` for shapes this module does not judge (a bare marker run, a
    command with shell operators it cannot follow). Silence there is deliberate:
    the test asserts vacuity of ``-k`` selectors, not every pytest shape.
    """
    try:
        tokens = shlex.split(command)
    except ValueError:
        return None
    # Drop the interpreter / module prefix so the loop below sees only arguments.
    while tokens and tokens[0] in ("python", "python3", "-m", "pytest"):
        tokens.pop(0)
    paths: list[str] = []
    node_ids: list[str] = []
    keyword: str | None = None
    i = 0
    while i < len(tokens):
        tok = tokens[i]
        if tok == "-k":
            i += 1
            keyword = tokens[i] if i < len(tokens) else None
        elif tok.startswith("-k"):
            keyword = tok[2:]
        elif tok in ("-m", "-p", "-W", "--cov", "--cov-report", "--randomly-seed", "-n"):
            i += 1  # value-taking options this module does not judge
        elif tok.startswith("-"):
            pass
        elif "::" in tok:
            node_ids.append(tok)
        elif any(op in tok for op in ("|", "&&", ";", ">")):
            return None
        else:
            paths.append(tok)
        i += 1
    if keyword is None and not node_ids:
        return None
    return Selector(spec, criterion, command, tuple(paths), tuple(node_ids), keyword)


def ticked_selectors(spec_dir: Path = SPEC_DIR) -> list[Selector]:
    """Every judged selector cited by a ticked criterion across the spec tree."""
    out: list[Selector] = []
    for spec in sorted(spec_dir.rglob("*.md")):
        if spec.name == TEMPLATE_NAME:
            continue
        sections = split_sections(spec.read_text(encoding="utf-8"))
        block = next((body for key, body in sections.items() if key.startswith("acceptance")), "")
        for bullet in split_bullets(block):
            ticked = TICKED.match(bullet)
            if not ticked:
                continue
            for command in _pytest_spans(bullet):
                parsed = _parse(command, spec.name, ticked.group(1))
                if parsed is not None:
                    out.append(parsed)
    return out


def _test_files(paths: Iterable[str]) -> list[Path]:
    files: list[Path] = []
    default_roots = ("harness/shared/tests", "harness/api_server/tests", "harness/control-plane/tests")
    roots = [REPO / p for p in (tuple(paths) or default_roots)]
    for root in roots:
        if root.is_file():
            files.append(root)
        elif root.is_dir():
            files.extend(sorted(root.rglob("test_*.py")))
    return files


def discover_items(paths: Iterable[str]) -> list[Item]:
    """Test functions declared in the named files, with class context."""
    items: list[Item] = []
    for path in _test_files(paths):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in tree.body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name.startswith("test"):
                items.append(Item(path, "", node.name))
            elif isinstance(node, ast.ClassDef) and node.name.startswith("Test"):
                for member in node.body:
                    if isinstance(member, (ast.FunctionDef, ast.AsyncFunctionDef)) and member.name.startswith("test"):
                        items.append(Item(path, node.name, member.name))
    return items


class _KeywordMatcher:
    """pytest's ``KeywordMatcher`` semantics: case-insensitive substring over the item's names."""

    def __init__(self, names: Iterable[str]) -> None:
        self._names = [name.lower() for name in names if name]

    def __call__(self, name: str, /, **kwargs: object) -> bool:
        return any(name.lower() in candidate for candidate in self._names)


def matches(selector: Selector) -> int:
    """How many statically discovered items the selector would collect."""
    items = discover_items(selector.paths)
    if selector.node_ids:
        # Full identity -- repo-relative path, class, function -- so
        # `test_x.py::NoSuchClass::test_existing` cannot be certified by an
        # unrelated class that happens to declare `test_existing`, and
        # `other/test_x.py` cannot stand in for `here/test_x.py`.
        wanted: set[tuple[str, str, str | None]] = set()
        for node_id in selector.node_ids:
            parts = node_id.split("::")
            rel = (REPO / parts[0]).resolve().relative_to(REPO).as_posix()
            if len(parts) == 1:
                wanted.add((rel, "", None))
            elif len(parts) == 2:
                wanted.add((rel, "", parts[1]))  # function, or a class selecting all its tests
            else:
                wanted.add((rel, parts[1], parts[2]))

        def _selected(it: Item) -> bool:
            rel = it.path.relative_to(REPO).as_posix()
            return (
                (rel, "", None) in wanted
                or (rel, "", it.func_name) in wanted
                and it.class_name == ""
                or (rel, "", it.class_name) in wanted
                or (rel, it.class_name, it.func_name) in wanted
            )

        items = [it for it in items if _selected(it)]
    if selector.keyword is None:
        return len(items)
    expression = Expression.compile(selector.keyword)
    return sum(1 for item in items if expression.evaluate(_KeywordMatcher(item.keywords)))


class TestTickedCriteriaCollectSomething:
    def test_the_corpus_has_judged_selectors(self) -> None:
        # The gate would pass vacuously on a corpus it could not parse; pin that
        # it sees the selectors the audit found and corrected.
        specs = {sel.spec for sel in ticked_selectors()}
        assert "code-quality-tech-debt-plan.md" in specs

    @pytest.mark.parametrize("selector", ticked_selectors(), ids=lambda s: f"{s.spec}:{s.criterion}:{s.command[:40]}")
    def test_every_ticked_selector_collects_at_least_one_test(self, selector: Selector) -> None:
        assert matches(selector) >= 1, (
            f"{selector.spec} {selector.criterion} is ticked on `{selector.command}`, which "
            "collects no test: the box carries no evidence. Correct the selector to the "
            "test that proves the claim, or untick it."
        )


EXECUTORS = "harness/shared/tests/test_tool_executors.py"
ACTIONS = "harness/shared/tests/test_command_actions.py"
FUNC = "test_patching_a_credential_file_is_refused"


def _selector(paths: tuple[str, ...] = (), node_ids: tuple[str, ...] = (), keyword: str | None = None) -> Selector:
    return Selector("x.md", "AC-1", "", paths, node_ids, keyword)


class TestTheMatcherItself:
    """The gate must be able to fail; these pin the grammar it relies on."""

    def test_a_dead_keyword_reports_zero(self) -> None:
        sel = _selector(paths=(EXECUTORS,), keyword="patch_denied_read")
        assert matches(sel) == 0

    def test_a_live_keyword_reports_the_match(self) -> None:
        sel = _selector(paths=(EXECUTORS,), keyword="credential_file_is_refused")
        assert matches(sel) >= 1

    def test_expressions_use_pytest_grammar(self) -> None:
        sel = _selector(paths=(ACTIONS,), keyword="glob or process_substitution")
        assert matches(sel) >= 1
        sel_and = _selector(paths=(ACTIONS,), keyword="glob and no_such_name_anywhere")
        assert matches(sel_and) == 0

    def test_node_ids_are_resolved(self) -> None:
        sel = _selector(node_ids=(f"{EXECUTORS}::TestApplyPatchConsultsTheReadPolicy::{FUNC}",))
        assert matches(sel) == 1
        whole_class = _selector(node_ids=(f"{EXECUTORS}::TestApplyPatchConsultsTheReadPolicy",))
        assert matches(whole_class) >= 1
        # A function inside a class is not reachable as `file::function`; pytest
        # would collect nothing for that id, so neither does the matcher.
        unqualified = _selector(node_ids=(f"{EXECUTORS}::{FUNC}",))
        assert matches(unqualified) == 0
        missing = _selector(node_ids=(f"{EXECUTORS}::test_no_such_function",))
        assert matches(missing) == 0

    def test_node_ids_need_the_whole_identity(self) -> None:
        """A wrong class or a wrong directory must not be certified by a
        same-named function elsewhere (Copilot review on PR #86)."""
        wrong_class = _selector(node_ids=(f"{EXECUTORS}::NoSuchClass::{FUNC}",))
        assert matches(wrong_class) == 0
        elsewhere = "harness/api_server/tests/test_tool_executors.py"
        wrong_dir = _selector(node_ids=(f"{elsewhere}::TestApplyPatchConsultsTheReadPolicy::{FUNC}",))
        assert matches(wrong_dir) == 0

    def test_unjudged_shapes_are_skipped_not_passed(self) -> None:
        assert _parse("pytest -m governance", "x.md", "AC-1") is None
        assert _parse("pytest harness/shared/tests | tee log", "x.md", "AC-1") is None
        parsed = _parse('python -m pytest harness/shared/tests -k "a or b"', "x.md", "AC-1")
        assert parsed is not None and parsed.keyword == "a or b" and parsed.paths == ("harness/shared/tests",)

    def test_only_ticked_bullets_are_collected(self, tmp_path: Path) -> None:
        spec = tmp_path / "s.md"
        spec.write_text(
            "## Acceptance criteria\n\n"
            "- [ ] AC-1: `pytest harness/shared/tests -k nothing_here` future\n"
            "- [x] AC-2: `pytest harness/shared/tests -k credential` done\n",
            encoding="utf-8",
        )
        found = ticked_selectors(tmp_path)
        assert [s.criterion for s in found] == ["AC-2"]
