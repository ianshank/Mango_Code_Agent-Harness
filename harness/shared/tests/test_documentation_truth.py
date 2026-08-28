"""Documentation that names a path must name one that exists.

The README's "Repository Layout" tree is the first thing a reader trusts, and
it had been describing a directory that does not exist -- `.agents/skills/`,
left behind when that registry was consolidated into `.mango/skills/`. Nothing
noticed, because prose has no gate.

The rule is narrow on purpose: only the fenced tree block is parsed, and only
entries that look like real repository paths. A README is allowed to discuss
things that are not files; it is not allowed to draw a map with roads that were
removed.
"""

from __future__ import annotations

import re

import pytest

from harness.shared.tests._helpers import REPO

README = REPO / "README.md"
GITIGNORE = REPO / ".gitignore"

pytestmark = pytest.mark.governance


def _tree_entries() -> list[str]:
    """Repository paths drawn in the README's layout tree.

    Only depth-0 entries are returned, and deliberately so. A nested line such
    as ``hooks/session-start.sh`` under ``.claude/`` is written relative to its
    *parent*, not to the repository root, so it cannot be resolved without
    reconstructing the indentation grammar -- a parser that would itself need
    tests to be trustworthy. Depth 0 is where a whole removed directory shows
    up, which is the rot this exists to catch (``.agents/`` was exactly that).

    Nested entries are not unchecked, they are checked differently:
    ``test_every_skill_directory_is_listed`` compares the skill names in the
    tree against the filesystem, which is the one nested section that changes
    often enough to rot.
    """
    text = README.read_text(encoding="utf-8")
    match = re.search(r"```text\n(.*?)```", text, re.S)
    if not match:
        return []
    entries = []
    for line in match.group(1).splitlines():
        # Depth 0 entries begin the line with the branch glyph.
        depth0 = re.match(r"^[├└]── ([A-Za-z0-9_.][A-Za-z0-9_./-]*)", line)
        if depth0:
            entries.append(depth0.group(1).rstrip("/"))
    return entries


class TestReadmeLayoutIsReal:
    def test_the_tree_block_is_found(self) -> None:
        """Guards the parse: if the fence moved, every check below would pass
        while reading nothing."""
        assert len(_tree_entries()) >= 3, "could not parse the README layout tree"

    @pytest.mark.parametrize("entry", _tree_entries())
    def test_top_level_entry_exists(self, entry: str) -> None:
        assert (REPO / entry).exists(), (
            f"README's layout tree draws {entry!r}, which does not exist. The tree is the "
            "first thing a reader trusts; a removed directory left in it sends people "
            "looking for something that was deleted."
        )

    def test_every_skill_directory_is_listed(self) -> None:
        """The tree enumerates the skills by name. A skill added without a
        README line is invisible to anyone reading the map."""
        text = README.read_text(encoding="utf-8")
        skills = sorted(p.name for p in (REPO / ".mango" / "skills").iterdir() if p.is_dir())
        missing = [name for name in skills if f"{name}/" not in text]
        assert not missing, f"skills exist but are not in the README layout: {missing}"

    def test_the_stated_skill_count_matches_reality(self) -> None:
        text = README.read_text(encoding="utf-8")
        actual = len([p for p in (REPO / ".mango" / "skills").iterdir() if p.is_dir()])
        match = re.search(r"(\d+) reusable skills", text)
        assert match, "README no longer states a skill count"
        assert int(match.group(1)) == actual, (
            f"README says {match.group(1)} skills; there are {actual}"
        )


class TestGitignoreHasNoDeadRules:
    """An ignore rule for a deleted subsystem is harmless until someone
    recreates that path for an unrelated reason and cannot work out why their
    file will not stage."""

    # Patterns whose target genuinely need not exist: build outputs, caches and
    # runtime artifacts are ignored precisely so they never appear in a clean tree.
    TRANSIENT = re.compile(
        r"(dist|build|coverage|node_modules|__pycache__|\.pytest_cache|\.mypy_cache|"
        r"\.ruff_cache|htmlcov|\.benchmarks|egg-info|\.gradle|\.venv|\.hypothesis|"
        r"\.env|\.coverage|scratch|test-|memory|\.state|FAILURE_MEMORY|vitest-results|"
        r"\.governance|coverage\.json)"
    )

    def test_no_ignore_rule_names_a_deleted_subsystem(self) -> None:
        """`harness/node/src/pong/web/dist/` and `*.pongrec` outlived the Pong
        demo's removal by two PRs."""
        offenders = []
        for line in GITIGNORE.read_text(encoding="utf-8").splitlines():
            rule = line.strip()
            if not rule or rule.startswith(("#", "*")) or "*" in rule:
                continue
            if self.TRANSIENT.search(rule):
                continue
            # A concrete directory path with no glob: its parent should exist,
            # or the rule is describing a tree that is gone.
            parent = (REPO / rule.rstrip("/")).parent
            if not parent.exists():
                offenders.append(rule)
        assert not offenders, (
            f".gitignore rules whose parent directory does not exist: {offenders}. "
            "Remove them, or they quietly ignore whatever is created there later."
        )
