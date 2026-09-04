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

import json
import re
from pathlib import Path

import pytest

from harness.shared.tests._helpers import REPO

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover - Python < 3.11 uses the backport
    import tomli as tomllib  # type: ignore[no-redef]

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
            check_path = rule.lstrip("!")
            parent = (REPO / check_path.rstrip("/")).parent
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


# --- One version, many mirrors -------------------------------------------------
#
# The project version had five values at once (pyproject 2.2.5, README 2.3.0,
# Makefile/CHANGELOG/NEXT_STEPS 2.4.0, package.json 2.0.0), a drift DEC-013 had
# already reconciled once. `pyproject.toml`'s `[project].version` is the packaging
# truth; every other site is a mirror and is checked here (extends R-CEG-1 in
# docs/specs/ci-enforcement-gaps.md; tech-debt-hardening-plan R-TDH-7).

_SEMVER = r"(\d+\.\d+\.\d+)"

#: Mirror path (repo-relative) -> regex whose first group is the version it states.
#: `harness/node/package.json` is handled as JSON below rather than by regex.
VERSION_MIRRORS: dict[str, str] = {
    "README.md": r"^\*\*Version:\*\*\s+" + _SEMVER,
    "NEXT_STEPS.md": r"^\*\*Version:\*\*\s+" + _SEMVER,
    "docs/architecture/c4_architecture.md": r"^\*\*Version:\*\*\s+" + _SEMVER,
    "Makefile": r"^# Agentic SSD v" + _SEMVER,
    # The first semver heading is the newest released entry; an `[Unreleased]`
    # heading above it carries no number and is passed over.
    "CHANGELOG.md": r"^## \[v?" + _SEMVER + r"\]",
}
PACKAGE_JSON = "harness/node/package.json"


def declared_version(root: Path) -> str:
    data = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))
    return str(data["project"]["version"])


def mirrored_versions(root: Path) -> dict[str, str | None]:
    """Each mirror's stated version, or None when the site cannot be found."""
    found: dict[str, str | None] = {}
    for rel, pattern in VERSION_MIRRORS.items():
        match = re.search(pattern, (root / rel).read_text(encoding="utf-8"), re.M)
        found[rel] = match.group(1) if match else None
    package = json.loads((root / PACKAGE_JSON).read_text(encoding="utf-8"))
    found[PACKAGE_JSON] = package.get("version")
    return found


def version_drift(root: Path) -> dict[str, str | None]:
    """Mirrors disagreeing with pyproject (missing sites count as drift)."""
    truth = declared_version(root)
    return {rel: seen for rel, seen in mirrored_versions(root).items() if seen != truth}


class TestVersionIsSingleSourced:
    def test_every_mirror_is_found(self) -> None:
        missing = [rel for rel, seen in mirrored_versions(REPO).items() if seen is None]
        assert not missing, f"version mirrors whose pattern no longer matches: {missing}"

    def test_every_mirror_agrees_with_pyproject(self) -> None:
        drift = version_drift(REPO)
        assert not drift, (
            f"pyproject.toml declares {declared_version(REPO)} but these mirrors disagree: {drift}. "
            "pyproject is the single source; update the mirrors, never the other way round."
        )

    @pytest.mark.parametrize("mirror", sorted([*VERSION_MIRRORS, PACKAGE_JSON]))
    def test_a_mutated_mirror_is_reported(self, mirror: str, tmp_path: Path) -> None:
        """The negative case: the check must fail when exactly one site drifts."""
        for rel in ["pyproject.toml", PACKAGE_JSON, *VERSION_MIRRORS]:
            target = tmp_path / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text((REPO / rel).read_text(encoding="utf-8"), encoding="utf-8")
        truth = declared_version(tmp_path)
        bogus = "0.0.1"
        assert bogus != truth
        path = tmp_path / mirror
        if mirror == PACKAGE_JSON:
            data = json.loads(path.read_text(encoding="utf-8"))
            data["version"] = bogus
            path.write_text(json.dumps(data), encoding="utf-8")
        else:
            text = path.read_text(encoding="utf-8")
            mutated = re.sub(
                VERSION_MIRRORS[mirror],
                lambda m: m.group(0).replace(m.group(1), bogus),
                text,
                count=1,
                flags=re.M,
            )
            path.write_text(mutated, encoding="utf-8")
        assert version_drift(tmp_path) == {mirror: bogus}


