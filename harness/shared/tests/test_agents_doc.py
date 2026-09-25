"""The per-directory ``AGENTS.md`` gate, and proof that it judges something.

Two suites live here and they answer different questions. The synthetic ones
build a document in ``tmp_path`` and assert that each rule fires on the defect
it names -- a gate nobody has seen fail is a gate nobody knows works, which is
the `gate-mutation-proof` skill's whole premise. The repository suite then runs
the same rules over this tree, where a failure means a document has drifted
from the code it describes.

The positive controls are not ceremony. Every assertion below is of the form
"these findings are empty", and an empty finding list is exactly what a broken
discovery returns. `TestTheGateIsNotVacuous` is what stands between "the
documents are true" and "the walker matched nothing".
"""

from __future__ import annotations

import json
import logging
from datetime import date
from pathlib import Path

import pytest

from harness.shared.agents_doc import (
    audit,
    companion_findings,
    contains,
    discover_source_directories,
    document_findings,
    iter_documents,
    main,
    mermaid_findings,
    parse_document,
    render_staleness_report,
    required_directories,
    scope_names,
    source_file_count,
    stale_documents,
    subagent_findings,
    waiver_findings,
)
from harness.shared.agents_doc_policy import (
    DEFAULT_MAX_LINES,
    POLICY_BLOCK,
    AgentsDocConfig,
    load_config,
)
from harness.shared.policy_loader import PolicyError
from harness.shared.tests._helpers import REPO

pytestmark = pytest.mark.governance

CONFIG = AgentsDocConfig()


def write_document(
    directory: Path,
    *,
    scope: str = "`a.py`, `b.py`, `c.py`",
    reviewed: str | None = "2026-09-19",
    key_files: tuple[str, ...] = ("a.py",),
    diagram: str | None = 'flowchart LR\n  A["one"] --> B["two"]\n',
    extra_lines: int = 0,
    companion: str | None = "@AGENTS.md",
) -> Path:
    """A document that passes every rule, minus whatever the caller breaks."""
    directory.mkdir(parents=True, exist_ok=True)
    for name in ("a.py", "b.py", "c.py"):
        (directory / name).write_text("x = 1\n", encoding="utf-8")
    body = [f"# AGENTS.md — {directory.name}", "", f"**Scope:** {scope}"]
    if reviewed is not None:
        body.append(f"**Reviewed:** {reviewed}")
    body += ["", "## What this does", "It exists so a test has something true to read.", ""]
    if diagram is not None:
        body += ["## Map", "", "```mermaid", diagram.rstrip("\n"), "```", ""]
    body += ["## Key files", "", "| File | Role |", "| --- | --- |"]
    body += [f"| `{name}` | a module |" for name in key_files]
    body += [""] + [f"<!-- filler {n} -->" for n in range(extra_lines)]
    path = directory / "AGENTS.md"
    path.write_text("\n".join(body) + "\n", encoding="utf-8")
    if companion is not None:
        (directory / "CLAUDE.md").write_text(companion + "\n", encoding="utf-8")
    return path


def findings_for(directory: Path, config: AgentsDocConfig = CONFIG) -> list[str]:
    return document_findings(parse_document(directory / "AGENTS.md", directory), directory.name, config)


#: The keys a declared block owes. Derived from the dataclass rather than typed
#: out, so a threshold added to the module cannot leave this helper behind: the
#: new key would be missing from every synthetic policy and the whole suite
#: would fail closed, which is the direction a drifting fixture should fail in.
NUMERIC_KEYS = tuple(
    name for name, value in vars(AgentsDocConfig()).items() if isinstance(value, int) and not isinstance(value, bool)
)


def policy_block(**overrides: object) -> dict[str, object]:
    """A complete `agents_doc` block at its defaults, with `overrides` applied.

    Complete on purpose. A declared block owes every numeric key it reads, so a
    partial one is not a lighter fixture -- it is a different test.
    """
    block: dict[str, object] = {key: getattr(AgentsDocConfig(), key) for key in NUMERIC_KEYS}
    block.update(overrides)
    return block


def write_policy(tmp_path: Path, block: object) -> Path:
    """A policy file carrying only the block under test."""
    path = tmp_path / "governance-policy.json"
    payload: dict[str, object] = {} if block is None else {POLICY_BLOCK: block}
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


