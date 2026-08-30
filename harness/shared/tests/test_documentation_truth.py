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
ENV_EXAMPLE = REPO / ".env.example"

pytestmark = pytest.mark.governance


def _tree_block() -> str:
    """The fenced layout tree, or "" if the fence is gone."""
    match = re.search(r"```text\n(.*?)```", README.read_text(encoding="utf-8"), re.S)
    return match.group(1) if match else ""


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
        # Scoped to the tree, not the whole README. Searching the whole file
        # gives false passes: `evidence-signing` is named both in the tree and
        # in the prose below it, so deleting its tree line would still match.
        tree = _tree_block()
        assert tree, "could not locate the README layout tree"
        skills = sorted(p.name for p in (REPO / ".mango" / "skills").iterdir() if p.is_dir())
        missing = [name for name in skills if f"{name}/" not in tree]
        assert not missing, f"skills exist but are not in the README layout tree: {missing}"

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


class TestDockerignoreHasNoDeadRules:
    """The same defect, in the file the class above does not read.

    `.dockerignore` carried `.agents/` long after that directory was
    consolidated into `.mango/skills/` (R-HYG-4). It survived two things: the
    gate above reads `.gitignore` only, and its predicate is *the parent
    exists* -- which `.agents/` satisfies, because its parent is the repository
    root. Pointing that gate at this file would not have caught it.

    This one checks the rule's own path. That is affordable here and not in
    `.gitignore`, where most rules name build outputs absent from a clean tree
    by design; a `.dockerignore` is a much shorter list of things that really
    are in the tree, so the transient set below stays small enough to read.

    A stale exclusion is not inert. It pre-exempts whatever is created at that
    path later, and here the consequence is that the path never reaches the
    image -- discovered at runtime, in a container, by an import that fails.
    """

    DOCKERIGNORE = REPO / ".dockerignore"

    #: Paths absent from a clean checkout by design: build output, caches,
    #: local-only artifacts, and secrets that must never be committed at all.
    #: Excluding them is the point, so their absence proves nothing.
    TRANSIENT = re.compile(
        r"(dist|build|coverage|node_modules|__pycache__|\.pytest_cache|\.mypy_cache|"
        r"\.ruff_cache|htmlcov|\.benchmarks|egg-info|\.gradle|\.venv|\.hypothesis|"
        r"\.env|\.coverage|scratch|test-|\.state|vitest-results|\.governance|"
        r"\.git/|\.DS_Store|Thumbs\.db)"
    )

    def _concrete_rules(self) -> list[str]:
        rules = []
        for line in self.DOCKERIGNORE.read_text(encoding="utf-8").splitlines():
            rule = line.strip()
            if not rule or rule.startswith(("#", "!", "*")) or "*" in rule:
                continue
            if self.TRANSIENT.search(rule):
                continue
            rules.append(rule)
        return rules

    def test_the_scan_finds_rules(self) -> None:
        """Positive control: with an empty parse every assertion below passes
        while checking no rule at all."""
        assert self._concrete_rules(), (
            "parsed no concrete rules out of .dockerignore; this parser needs "
            "updating before its verdict means anything"
        )

    def test_every_concrete_rule_excludes_something_that_exists(self) -> None:
        offenders = [
            rule for rule in self._concrete_rules() if not (REPO / rule.rstrip("/")).exists()
        ]
        assert not offenders, (
            f".dockerignore excludes paths that do not exist: {offenders}. Remove them. "
            "A rule for a path nobody has created yet is not harmless: it exempts whatever "
            "is put there later, and the first symptom is a container that cannot import it."
        )


def _documented_models() -> set[str]:
    """Every backticked provider/model identifier the README names.

    Scoped to the ``<vendor>/<model>`` shape inside a code span, which is how
    this README writes a model and nothing else in it looks like.
    """
    return set(re.findall(r"`((?:nvidia|google|meta|mistralai)/[\w.\-]+)`", README.read_text(encoding="utf-8")))


def _configured_model() -> str:
    """The default model ``.env.example`` hands to the bridge."""
    for line in ENV_EXAMPLE.read_text(encoding="utf-8").splitlines():
        if line.startswith("NEMOTRON_DEFAULT_MODEL="):
            return line.split("=", 1)[1].strip()
    return ""


class TestTheConfiguredModelIsTheDocumentedOne:
    """`.env.example` shipped `google/diffusiongemma-26b-a4b-it` while the README
    documented `nvidia/llama-3.3-nemotron-super-49b-v1`, and
    `nemotron_bridge.resolve` has no fallback -- so the scaffold every adopter
    copies pointed "Nemotron" traffic at a different vendor's model. Nothing
    noticed, because a value in a scaffold has no gate.
    """

    def test_the_scan_finds_both_sides(self) -> None:
        """A comparison between two empty sets passes and proves nothing."""
        assert _documented_models(), "no model identifier found in README"
        assert _configured_model(), "no NEMOTRON_DEFAULT_MODEL found in .env.example"

    def test_the_readme_names_exactly_one_model(self) -> None:
        assert len(_documented_models()) == 1, f"README names several models: {sorted(_documented_models())}"

    def test_the_scaffold_matches_the_documentation(self) -> None:
        assert _configured_model() in _documented_models(), (
            f".env.example sets NEMOTRON_DEFAULT_MODEL={_configured_model()!r} "
            f"but the README documents {sorted(_documented_models())}"
        )