# --- Changelog sections stay readable -------------------------------------------
#
# The v2.2.4 section of CHANGELOG.md had grown to about 1,300 lines before it was
# moved to docs/releases/v2.2.4.md (tech-debt-hardening-plan R-TDH-24). A byte
# budget on the whole file would have been self-defeating -- the plan's own
# arithmetic put the file at ~49 kB *after* that move -- so the cap is per release
# section and is read from `limits.changelog_section_lines` in the policy.

CHANGELOG = REPO / "CHANGELOG.md"
GOVERNANCE_POLICY = REPO / "harness" / "shared" / "governance-policy.json"
_VERSION_HEADING = re.compile(r"^## \[v?\d+\.\d+\.\d+\]")
_ANY_H2 = re.compile(r"^## ")


def changelog_section_cap() -> int:
    """`limits.changelog_section_lines`, read straight from the policy file.

    No default: a missing or non-numeric key fails the test rather than
    quietly measuring against a literal that the policy never agreed to.
    """
    policy = json.loads(GOVERNANCE_POLICY.read_text(encoding="utf-8"))
    value = policy.get("limits", {}).get("changelog_section_lines")
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        pytest.fail(f"governance-policy.json limits.changelog_section_lines is absent or non-numeric: {value!r}")
    return int(value)


def changelog_sections(text: str) -> dict[str, int]:
    """Line count of every ``## [x.y.z]`` section of a changelog, keyed by heading.

    A section runs from its heading line to the line before the next ``## ``
    heading of any kind (or the end of the file), heading included. Two parts
    of the real file are exempt, both by construction rather than by name:

    * ``## [Unreleased]`` carries no version, so it never matches the pattern.
      It is the one section that is *meant* to grow until a release cuts it,
      and capping it would only push entries out of the changelog.
    * The trailing ``## Harness gate-contract history`` block is the folded
      ``harness/CHANGELOG.md`` (v2.0.0-v2.1.5). Its entries are ``###``
      sub-headings under one non-version ``##`` heading, so that heading ends
      the last release section without starting a new one, and the block's
      length is never attributed to any version.
    """
    sections: dict[str, int] = {}
    current: str | None = None
    for line in text.splitlines():
        if _ANY_H2.match(line):
            current = line.rstrip() if _VERSION_HEADING.match(line) else None
            if current is not None:
                sections[current] = 0
        if current is not None:
            sections[current] += 1
    return sections


def oversized_changelog_sections(text: str, cap: int) -> dict[str, int]:
    """The release sections longer than ``cap`` lines, with their lengths."""
    return {heading: count for heading, count in changelog_sections(text).items() if count > cap}


class TestChangelogSectionCap:
    def test_changelog_section_parser_finds_release_sections(self) -> None:
        """Positive control: an empty parse would make the cap check pass while
        measuring nothing, and the exemptions must be exemptions, not misses."""
        sections = changelog_sections(CHANGELOG.read_text(encoding="utf-8"))
        assert len(sections) >= 3, f"parsed too few release sections out of CHANGELOG.md: {sorted(sections)}"
        assert all(_VERSION_HEADING.match(heading) for heading in sections)
        text = CHANGELOG.read_text(encoding="utf-8")
        assert "## [Unreleased]" in text and "## Harness gate-contract history" in text

    def test_changelog_section_cap_is_policy_sourced(self) -> None:
        assert changelog_section_cap() > 0

    def test_every_changelog_section_is_within_the_cap(self) -> None:
        cap = changelog_section_cap()
        over = oversized_changelog_sections(CHANGELOG.read_text(encoding="utf-8"), cap)
        assert not over, (
            f"CHANGELOG.md release sections longer than limits.changelog_section_lines={cap}: {over}. "
            "Move the body to docs/releases/<version>.md and leave a pointer under the heading."
        )

    def test_changelog_section_one_line_over_the_cap_is_reported(self) -> None:
        """The negative case: exactly the offending section, nothing else."""
        cap = changelog_section_cap()
        filler = "- an entry\n"
        at_cap = "## [1.0.0] - 2026-01-01\n" + filler * (cap - 1)  # heading + (cap - 1) lines == cap
        one_over = "## [1.1.0] - 2026-01-02\n" + filler * cap  # heading + cap lines == cap + 1
        text = (
            "# Changelog\n\n## [Unreleased]\n" + filler * (cap + 5)  # exempt however long
            + one_over
            + at_cap
            + "## Harness gate-contract history (formerly `harness/CHANGELOG.md`)\n"
            + "### v2.1.5 - old\n" + filler * (cap + 5)  # exempt trailing block
        )
        assert oversized_changelog_sections(text, cap) == {"## [1.1.0] - 2026-01-02": cap + 1}
        assert changelog_sections(text)["## [1.0.0] - 2026-01-01"] == cap


