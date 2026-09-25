"""Which paths the gate may touch at all — containment, and the refusal of links.

Split from `test_agents_doc.py` when it reached ``limits.test_size_budget_lines``.
The seam is not arbitrary: everything here answers *may this path be read*, while
next door answers *is this document's claim true*. This half grew in five
consecutive review rounds and next door did not, which is the clearest evidence
there was that they are two concerns sharing a file.

Read the round order, because each fix closed the layer it was reported at and
left the next one open — the pattern worth learning from this branch:

1. a scope-line path could escape its directory (`../`, then `/etc/passwd`);
2. a *policy*-valued path could redirect the audit somewhere empty;
3. the Windows drive-relative form of the same (`C:foo`);
4. an in-tree symlink pointing outside, caught only at resolution time;
5. the document and companion *files* being links at all, which `contains()`
   accepted because an in-tree link resolves inside and compares equal;
6. and the skip added in (5) swallowing a configured directory that does not
   resolve at all, which is the one defect here that a fix of mine created.

Every case below is a defect that shipped, not a hypothetical.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from harness.shared.agents_doc import (
    audit,
    companion_findings,
    configured_path_findings,
    subagent_findings,
)
from harness.shared.agents_doc_policy import AgentsDocConfig
from harness.shared.tests._agents_doc_helpers import CONFIG, write_document

pytestmark = pytest.mark.governance


class TestConfiguredPathsAreRealAndInTree:
    """R-ADOC-6 at the point of use. The load-time rule is lexical, so it cannot
    see a symlink: a plain relative name stays plain until something resolves
    it. Lexical is still right at load time -- a configured directory may
    legitimately not exist yet -- so the resolution half lives here."""

    def _repo(self, tmp_path: Path) -> Path:
        (tmp_path / ".claude" / "agents").mkdir(parents=True)
        return tmp_path

    def test_a_missing_subagent_directory_is_not_a_finding(self, tmp_path: Path) -> None:
        """The negative control: a repository need not define subagents."""
        config = AgentsDocConfig(subagent_directory="nowhere")
        assert subagent_findings(tmp_path, config) == []

    def test_an_existing_non_directory_is_reported(self, tmp_path: Path) -> None:
        """`is_dir()` alone returned `[]` here, so pointing the key at a file
        switched the frontmatter audit off with no finding at all."""
        (tmp_path / "notadir").write_text("x\n", encoding="utf-8")
        findings = subagent_findings(tmp_path, AgentsDocConfig(subagent_directory="notadir"))
        assert "is not a directory" in "".join(findings)

    def test_a_symlink_out_of_the_tree_is_reported_not_followed(self, tmp_path: Path) -> None:
        outside = tmp_path / "outside"
        outside.mkdir()
        (outside / "rogue.md").write_text("no frontmatter\n", encoding="utf-8")
        root = self._repo(tmp_path / "repo")
        (root / "linked").symlink_to(outside)
        findings = subagent_findings(root, AgentsDocConfig(subagent_directory="linked"))
        assert "resolves outside the checkout" in "".join(findings)
        assert "rogue.md" not in "".join(findings), "the external tree must not be audited"

    def test_an_additional_directory_pointing_out_of_the_tree_is_reported(self, tmp_path: Path) -> None:
        outside = tmp_path / "outside"
        outside.mkdir()
        root = self._repo(tmp_path / "repo")
        (root / "linked").symlink_to(outside)
        config = AgentsDocConfig(additional_directories=("linked",))
        assert "resolves outside the checkout" in "".join(configured_path_findings(root, config))

    def test_a_missing_additional_directory_is_reported(self, tmp_path: Path) -> None:
        """The hole the `audit()` skip opened. `contains()` refuses a path that does
        not resolve *at all* as readily as one resolving outside, so the skip added
        to stop reading an external tree also swallowed a typo in
        `additional_directories` -- and with the floor satisfied the whole audit
        returned `[]`. A waived directory already had this check; an additional one
        had none."""
        root = self._repo(tmp_path / "repo")
        config = AgentsDocConfig(additional_directories=("typo",))
        assert "is not a directory in this checkout" in "".join(configured_path_findings(root, config))

    def test_an_additional_directory_that_is_a_file_is_reported(self, tmp_path: Path) -> None:
        root = self._repo(tmp_path / "repo")
        (root / "notadir").write_text("x\n", encoding="utf-8")
        config = AgentsDocConfig(additional_directories=("notadir",))
        assert "is not a directory in this checkout" in "".join(configured_path_findings(root, config))

    def test_a_real_additional_directory_is_not_reported(self, tmp_path: Path) -> None:
        """The negative control: the rule must refuse only what is broken."""
        root = self._repo(tmp_path / "repo")
        (root / "real").mkdir()
        config = AgentsDocConfig(additional_directories=("real",))
        assert configured_path_findings(root, config) == []

    def test_the_audit_never_skips_a_configured_directory_in_silence(self, tmp_path: Path) -> None:
        """End to end, which is where it actually bit: a satisfied population floor
        plus one bad entry used to produce a clean run."""
        for name in ("one", "two"):
            write_document(tmp_path / name)
        config = AgentsDocConfig(additional_directories=("one", "two", "missing"), min_documented_directories=2)
        assert "missing" in "".join(audit(tmp_path, config))

    def _document_body(self) -> str:
        return (
            "# AGENTS.md — pkg\n\n**Scope:** `a.py`, `b.py`, `c.py`\n"
            "**Reviewed:** 2026-09-19\n\n## What this does\nIt exists.\n\n"
            "## Key files\n\n| File | Role |\n| --- | --- |\n| `a.py` | a module |\n"
        )

    def test_a_symlinked_companion_is_reported(self, tmp_path: Path) -> None:
        """DEC-070 rejected a symlinked companion for Windows portability, and
        that was prose. A link to an external file holding the right one line
        satisfied the rule while the content the gate read lived outside the
        checkout, so the decision is mechanical now."""
        outside = tmp_path / "outside"
        outside.mkdir()
        (outside / "companion.md").write_text("@AGENTS.md\n", encoding="utf-8")
        directory = tmp_path / "repo" / "pkg"
        directory.mkdir(parents=True)
        (directory / "CLAUDE.md").symlink_to(outside / "companion.md")
        findings = companion_findings(directory, "pkg", CONFIG)
        assert "must be a regular file in this directory, not a link" in "".join(findings)

    def test_a_real_companion_beside_the_document_is_accepted(self, tmp_path: Path) -> None:
        """The negative control: the rule is about escaping, not about existing."""
        directory = tmp_path / "pkg"
        directory.mkdir()
        (directory / "CLAUDE.md").write_text("@AGENTS.md\n", encoding="utf-8")
        assert companion_findings(directory, "pkg", CONFIG) == []

    def test_a_symlinked_document_is_reported(self, tmp_path: Path) -> None:
        """The document itself was read through a link the same way."""
        outside = tmp_path / "outside"
        outside.mkdir()
        (outside / "AGENTS.md").write_text(self._document_body(), encoding="utf-8")
        root = tmp_path / "repo"
        directory = root / "pkg"
        directory.mkdir(parents=True)
        for name in ("a.py", "b.py", "c.py"):
            (directory / name).write_text("x = 1\n", encoding="utf-8")
        (directory / "CLAUDE.md").write_text("@AGENTS.md\n", encoding="utf-8")
        (directory / "AGENTS.md").symlink_to(outside / "AGENTS.md")
        config = AgentsDocConfig(additional_directories=("pkg",), min_documented_directories=1)
        escapes = [f for f in audit(root, config) if "not a link" in f]
        assert escapes, "a symlinked document must be reported, not read"

    def test_an_in_tree_symlinked_companion_is_reported(self, tmp_path: Path) -> None:
        """Containment was not enough to enforce the rule DEC-070 states.

        An *in-tree* link resolves inside and compares equal, so
        `pkg/CLAUDE.md -> pkg/real.md` satisfied `contains()` while being exactly
        the shape that decision refuses. The PR body claimed symlinked
        companions were refused; until this, only escaping ones were.
        """
        directory = tmp_path / "pkg"
        directory.mkdir()
        (directory / "real.md").write_text("@AGENTS.md\n", encoding="utf-8")
        (directory / "CLAUDE.md").symlink_to(directory / "real.md")
        findings = companion_findings(directory, "pkg", CONFIG)
        assert "must be a regular file in this directory, not a link" in "".join(findings)

    def test_an_in_tree_symlinked_document_is_reported(self, tmp_path: Path) -> None:
        root = tmp_path / "repo"
        directory = root / "pkg"
        directory.mkdir(parents=True)
        for name in ("a.py", "b.py", "c.py"):
            (directory / name).write_text("x = 1\n", encoding="utf-8")
        (directory / "CLAUDE.md").write_text("@AGENTS.md\n", encoding="utf-8")
        (directory / "real.md").write_text(self._document_body(), encoding="utf-8")
        (directory / "AGENTS.md").symlink_to(directory / "real.md")
        config = AgentsDocConfig(additional_directories=("pkg",), min_documented_directories=1)
        assert [f for f in audit(root, config) if "not a link" in f]

    def test_a_symlinked_subagent_definition_is_reported_not_parsed(self, tmp_path: Path) -> None:
        """The directory being contained said nothing about its children: a
        linked `rogue.md` was read and parsed like any other definition, so the
        audit consumed external content through a door the directory check had
        already been added to guard."""
        outside = tmp_path / "outside"
        outside.mkdir()
        (outside / "rogue.md").write_text("no frontmatter at all\n", encoding="utf-8")
        root = tmp_path / "repo"
        (root / ".claude" / "agents").mkdir(parents=True)
        (root / ".claude" / "agents" / "rogue.md").symlink_to(outside / "rogue.md")
        findings = subagent_findings(root, AgentsDocConfig())
        assert "must be a regular file in this directory, not a link" in "".join(findings)
        assert "opening '---'" not in "".join(findings), "the external file must not be parsed"

    def test_an_escaping_configured_directory_is_reported_and_its_document_not_read(self, tmp_path: Path) -> None:
        """Reporting the escape was not the same as declining to read it. The
        external document was still found, parsed and counted toward the
        population floor, so the tree outside the checkout was being judged.
        """
        external = tmp_path / "external"
        external.mkdir()
        for name in ("a.py", "b.py", "c.py"):
            (external / name).write_text("x = 1\n", encoding="utf-8")
        (external / "AGENTS.md").write_text(self._document_body(), encoding="utf-8")
        (external / "CLAUDE.md").write_text("@AGENTS.md\n", encoding="utf-8")
        root = tmp_path / "repo"
        root.mkdir()
        (root / "linked").symlink_to(external)
        config = AgentsDocConfig(additional_directories=("linked",), min_documented_directories=1)
        findings = audit(root, config)
        assert any("resolves outside the checkout" in f for f in findings), findings
        assert any("the floor is 1" in f for f in findings), (
            "the external document must not count toward the population floor"
        )

    def test_paths_that_stay_inside_report_nothing(self, tmp_path: Path) -> None:
        root = self._repo(tmp_path / "repo")
        (root / "pkg").mkdir()
        config = AgentsDocConfig(additional_directories=("pkg",))
        assert configured_path_findings(root, config) == []