# --- Configuration resolution ---------------------------------------------------


class TestConfigResolution:
    """R-ADOC-4, C-ADOC-1. Precedence: explicit argument > environment > policy > default.

    The order matters in one direction only: a run must never silently enforce a
    number nobody reviewed. `_Section.int` handles the policy half; these cover
    the three levels above it and the adopter path below.
    """

    def test_an_undeclared_block_takes_built_in_defaults(self, tmp_path: Path) -> None:
        """The DEC-043 hazard. `_section` marks any present *file* as backed, so
        without the `declared()` guard every adopter policy written before this
        block existed would raise on its first numeric key."""
        assert load_config(write_policy(tmp_path, None)).max_lines == DEFAULT_MAX_LINES

    def test_a_declared_block_overrides_the_default(self, tmp_path: Path) -> None:
        assert load_config(write_policy(tmp_path, policy_block(max_lines=42))).max_lines == 42

    def test_a_declared_block_missing_a_numeric_key_fails_closed(self, tmp_path: Path) -> None:
        """A substituted threshold lets a gate report success against a number
        the policy no longer states, and the substitute is always plausible."""
        with pytest.raises(PolicyError, match="min_scope_names"):
            load_config(write_policy(tmp_path, {"max_lines": 42}))

    def test_the_environment_overrides_the_policy(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("AGENTS_DOC_MAX_LINES", "7")
        assert load_config(write_policy(tmp_path, policy_block(max_lines=999))).max_lines == 7

    def test_a_non_numeric_environment_override_is_ignored_not_fatal(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
    ) -> None:
        """The environment is the least reviewed level; a typo there must not be
        able to take a CI leg down. It is logged so the fallback is explicable."""
        monkeypatch.setenv("AGENTS_DOC_MAX_LINES", "not-a-number")
        with caplog.at_level(logging.WARNING):
            assert load_config(write_policy(tmp_path, policy_block(max_lines=999))).max_lines == 999
        assert "not an integer" in caplog.text

    def test_an_explicit_argument_overrides_the_environment(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("AGENTS_DOC_MAX_LINES", "7")
        assert load_config(write_policy(tmp_path, policy_block(max_lines=999)), max_lines=3).max_lines == 3

    def test_a_non_integer_explicit_override_is_rejected(self, tmp_path: Path) -> None:
        with pytest.raises(PolicyError, match="must be an integer"):
            load_config(write_policy(tmp_path, policy_block(max_lines=999)), max_lines="three")

    def test_a_list_key_of_the_wrong_shape_is_rejected(self, tmp_path: Path) -> None:
        block = policy_block(additional_directories="scripts")
        with pytest.raises(PolicyError, match="list of strings"):
            load_config(write_policy(tmp_path, block))

    def test_a_negative_threshold_is_rejected(self, tmp_path: Path) -> None:
        """A negative floor does not tighten a gate, it disables one:
        `min_documented_directories: -1` makes `present < floor` false for an
        empty tree, so the anti-vacuity check passes with no documents at all."""
        with pytest.raises(PolicyError, match="zero or greater"):
            load_config(write_policy(tmp_path, policy_block(min_documented_directories=-1)))

    def test_every_numeric_key_is_range_checked_not_just_one(self, tmp_path: Path) -> None:
        """Written against the dataclass, so a threshold added later is covered
        without anyone remembering to extend this test."""
        for key in NUMERIC_KEYS:
            with pytest.raises(PolicyError, match="zero or greater"):
                load_config(write_policy(tmp_path, policy_block(**{key: -1})))

    def test_an_override_reaches_an_undeclared_block(self, tmp_path: Path) -> None:
        """The undeclared-block branch returned early, which dropped the two
        levels above the policy: `--max-lines 5` against an adopter policy
        resolved to the built-in 150, so the documented precedence held only
        for deployments that had already adopted the block."""
        policy = write_policy(tmp_path, None)
        assert load_config(policy, max_lines=5).max_lines == 5

    def test_the_environment_reaches_an_undeclared_block(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("AGENTS_DOC_MAX_LINES", "9")
        assert load_config(write_policy(tmp_path, None)).max_lines == 9

    def test_a_waiver_map_of_the_wrong_shape_is_rejected(self, tmp_path: Path) -> None:
        with pytest.raises(PolicyError, match="object of string reasons"):
            load_config(write_policy(tmp_path, policy_block(waived_directories=["scripts"])))

    def test_this_repositorys_policy_declares_every_key_the_module_reads(self) -> None:
        """The live block, resolved the way a gate run resolves it. A key added
        to the module and forgotten in the policy fails here, not in CI."""
        assert load_config().filename == "AGENTS.md"


# --- Discovery ------------------------------------------------------------------


class TestDiscovery:
    """R-ADOC-2: the required set is derived from the tree, not transcribed."""

    def test_a_directory_at_the_floor_is_discovered(self, tmp_path: Path) -> None:
        write_document(tmp_path / "pkg")
        assert "pkg" in discover_source_directories(tmp_path, CONFIG)

    def test_a_directory_below_the_floor_is_not(self, tmp_path: Path) -> None:
        (tmp_path / "thin").mkdir()
        (tmp_path / "thin" / "only.py").write_text("x = 1\n", encoding="utf-8")
        assert discover_source_directories(tmp_path, CONFIG) == []

    def test_counting_is_not_recursive(self, tmp_path: Path) -> None:
        """A recursive count would make every ancestor of a deep tree owe a
        document, which is the opposite of scoping instructions to the edit."""
        write_document(tmp_path / "parent" / "child")
        assert source_file_count(tmp_path / "parent", CONFIG) == 0

    def test_pruned_directories_are_skipped(self, tmp_path: Path) -> None:
        write_document(tmp_path / "node_modules" / "pkg")
        assert discover_source_directories(tmp_path, CONFIG) == []

    def test_a_waived_directory_is_not_required(self, tmp_path: Path) -> None:
        write_document(tmp_path / "pkg")
        config = AgentsDocConfig(waived_directories={"pkg": "x" * 50})
        assert required_directories(tmp_path, config) == []

    def test_an_additional_directory_is_required_without_any_sources(self, tmp_path: Path) -> None:
        (tmp_path / "docs").mkdir()
        config = AgentsDocConfig(additional_directories=("docs",))
        assert required_directories(tmp_path, config) == ["docs"]

    def test_iter_documents_pairs_each_directory_with_its_path(self, tmp_path: Path) -> None:
        write_document(tmp_path / "pkg")
        assert list(iter_documents(tmp_path, CONFIG)) == [("pkg", tmp_path / "pkg" / "AGENTS.md")]


class TestWaiverFindings:
    def test_a_waiver_for_a_missing_directory_is_reported(self, tmp_path: Path) -> None:
        config = AgentsDocConfig(waived_directories={"gone": "y" * 50})
        assert "does not exist" in "".join(waiver_findings(tmp_path, config))

    def test_a_waiver_without_a_real_reason_is_reported(self, tmp_path: Path) -> None:
        (tmp_path / "pkg").mkdir()
        config = AgentsDocConfig(waived_directories={"pkg": "n/a"})
        assert "waiver reason" in "".join(waiver_findings(tmp_path, config))

    def test_a_justified_waiver_for_a_real_directory_is_accepted(self, tmp_path: Path) -> None:
        (tmp_path / "pkg").mkdir()
        assert waiver_findings(tmp_path, AgentsDocConfig(waived_directories={"pkg": "z" * 50})) == []


# --- Parsing --------------------------------------------------------------------


class TestParsing:
    def test_scope_names_reads_only_the_scope_line(self) -> None:
        text = "**Scope:** `a.py`, `b.py`\n\nProse naming `c.py` elsewhere.\n"
        assert scope_names(text) == ["a.py", "b.py"]

    def test_scope_names_is_empty_without_a_scope_line(self) -> None:
        assert scope_names("# No scope here\n") == []

    def test_key_files_reads_only_the_first_column_of_its_own_section(self, tmp_path: Path) -> None:
        """Prose outside the table names modules this directory does not own;
        holding those to existence here would reject true sentences."""
        directory = tmp_path / "pkg"
        write_document(directory)
        extra = "\n## Gotchas\n\n| `elsewhere.py` | not a key file |\n"
        (directory / "AGENTS.md").write_text(
            (directory / "AGENTS.md").read_text(encoding="utf-8") + extra, encoding="utf-8"
        )
        assert parse_document(directory / "AGENTS.md", directory).key_files == ("a.py",)

    def test_a_document_without_a_key_files_section_parses_to_no_key_files(self, tmp_path: Path) -> None:
        directory = tmp_path / "pkg"
        directory.mkdir()
        (directory / "AGENTS.md").write_text("# AGENTS.md\n\n**Scope:** `a.py`\n", encoding="utf-8")
        assert parse_document(directory / "AGENTS.md", directory).key_files == ()

    def test_diagrams_are_collected(self, tmp_path: Path) -> None:
        directory = tmp_path / "pkg"
        write_document(directory)
        assert len(parse_document(directory / "AGENTS.md", directory).diagrams) == 1


# --- Document rules, each with the defect it names ------------------------------


class TestDocumentFindings:
    def test_a_correct_document_reports_nothing(self, tmp_path: Path) -> None:
        write_document(tmp_path / "pkg")
        assert findings_for(tmp_path / "pkg") == []

    def test_a_scope_line_naming_a_missing_path_is_reported(self, tmp_path: Path) -> None:
        write_document(tmp_path / "pkg", scope="`a.py`, `b.py`, `deleted.py`")
        assert "does not exist" in "".join(findings_for(tmp_path / "pkg"))

    def test_a_technology_name_on_the_scope_line_is_left_alone(self, tmp_path: Path) -> None:
        """`harness/node` says `vitest` and `pnpm` truthfully. This module cannot
        resolve those; the Node gate does, against `package.json`. Judging them
        here would reject a true sentence."""
        write_document(tmp_path / "pkg", scope="`a.py`, `vitest`, `pnpm`")
        assert findings_for(tmp_path / "pkg") == []

    def test_a_scope_path_escaping_the_directory_is_reported(self, tmp_path: Path) -> None:
        """`directory / name` is not containment. `../sibling.py` resolved to a
        real file outside the directory the document describes, and existence
        was the whole rule, so the claim was accepted."""
        (tmp_path / "outside.py").write_text("x = 1\n", encoding="utf-8")
        write_document(tmp_path / "pkg", scope="`a.py`, `b.py`, `../outside.py`")
        assert "does not exist under" in "".join(findings_for(tmp_path / "pkg"))

    def test_an_absolute_scope_path_is_reported(self, tmp_path: Path) -> None:
        """An absolute name discards the base entirely, so any existing file on
        the machine satisfied the check."""
        write_document(tmp_path / "pkg", scope="`a.py`, `b.py`, `/etc/hosts`")
        assert "`/etc/hosts`" in "".join(findings_for(tmp_path / "pkg"))

    def test_a_key_file_escaping_the_directory_is_reported(self, tmp_path: Path) -> None:
        (tmp_path / "outside.py").write_text("x = 1\n", encoding="utf-8")
        write_document(tmp_path / "pkg", key_files=("a.py", "../outside.py"))
        assert "Key files names `../outside.py`" in "".join(findings_for(tmp_path / "pkg"))

    def test_containment_still_accepts_a_real_subdirectory_path(self, tmp_path: Path) -> None:
        """The negative control: tightening this must not start rejecting the
        nested paths documents legitimately name."""
        write_document(tmp_path / "pkg")
        (tmp_path / "pkg" / "sub").mkdir()
        (tmp_path / "pkg" / "sub" / "deep.py").write_text("x = 1\n", encoding="utf-8")
        assert contains(tmp_path / "pkg", "sub/deep.py")
        assert not contains(tmp_path / "pkg", "../outside.py")

    def test_a_scope_line_of_only_technologies_is_reported(self, tmp_path: Path) -> None:
        """Without one path claim the line is unfalsifiable by anything here."""
        write_document(tmp_path / "pkg", scope="`vitest`, `pnpm`, `eslint`")
        assert "names no path under" in "".join(findings_for(tmp_path / "pkg"))

    def test_a_thin_scope_line_is_reported(self, tmp_path: Path) -> None:
        """Two names is a sentence; the floor is what makes it falsifiable."""
        write_document(tmp_path / "pkg", scope="`a.py`, `b.py`")
        assert "at least 3" in "".join(findings_for(tmp_path / "pkg"))

    def test_a_key_file_that_does_not_exist_is_reported(self, tmp_path: Path) -> None:
        write_document(tmp_path / "pkg", key_files=("a.py", "moved.py"))
        assert "Key files names `moved.py`" in "".join(findings_for(tmp_path / "pkg"))

    def test_an_over_long_key_files_table_is_reported(self, tmp_path: Path) -> None:
        """Past the cap the table stops summarising and becomes a second copy of
        the README layout tree, which has its own gate and its own drift."""
        write_document(tmp_path / "pkg", key_files=("a.py",) * 9)
        assert "Key files lists 9 entries" in "".join(findings_for(tmp_path / "pkg"))

    def test_a_missing_reviewed_line_is_reported(self, tmp_path: Path) -> None:
        write_document(tmp_path / "pkg", reviewed=None)
        assert "no **Reviewed:** line" in "".join(findings_for(tmp_path / "pkg"))

    def test_a_reviewed_line_that_is_not_a_date_is_reported(self, tmp_path: Path) -> None:
        write_document(tmp_path / "pkg", reviewed="last-tuesday")
        assert "not an ISO date" in "".join(findings_for(tmp_path / "pkg"))

    def test_a_document_over_the_line_budget_is_reported(self, tmp_path: Path) -> None:
        write_document(tmp_path / "pkg", extra_lines=DEFAULT_MAX_LINES + 5)
        assert "exceeds the 150-line budget" in "".join(findings_for(tmp_path / "pkg"))

    def test_the_budget_comes_from_the_config_not_a_literal(self, tmp_path: Path) -> None:
        write_document(tmp_path / "pkg")
        assert "exceeds the 5-line budget" in "".join(findings_for(tmp_path / "pkg", AgentsDocConfig(max_lines=5)))


class TestCompanionFindings:
    """R-ADOC-3: the companion import is what makes a document load in Claude Code."""

    def test_a_correct_companion_reports_nothing(self, tmp_path: Path) -> None:
        write_document(tmp_path / "pkg")
        assert companion_findings(tmp_path / "pkg", "pkg", CONFIG) == []

    def test_a_missing_companion_is_reported(self, tmp_path: Path) -> None:
        """Without it the document is inert in Claude Code: AGENTS.md is read
        only where no CLAUDE.md sits above, and this repository has one."""
        write_document(tmp_path / "pkg", companion=None)
        assert "missing CLAUDE.md" in "".join(companion_findings(tmp_path / "pkg", "pkg", CONFIG))

    def test_a_companion_carrying_anything_else_is_reported(self, tmp_path: Path) -> None:
        write_document(tmp_path / "pkg", companion="@AGENTS.md\n\nAlso, some rules.")
        assert "expected '@AGENTS.md'" in "".join(companion_findings(tmp_path / "pkg", "pkg", CONFIG))


class TestMermaidFindings:
    """`test_documentation_truth` catches one failure mode -- a bare bracket in a
    label. These are the others, each of which renders as an error box or as
    something nobody can follow, and none of which is visible in a diff."""

    def test_a_well_formed_diagram_reports_nothing(self) -> None:
        assert mermaid_findings(['flowchart LR\n  A["one"] --> B["two"]\n'], CONFIG) == []

    def test_an_unknown_opening_keyword_is_reported(self) -> None:
        assert "not a known mermaid diagram type" in "".join(mermaid_findings(["flowchrt LR\n  A --> B\n"], CONFIG))

    def test_a_keyword_that_merely_shares_a_prefix_is_reported(self) -> None:
        """`startswith` accepted `flowchartX LR`, which renders as an error box.
        A check that admits the typo it exists to catch is not a check."""
        assert "not a known mermaid diagram type" in "".join(
            mermaid_findings(['flowchartX LR\n  A["a"] --> B["b"]\n'], CONFIG)
        )

    def test_a_valid_keyword_with_a_direction_is_still_accepted(self) -> None:
        """Negative control for the fix above: the token check must not start
        rejecting `flowchart LR`, which is how every diagram here opens."""
        assert mermaid_findings(['flowchart LR\n  A["a"] --> B["b"]\n'], CONFIG) == []

    def test_an_unbalanced_quote_is_reported(self) -> None:
        assert "unbalanced quote" in "".join(mermaid_findings(['flowchart LR\n  A["one] --> B\n'], CONFIG))

    def test_an_unbalanced_bracket_is_reported(self) -> None:
        assert "unbalanced brackets" in "".join(mermaid_findings(['flowchart LR\n  A["one"] --> B["two"\n'], CONFIG))

    def test_an_empty_diagram_is_reported(self) -> None:
        assert "is empty" in "".join(mermaid_findings(["\n  \n"], CONFIG))

    def test_too_many_diagrams_are_reported(self) -> None:
        good = 'flowchart LR\n  A["one"] --> B["two"]\n'
        assert "3 diagrams" in "".join(mermaid_findings([good] * 3, CONFIG))

    def test_a_diagram_past_the_node_cap_is_reported(self) -> None:
        body = "flowchart LR\n" + "".join(f'  N{n}["node {n}"]\n' for n in range(45))
        assert "declares 45 nodes" in "".join(mermaid_findings([body], CONFIG))

    def test_the_node_cap_comes_from_the_config(self) -> None:
        body = "flowchart LR\n" + "".join(f'  N{n}["node {n}"]\n' for n in range(5))
        assert "at most 3" in "".join(mermaid_findings([body], AgentsDocConfig(max_diagram_nodes=3)))


class TestSubagentFindings:
    """The only silent failure mode in the set. Claude Code treats a subagent
    file with malformed frontmatter as ordinary documentation -- no error, no
    warning -- so the agent simply never exists, and nobody finds out until it
    does not answer."""

    @staticmethod
    def write_subagent(tmp_path: Path, body: str, stem: str = "helper") -> AgentsDocConfig:
        directory = tmp_path / ".claude" / "agents"
        directory.mkdir(parents=True, exist_ok=True)
        (directory / f"{stem}.md").write_text(body, encoding="utf-8")
        return AgentsDocConfig()

    def test_a_well_formed_subagent_reports_nothing(self, tmp_path: Path) -> None:
        config = self.write_subagent(tmp_path, "---\nname: helper\ndescription: Does a thing.\n---\n\nBody.\n")
        assert subagent_findings(tmp_path, config) == []

    def test_no_subagent_directory_is_not_a_finding(self, tmp_path: Path) -> None:
        """A repository with no project subagents has nothing wrong with it."""
        assert subagent_findings(tmp_path, AgentsDocConfig()) == []

    def test_frontmatter_not_on_line_one_is_reported(self, tmp_path: Path) -> None:
        config = self.write_subagent(tmp_path, "\n---\nname: helper\ndescription: x\n---\n")
        assert "no opening '---' on line 1" in "".join(subagent_findings(tmp_path, config))

    def test_unclosed_frontmatter_is_reported(self, tmp_path: Path) -> None:
        config = self.write_subagent(tmp_path, "---\nname: helper\ndescription: x\n")
        assert "never closed" in "".join(subagent_findings(tmp_path, config))

    def test_a_missing_name_is_reported(self, tmp_path: Path) -> None:
        config = self.write_subagent(tmp_path, "---\ndescription: x\n---\n")
        assert "no 'name'" in "".join(subagent_findings(tmp_path, config))

    def test_a_name_containing_a_colon_is_reported(self, tmp_path: Path) -> None:
        """A colon is reserved for plugin-scoped names, so Claude Code rejects it."""
        config = self.write_subagent(tmp_path, "---\nname: 'plug:helper'\ndescription: x\n---\n")
        assert "contains ':'" in "".join(subagent_findings(tmp_path, config))

    def test_a_name_that_does_not_match_the_filename_is_reported(self, tmp_path: Path) -> None:
        config = self.write_subagent(tmp_path, "---\nname: other\ndescription: x\n---\n")
        assert "does not match the filename" in "".join(subagent_findings(tmp_path, config))

    def test_a_missing_description_is_reported(self, tmp_path: Path) -> None:
        """Without one nothing tells Claude when to delegate, so it never does."""
        config = self.write_subagent(tmp_path, "---\nname: helper\n---\n")
        assert "no 'description'" in "".join(subagent_findings(tmp_path, config))

    def test_this_repositorys_subagents_are_well_formed(self) -> None:
        assert subagent_findings(REPO, load_config()) == []


# --- The audit and the command-line entry point ---------------------------------


class TestAudit:
    def test_a_complete_tree_reports_nothing(self, tmp_path: Path) -> None:
        for name in ("one", "two"):
            write_document(tmp_path / name)
        config = AgentsDocConfig(min_documented_directories=2)
        assert audit(tmp_path, config) == []

    def test_a_missing_document_is_reported(self, tmp_path: Path) -> None:
        write_document(tmp_path / "one")
        (tmp_path / "one" / "AGENTS.md").unlink()
        assert "missing AGENTS.md" in "".join(audit(tmp_path, AgentsDocConfig(min_documented_directories=0)))

    def test_the_population_floor_catches_a_vacuous_pass(self, tmp_path: Path) -> None:
        """An empty tree satisfies every rule above it. The floor is what makes
        "all documents are true" different from "there are no documents"."""
        assert "the floor is 20" in "".join(audit(tmp_path, AgentsDocConfig()))

    def test_audit_resolves_its_own_config_when_given_none(self, tmp_path: Path) -> None:
        assert audit(tmp_path) != []


class TestStaleness:
    """C-ADOC-4. Reported, never blocking. Presence of `**Reviewed:**` is a blocking rule;
    its age is not, because a clock-dependent gate over twenty-five documents
    turns unrelated pull requests red at a date boundary (DEC-070, C-ADOC-4)."""

    @staticmethod
    def tree(tmp_path: Path, reviewed: str) -> AgentsDocConfig:
        write_document(tmp_path / "pkg", reviewed=reviewed)
        return AgentsDocConfig(additional_directories=("pkg",))

    def test_a_fresh_document_is_not_stale(self, tmp_path: Path) -> None:
        config = self.tree(tmp_path, "2026-09-19")
        assert stale_documents(tmp_path, config, 90, date(2026, 10, 1)) == []

    def test_a_document_past_the_horizon_is_reported(self, tmp_path: Path) -> None:
        config = self.tree(tmp_path, "2026-01-01")
        assert stale_documents(tmp_path, config, 90, date(2026, 10, 1)) == [("pkg", "2026-01-01", 273)]

    def test_an_unparseable_date_is_left_to_the_blocking_rule(self, tmp_path: Path) -> None:
        """Reporting it here as well would file an issue for something that has
        already failed `make ci`, which trains people to ignore the issue."""
        config = self.tree(tmp_path, "last-tuesday")
        assert stale_documents(tmp_path, config, 90, date(2026, 10, 1)) == []

    def test_a_missing_document_is_not_a_staleness_report(self, tmp_path: Path) -> None:
        (tmp_path / "pkg").mkdir()
        config = AgentsDocConfig(additional_directories=("pkg",))
        assert stale_documents(tmp_path, config, 90, date(2026, 10, 1)) == []

    def test_nothing_stale_renders_nothing(self) -> None:
        """The workflow appends this to an issue body and opens the issue only
        when the file is non-empty, so an empty string is load-bearing."""
        assert render_staleness_report([], 90, "AGENTS.md") == ""

    def test_the_report_names_the_directory_and_the_age(self) -> None:
        report = render_staleness_report([("pkg", "2026-01-01", 273)], 90, "AGENTS.md")
        assert "| `pkg` | 2026-01-01 | 273 |" in report
        assert "past 90 days" in report

    def test_the_command_line_reports_and_still_exits_zero(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Exit 0 is the whole point: this path must never fail a pipeline."""
        write_document(tmp_path / "pkg", reviewed="2020-01-01")
        policy = write_policy(tmp_path, policy_block(additional_directories=["pkg"]))
        assert main(["--repo-root", str(tmp_path), "--policy", str(policy), "--stale-since-days", "1"]) == 0
        assert "| `pkg` |" in capsys.readouterr().out


class TestCommandLine:
    """Each case passes `--policy`. Without it the CLI resolves this repository's
    policy, whose `additional_directories` name paths a `tmp_path` tree does not
    have -- so the run under test would be judged against the wrong contract."""

    def test_list_prints_the_required_directories(self, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
        write_document(tmp_path / "pkg")
        policy = write_policy(tmp_path, policy_block(min_documented_directories=1))
        assert main(["--repo-root", str(tmp_path), "--policy", str(policy), "--list"]) == 0
        assert capsys.readouterr().out.strip() == "pkg"

    def test_a_clean_tree_exits_zero(self, tmp_path: Path) -> None:
        for name in ("one", "two"):
            write_document(tmp_path / name)
        policy = write_policy(tmp_path, policy_block(min_documented_directories=2))
        assert main(["--repo-root", str(tmp_path), "--policy", str(policy)]) == 0

    def test_findings_exit_non_zero(self, tmp_path: Path) -> None:
        policy = write_policy(tmp_path, policy_block())
        assert main(["--repo-root", str(tmp_path), "--policy", str(policy)]) == 1

    def test_an_explicit_override_reaches_the_audit(self, tmp_path: Path) -> None:
        """`--max-lines` is the one threshold the command line can tighten, so a
        run can prove a stricter budget without editing a protected policy."""
        write_document(tmp_path / "pkg")
        policy = write_policy(tmp_path, policy_block(min_documented_directories=1))
        argv = ["--repo-root", str(tmp_path), "--policy", str(policy)]
        assert main(argv) == 0
        assert main([*argv, "--max-lines", "5"]) == 1

    def test_an_unreadable_policy_exits_non_zero_rather_than_raising(self, tmp_path: Path) -> None:
        """Fail closed: a gate that crashes on its own policy has still not
        judged the tree, and an exception trace is not a verdict."""
        bad = tmp_path / "policy.json"
        bad.write_text(json.dumps({POLICY_BLOCK: {"max_lines": 1}}), encoding="utf-8")
        assert main(["--repo-root", str(tmp_path), "--policy", str(bad)]) == 1


# --- This repository ------------------------------------------------------------


class TestTheGateIsNotVacuous:
    """Positive controls. Every assertion in the suite below is "no findings",
    and a discovery that matched nothing returns exactly that."""

    def test_the_walker_finds_source_directories(self) -> None:
        assert len(discover_source_directories(REPO, load_config())) >= 15

    def test_the_required_set_is_larger_than_the_discovered_one(self) -> None:
        """`additional_directories` carries the boundaries that are document-worthy
        but source-light. If it stopped being applied, this is what would say so."""
        config = load_config()
        assert len(required_directories(REPO, config)) > len(discover_source_directories(REPO, config))

    def test_a_known_directory_is_required(self) -> None:
        assert "harness/shared/governance" in required_directories(REPO, load_config())

    def test_openspec_is_not_in_the_required_set(self) -> None:
        """DEC-055 folds `openspec/` into `docs/specs/` and deletes it; its
        AC-28 requires `ls openspec` to fail. Requiring a document there would
        make this gate depend on a directory scheduled for removal, and create
        one that must immediately be migrated or deleted."""
        assert "openspec" not in required_directories(REPO, load_config())

    def test_every_waiver_names_a_directory_that_exists(self) -> None:
        assert waiver_findings(REPO, load_config()) == []


class TestThisRepository:
    """R-ADOC-1 and R-ADOC-5 over the real tree.

    C-ADOC-2 and C-ADOC-3 are asserted here too, by absence: no document is
    written into `.mango/agents/` or any `harness/*/agents/`, whose `*.md`
    namespace five existing assertions hold to an exact membership, and no
    existing gate's exclusion list was widened to admit one. Those five suites
    still pass unchanged, which is what makes this a addition rather than a
    loosening.
    """

    def test_no_document_was_written_into_a_persona_namespace(self) -> None:
        """C-ADOC-2. Widening those globs would have been the easy fix and the
        wrong one: it weakens five real gates to accommodate prose."""
        config = load_config()
        intruders = [
            str(path.relative_to(REPO))
            for path in REPO.glob("**/agents/" + config.filename)
            if ".git" not in path.parts
        ]
        assert not intruders, f"a document landed in a persona namespace: {intruders}"

    def test_every_required_directory_carries_a_document(self) -> None:
        config = load_config()
        missing = [relative for relative, path in iter_documents(REPO, config) if not path.is_file()]
        assert not missing, (
            f"these directories owe a {config.filename} and do not have one: {missing}. "
            "Add the document, or waive the directory in governance-policy.json with a reason."
        )

    def test_every_document_is_backed_by_its_own_directory(self) -> None:
        findings = audit(REPO, load_config())
        assert not findings, "per-directory documentation has drifted from the tree:\n" + "\n".join(findings)
