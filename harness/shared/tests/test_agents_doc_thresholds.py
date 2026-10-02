"""Every threshold at its boundary, and every exclusion list actually excluding.

A mutation pass over the `agents_doc` suites found nine surviving mutants, and
they shared one shape: the rules were tested far from the line they draw. A
155-line document against a 150-line budget proves the budget fires somewhere
between 150 and 155; it does not prove it fires at 151. Adding one to
``max_lines``, ``max_diagram_nodes``, ``min_waiver_reason_chars`` and the
staleness horizon changed no verdict in the whole suite.

The convention already existed -- ``max_diagrams``, ``min_scope_names``,
``max_key_files`` and ``min_documented_directories`` were each tested at their
boundary and each killed the same mutation. It was applied unevenly, which is
the only reason this module exists: one place where a threshold is pinned from
both sides, so a new one has an obvious home and an obvious shape.

The exclusion lists are here for the same reason. ``MERMAID_NON_NODES`` and the
``%%``-comment skip could both be deleted outright with 198 tests still green,
because every diagram in the suite is multi-line and uncommented and so never
reaches either.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from harness.shared.agents_doc import (
    audit,
    declared_nodes,
    discover_source_directories,
    mermaid_findings,
    stale_documents,
    waiver_findings,
)
from harness.shared.agents_doc_policy import AgentsDocConfig
from harness.shared.tests._agents_doc_helpers import CONFIG, findings_for, write_document

pytestmark = pytest.mark.governance

#: `write_document` with no filler. Measured rather than written down, so a
#: change to the template cannot silently move every boundary case below.
BASE_DOCUMENT_LINES = 21


def document_of_exactly(directory: Path, lines: int) -> Path:
    """A document that is exactly `lines` long, or an error saying why not."""
    path = write_document(directory)
    base = len(path.read_text(encoding="utf-8").splitlines())
    assert base == BASE_DOCUMENT_LINES, f"the template is now {base} lines; update BASE_DOCUMENT_LINES"
    assert lines >= base, f"cannot build a {lines}-line document from a {base}-line template"
    return write_document(directory, extra_lines=lines - base)


def diagram_with(nodes: int) -> str:
    """A flowchart declaring exactly `nodes` distinct identifiers."""
    edges = "\n".join(f'  N{index}["n"] --> N{index + 1}["n"]' for index in range(nodes - 1))
    body = f"flowchart LR\n{edges}\n"
    assert len(declared_nodes(body, CONFIG)) == nodes, "the generator does not declare what it claims"
    return body


class TestTheLineBudgetFiresAtItsBoundary:
    """`max_lines` is the one threshold with a measured basis -- >200 lines
    reduces instruction adherence -- so it is also the one where "somewhere
    around there" is not good enough."""

    def test_a_document_at_exactly_the_budget_is_accepted(self, tmp_path: Path) -> None:
        document_of_exactly(tmp_path / "pkg", CONFIG.max_lines)
        assert not [finding for finding in findings_for(tmp_path / "pkg") if "budget" in finding]

    def test_one_line_over_the_budget_is_reported(self, tmp_path: Path) -> None:
        document_of_exactly(tmp_path / "pkg", CONFIG.max_lines + 1)
        assert any("exceeds the" in finding for finding in findings_for(tmp_path / "pkg"))


class TestTheNodeCapFiresAtItsBoundary:
    def test_a_diagram_at_exactly_the_cap_is_accepted(self) -> None:
        assert mermaid_findings([diagram_with(CONFIG.max_diagram_nodes)], CONFIG) == []

    def test_one_node_over_the_cap_is_reported(self) -> None:
        findings = mermaid_findings([diagram_with(CONFIG.max_diagram_nodes + 1)], CONFIG)
        assert any("stays legible" in finding for finding in findings), findings


