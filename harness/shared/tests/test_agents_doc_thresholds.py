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

The companion-body rule is the same story told with whitespace: it was
asserted against `"@AGENTS.md\n\nAlso, some rules."` -- prose, nowhere near the
line -- while `strip()` quietly accepted `"   @AGENTS.md"` and
`"\n@AGENTS.md\n\n"`, which R-ADOC-3 calls content.

The exclusion lists are here for the same reason. ``MERMAID_NON_NODES`` and the
``%%``-comment skip could both be deleted outright with 198 tests still green,
because every diagram in the suite is multi-line and uncommented and so never
reaches either.
"""

from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

import pytest

from harness.shared.agents_doc import (
    audit,
    companion_findings,
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


class TestTheCompanionBodyIsExact:
    """R-ADOC-3 holds the *entire* body to the configured import."""

    @pytest.mark.parametrize(
        "body",
        [
            "\n@AGENTS.md",
            "@AGENTS.md\n\n",
            "   @AGENTS.md",
            "\n\n@AGENTS.md\n\n",
            "\t@AGENTS.md",
        ],
        ids=["leading-blank", "trailing-blank", "leading-spaces", "surrounded", "leading-tab"],
    )
    def test_whitespace_around_the_import_is_still_content(self, tmp_path: Path, body: str) -> None:
        """`strip()` normalised every one of these to the import and accepted
        it, although R-ADOC-3 holds the *entire* body to the import. Leading
        whitespace and extra blank lines are content, and all 24 companions in
        this repository are byte-exactly `@AGENTS.md` plus one newline, so
        nothing legitimate relies on the laxity."""
        write_document(tmp_path / "pkg", companion=body)
        assert "expected '@AGENTS.md'" in "".join(companion_findings(tmp_path / "pkg", "pkg", CONFIG))

    @pytest.mark.parametrize("body", ["@AGENTS.md", "@AGENTS.md\r"], ids=["lf", "crlf"])
    def test_one_trailing_terminator_is_accepted_in_either_convention(self, tmp_path: Path, body: str) -> None:
        """The control, and a pin on *why* CRLF works. `write_document` appends
        the newline, so these land as `"@AGENTS.md\n"` and `"@AGENTS.md\r\n"`,
        and `Path.read_text`'s universal-newline translation collapses the second
        to the first before any comparison. I first wrote an explicit `\r` arm
        for it; its mutation could not be made to fail, because the arm was
        unreachable. This test is what makes the dependency visible — switch
        `read_utf8` to `read_bytes().decode()` and the CRLF case starts failing
        the gate on exactly the Windows checkouts DEC-061 exists for."""
        write_document(tmp_path / "pkg", companion=body)
        assert companion_findings(tmp_path / "pkg", "pkg", CONFIG) == []


class TestTheReviewedDateMeansTheSameOnEveryInterpreter:
    """``date.fromisoformat`` widened in 3.11, so the gate's verdict moved with it.

    Before 3.11 it accepted only ``YYYY-MM-DD``; from 3.11 it takes most of
    ISO 8601, including the basic form and week dates. This repository's floor
    is 3.10 and CI runs 3.10, 3.12 and 3.14, so ``**Reviewed:** 20260919`` was
    a blocking finding on one leg and silent on the other two -- a gate whose
    accepted set depended on which interpreter happened to run it. The rule is
    now pinned to the canonical form on every version.
    """

    # Each is accepted by 3.11+ and rejected by the 3.10 floor, which is the
    # whole defect; `2026-9-19` and ordinal dates are rejected by both and so
    # prove nothing here.
    @pytest.mark.parametrize("value", ["20260919", "2026-W38-6", "2026W386"])
    def test_a_form_only_newer_interpreters_accept_is_reported(self, tmp_path: Path, value: str) -> None:
        write_document(tmp_path / "pkg", reviewed=value)
        assert "not a YYYY-MM-DD date" in "".join(findings_for(tmp_path / "pkg"))

    def test_the_canonical_form_is_still_accepted(self, tmp_path: Path) -> None:
        """The negative control: pinning the format must not reject the real one."""
        write_document(tmp_path / "pkg", reviewed="2026-09-19")
        assert "not a YYYY-MM-DD date" not in "".join(findings_for(tmp_path / "pkg"))

    def test_the_shape_alone_is_not_enough(self, tmp_path: Path) -> None:
        """A regex would accept the 31st of February; the calendar still decides."""
        write_document(tmp_path / "pkg", reviewed="2026-02-31")
        assert "not a YYYY-MM-DD date" in "".join(findings_for(tmp_path / "pkg"))

    @pytest.mark.parametrize("value", ["20260101", "2026-W01-1"])
    def test_staleness_leaves_such_a_form_to_the_blocking_rule(self, tmp_path: Path, value: str) -> None:
        """The report reads the same date, so it drifted the same way: on 3.11+ it
        aged a document the 3.10 leg refused to parse at all."""
        write_document(tmp_path / "pkg", reviewed=value)
        assert stale_documents(tmp_path, CONFIG, 90, date(2026, 10, 1)) == []

    def test_the_stdlib_divergence_the_pin_exists_for(self) -> None:
        """Asserted, not left in a comment, so the pin is a fix and not a style
        choice (the v2.2.4 precedent for stdlib-dependent behaviour). It holds on
        every leg of the matrix, and keeps holding once the floor passes 3.10 --
        `fromisoformat` does not narrow again, so a week date stays a trap.
        """
        try:
            date.fromisoformat("20260919")
        except ValueError:
            assert sys.version_info < (3, 11), "3.11+ accepts the basic form"
        else:
            assert sys.version_info >= (3, 11), "before 3.11 the basic form raises"