class TestTheDeclaredVersionIsARealRelease:
    """R-GT-9: the mirrors agreeing with each other is not the same as the
    release existing.

    `TestVersionIsSingleSourced` pins the four mirrors to `pyproject.toml` and
    passes -- it passed on 2026-09-03 while the most recently merged work was
    described in a commit message and an RCA filename as v2.5.0, with no
    `## [2.5.0]` section anywhere in the changelog and no git tag in the
    repository's history. Nothing connected a declared version to a released
    one, so the whole set of mirrors could be internally consistent and
    collectively wrong.
    """

    @staticmethod
    def _sections(text: str) -> set[str]:
        return set(re.findall(r"^## \[v?(\d+\.\d+\.\d+)\]", text, re.M))

    def test_the_parser_finds_the_release_sections(self) -> None:
        """Guards the check: no sections found would make it vacuous."""
        sections = self._sections(CHANGELOG.read_text(encoding="utf-8"))
        assert len(sections) > 1, f"only found {sections} in CHANGELOG.md; the parser has stopped matching"

    def test_declared_version_has_a_changelog_section(self) -> None:
        declared = declared_version(REPO)
        sections = self._sections(CHANGELOG.read_text(encoding="utf-8"))
        assert declared in sections, (
            f"pyproject.toml declares {declared} but CHANGELOG.md has no `## [{declared}]` section. "
            f"Sections present: {sorted(sections)}. Either the version was bumped without writing "
            "the release, or the release was written under a different number -- both leave the "
            "repository disagreeing with itself about what it currently is."
        )

    def test_a_version_with_no_section_is_reported(self, tmp_path: Path) -> None:
        """The negative case, so this cannot pass by matching everything."""
        for rel in ["pyproject.toml", "CHANGELOG.md"]:
            target = tmp_path / rel
            target.write_text((REPO / rel).read_text(encoding="utf-8"), encoding="utf-8")
        pyproject = tmp_path / "pyproject.toml"
        bumped = re.sub(
            r'^(version\s*=\s*)"[^"]+"', r'\1"9.9.9"', pyproject.read_text(encoding="utf-8"), count=1, flags=re.M
        )
        pyproject.write_text(bumped, encoding="utf-8")
        assert declared_version(tmp_path) == "9.9.9"
        assert "9.9.9" not in self._sections((tmp_path / "CHANGELOG.md").read_text(encoding="utf-8"))


#: A mermaid node whose label is delimited by bare brackets, capturing the label.
#: Quoted labels (`id["..."]`) are excluded by the negative lookahead: quoting is
#: exactly what makes a bracket inside a label safe, so a quoted node is correct
#: by construction and must not be reported.
UNQUOTED_MERMAID_NODE = re.compile(r"\w+\[(?!\")([^\]]*)\]")

#: Documentation trees whose fenced mermaid blocks must be renderable.
DIAGRAM_ROOTS = ("docs", "README.md", "CLAUDE.md")


def mermaid_blocks(text: str) -> list[str]:
    """The body of every fenced ```mermaid block in `text`."""
    return re.findall(r"```mermaid\n(.*?)```", text, re.S)


def documents_with_diagrams() -> list[Path]:
    """Markdown files under `DIAGRAM_ROOTS` that contain at least one mermaid block."""
    candidates: list[Path] = []
    for entry in DIAGRAM_ROOTS:
        target = REPO / entry
        candidates.extend(sorted(target.rglob("*.md")) if target.is_dir() else [target])
    return [path for path in candidates if path.is_file() and "```mermaid" in path.read_text(encoding="utf-8")]