class TestTheWaiverReasonFloorFiresAtItsBoundary:
    @staticmethod
    def _findings(reason: str) -> list[str]:
        return waiver_findings(Path("."), AgentsDocConfig(waived_directories={"harness": reason}))

    def test_a_reason_of_exactly_the_floor_is_accepted(self) -> None:
        assert self._findings("r" * CONFIG.min_waiver_reason_chars) == []

    def test_one_character_short_is_reported(self) -> None:
        findings = self._findings("r" * (CONFIG.min_waiver_reason_chars - 1))
        assert any("characters" in finding for finding in findings), findings

    def test_whitespace_does_not_count_toward_the_floor(self) -> None:
        """The `.strip()` could be deleted and nothing noticed: a reason of fifty
        spaces is forty characters long and says nothing, which is the exemption
        granted without a reason that this floor exists to refuse."""
        findings = self._findings(" " * (CONFIG.min_waiver_reason_chars + 10))
        assert any("is 0 characters" in finding for finding in findings), findings


class TestTheStalenessHorizonFiresAtItsBoundary:
    """`age > max_age_days`, so the horizon day itself is fresh. Asserted from
    both sides because an off-by-one here files a weekly issue a day early or
    swallows one a day late, and neither is visible in a passing suite."""

    @staticmethod
    def _age(tmp_path: Path, days: int) -> list[tuple[str, str, int]]:
        reviewed = date(2026, 1, 1)
        write_document(tmp_path / "pkg", reviewed=reviewed.isoformat())
        config = AgentsDocConfig(additional_directories=("pkg",))
        return stale_documents(tmp_path, config, 90, date.fromordinal(reviewed.toordinal() + days))

    def test_a_document_exactly_at_the_horizon_is_not_stale(self, tmp_path: Path) -> None:
        assert self._age(tmp_path, 90) == []

    def test_one_day_past_the_horizon_is_stale(self, tmp_path: Path) -> None:
        assert self._age(tmp_path, 91) == [("pkg", "2026-01-01", 91)]


class TestDiagramExclusionsActuallyExclude:
    def test_syntax_keywords_on_a_single_line_diagram_are_not_nodes(self) -> None:
        """The suite's diagrams are all multi-line, and a line carrying no edge
        is skipped before the exclusion list is consulted -- so deleting
        `MERMAID_NON_NODES` and `diagram_types` from the filter left every test
        green. Single-line mermaid is where the filter is the only thing
        standing between a keyword and the node cap."""
        assert declared_nodes("graph LR; A-->B\n", CONFIG) == {"A--", "B"}

    def test_a_commented_out_edge_declares_no_nodes(self) -> None:
        """`%%` is a mermaid comment. Without the skip, a diagram documenting
        its own alternatives in comments would count them against the cap."""
        body = 'flowchart LR\n  %% Zebra --> Quagga\n  A["a"] --> B["b"]\n'
        assert declared_nodes(body, CONFIG) == {"A", "B"}


class TestTheAuditReadsTheRealPolicy:
    def test_an_audit_given_no_config_resolves_the_repositorys_own(self, tmp_path: Path) -> None:
        """Replaces a test that asserted `audit(tmp_path) != []`. An empty tree
        trips the population floor under *any* config, so that assertion held
        with `load_config()` swapped for `AgentsDocConfig()` -- the gate ceasing
        to read `governance-policy.json` at all. This asserts a finding only the
        real policy can produce: the built-in defaults declare no waivers, and
        this repository's policy declares five, none of which exist under an
        empty root."""
        findings = audit(tmp_path)
        assert any("waived but the directory does not exist" in finding for finding in findings), findings
        assert not any(
            "waived but the directory does not exist" in finding for finding in audit(tmp_path, AgentsDocConfig())
        ), "the control: built-in defaults must not produce the finding above"


class TestTheRepositoryRootNeverOwesADocument:
    def test_a_root_holding_enough_sources_is_still_not_discovered(self, tmp_path: Path) -> None:
        """Instructions for the root are `CLAUDE.md`, not this gate. The guard is
        inert on this checkout -- the root carries two first-party sources
        against a floor of three -- so removing it changed no verdict, and a
        third root-level module would have made the gate demand a root
        `AGENTS.md` with nothing to catch it."""
        for name in ("a.py", "b.py", "c.py"):
            (tmp_path / name).write_text("x = 1\n", encoding="utf-8")
        assert discover_source_directories(tmp_path, CONFIG) == []