class TestEveryMermaidDiagramCanRender:
    """A diagram that fails to parse documents nothing, and says so to no one.

    `c4_architecture.md` carried a node label reading
    ``AgentMetaTools[... (Context7) [Planned]]``. Mermaid ends a bare-bracket
    label at the first `]`, so the trailing `]]` is a syntax error and the whole
    diagram -- the agent-topology view, not one node -- rendered as an error box
    on GitHub. It had no gate: prose is checked here for naming real paths, and
    nothing checked that the pictures still draw. This is the documentation
    instance of the branch's recurring shape, a gate whose scope stopped short
    of the artefact it is supposed to cover.
    """

    def test_at_least_one_document_carries_a_diagram(self) -> None:
        """Guards the finder: a glob that matches nothing would pass every case below."""
        found = documents_with_diagrams()
        assert found, "no markdown with a mermaid block was found; the discovery is broken"
        assert any(path.name == "c4_architecture.md" for path in found)

    def test_no_node_label_ends_early_on_a_nested_bracket(self) -> None:
        offenders: list[str] = []
        for path in documents_with_diagrams():
            for index, block in enumerate(mermaid_blocks(path.read_text(encoding="utf-8"))):
                for lineno, line in enumerate(block.splitlines(), 1):
                    for match in UNQUOTED_MERMAID_NODE.finditer(line):
                        if "[" in match.group(1):
                            offenders.append(f"{path.relative_to(REPO)} block {index} line {lineno}: {line.strip()}")
        assert not offenders, (
            "these mermaid node labels contain a bracket without being quoted, so the label ends "
            "early and the diagram fails to parse. Wrap the label in double quotes: "
            + "; ".join(offenders)
        )

    def test_the_detector_reports_a_known_bad_label(self) -> None:
        """The exact shape found in `c4_architecture.md`, so the regex cannot silently stop matching."""
        bad = 'Node[label with (parens) [Planned]]'
        match = UNQUOTED_MERMAID_NODE.search(bad)
        assert match is not None and "[" in match.group(1)

    def test_the_detector_accepts_a_quoted_label(self) -> None:
        quoted = 'Node["label with [brackets] and (parens)"]'
        assert [m for m in UNQUOTED_MERMAID_NODE.finditer(quoted) if "[" in m.group(1)] == []


# --- Documented routes are registered routes ------------------------------------
#
# `c4_architecture.md` listed `/health`, `/v1/orchestrator/run` and `/v1/models`
# as the gateway's API while `harness/api_server/main.py` registered exactly one
# route, `/api/orchestrate`, plus the static mount at `/` (2026 standards audit,
# M26). The list is read from the doc's "API surface" section only, so prose
# elsewhere may discuss a route that is planned; a path *listed as the API* has
# to exist on the app object at test time.

C4_ARCHITECTURE = REPO / "docs" / "architecture" / "c4_architecture.md"
API_SECTION_HEADING = re.compile(r"^(#{2,4}) [^\n]*API surface", re.M)


def documented_api_routes(text: str) -> list[str]:
    """Every backticked ``/...`` path under the API-surface heading.

    The section runs to the next heading of the same or a higher level, so a
    later section's paths are not attributed to the API.
    """
    match = API_SECTION_HEADING.search(text)
    if not match:
        return []
    body = text[match.end():]
    end = re.search(rf"^#{{1,{len(match.group(1))}}} ", body, re.M)
    if end:
        body = body[: end.start()]
    return re.findall(r"`(/[^`\s]*)`", body)


class TestDocumentedRoutesExist:
    @staticmethod
    def _registered_paths() -> set[str]:
        from harness.api_server.main import app

        # Starlette stores `Mount("/")` with an empty path (it strips the
        # trailing slash), so the static mount is read back as the `/` it serves.
        return {str(getattr(route, "path", "")) or "/" for route in app.routes}

    def test_the_section_lists_routes(self) -> None:
        """Guards the parse: a heading rename would make the check below vacuous."""
        assert documented_api_routes(C4_ARCHITECTURE.read_text(encoding="utf-8")), (
            "no backticked route found under the C4 doc's 'API surface' heading"
        )

    def test_every_documented_route_is_registered(self) -> None:
        documented = set(documented_api_routes(C4_ARCHITECTURE.read_text(encoding="utf-8")))
        missing = sorted(documented - self._registered_paths())
        assert not missing, (
            f"c4_architecture.md documents routes the FastAPI app does not register: {missing}. "
            "List a route in the API-surface section only once `app.routes` carries it."
        )

    def test_the_parser_stops_at_the_next_section(self) -> None:
        """The negative case: a path listed after the section is not the API's."""
        text = "## 2.2 API surface\n- `/nowhere`\n#### note `/still-inside`\n## 3. Next\n- `/outside`\n"
        assert documented_api_routes(text) == ["/nowhere", "/still-inside"]
        assert "/nowhere" not in self._registered_paths()
