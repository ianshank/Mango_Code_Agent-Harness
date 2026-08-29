"""Behavioural tests for the plan defect rules.

Spec: ``docs/specs/plan-review-framework.md`` (R-PLR-1..R-PLR-7, C-PLR-4).

Every rule here was calibrated against the fifteen plans in this repository, and
three of them were wrong on first contact with that corpus. So each rule gets both
halves: a case it must catch, and a case it must *not*, because the failure mode
these rules actually exhibit is over-firing, not under-firing. A rule that reports
77% of a corpus is not a detector.
"""

from __future__ import annotations

import pytest

from harness.shared.plan_rules import (
    RULES,
    STRUCTURAL_RULES,
    check_plan,
    parse_plan,
    split_bullets,
    strip_code_spans,
    structural_findings,
    structural_line,
)

pytestmark = pytest.mark.governance

CONFORMING = """\
# Spec: a conforming plan

## Requirements

- R-EX-1: The thing MUST happen.

## Steps

1. Do it — produces `out.py`

## Files touched

- `out.py`

## Acceptance criteria

- [ ] AC-1: `out.py` exists — verified by `pytest -k test_out` · stage: `make ci` (R-EX-1)
- [ ] AC-2: A missing input is rejected with exit 1 (R-EX-1)
"""


def _classes(text: str, name: str = "probe.md") -> list[str]:
    return [f.defect_class for f in check_plan(text, name)]


def _swap(original: str, replacement: str) -> str:
    assert original in CONFORMING, "fixture drifted from the string being replaced"
    return CONFORMING.replace(original, replacement)


class TestTheConformingFixtureIsClean:
    """If the baseline reports anything, every mutation test below is meaningless."""

    def test_no_findings(self) -> None:
        assert check_plan(CONFORMING, "probe.md") == []


class TestUnfalsifiableAcceptance:
    """AC-1: a criterion naming no observable."""

    def test_prose_only_criterion_is_reported(self) -> None:
        text = _swap(
            "- [ ] AC-2: A missing input is rejected with exit 1 (R-EX-1)",
            "- [ ] AC-2: The behaviour is reasonable and the design is sound (R-EX-1)",
        )
        assert "UNFALSIFIABLE_ACCEPTANCE" in _classes(text)

    def test_a_criterion_naming_a_make_stage_is_not_reported(self) -> None:
        assert "UNFALSIFIABLE_ACCEPTANCE" not in _classes(CONFORMING)

    @pytest.mark.parametrize(
        "observable",
        ["`make ci`", "`out.py`", "pytest -k test_x", "exit 1", "`policy.json`"],
    )
    def test_each_observable_form_satisfies_the_grammar(self, observable: str) -> None:
        """The grammar's first version missed bare shell commands and reported 13
        false positives out of 20. Each accepted form is pinned so a future
        narrowing of the pattern fails here rather than in a reviewer's inbox."""
        text = _swap(
            "- [ ] AC-2: A missing input is rejected with exit 1 (R-EX-1)",
            f"- [ ] AC-2: Something is rejected, shown by {observable} (R-EX-1)",
        )
        assert "UNFALSIFIABLE_ACCEPTANCE" not in _classes(text)


class TestStageReachability:
    """AC-4: a criterion that names a check but hands it to a human."""

    def test_a_check_deferred_to_a_human_is_reported(self) -> None:
        text = _swap(
            "- [ ] AC-2: A missing input is rejected with exit 1 (R-EX-1)",
            "- [ ] AC-2: `git grep x` finds nothing, rejected — verified by inspection (R-EX-1)",
        )
        assert "STAGE_REACHABILITY" in _classes(text)

    def test_it_is_not_also_reported_as_unfalsifiable(self) -> None:
        """The criterion already carries an observable. Telling its author to add
        one would be the wrong remedy -- what is missing is the wiring."""
        text = _swap(
            "- [ ] AC-2: A missing input is rejected with exit 1 (R-EX-1)",
            "- [ ] AC-2: `git grep x` finds nothing, rejected — verified by inspection (R-EX-1)",
        )
        assert "UNFALSIFIABLE_ACCEPTANCE" not in _classes(text)

    def test_human_deferral_overrides_a_code_span(self) -> None:
        """AC-2 of the spec: the deferral wins even when the criterion is dense
        with backticks, because none of them is a stage that runs it."""
        text = _swap(
            "- [ ] AC-2: A missing input is rejected with exit 1 (R-EX-1)",
            "- [ ] AC-2: `a.py` and `b.py` and `c.py` differ, rejected — by inspection (R-EX-1)",
        )
        assert "STAGE_REACHABILITY" in _classes(text)

    def test_a_deferral_quoted_inside_a_code_span_is_not_a_finding(self) -> None:
        """C-PLR-4. This spec's own AC-2 quotes the phrase as test data; matching
        it there failed the very document that defines the rule."""
        text = _swap(
            "- [ ] AC-2: A missing input is rejected with exit 1 (R-EX-1)",
            "- [ ] AC-2: A criterion saying `verified by inspection` is rejected — "
            "verified by `pytest -k test_x` · stage: `make ci` (R-EX-1)",
        )
        assert "STAGE_REACHABILITY" not in _classes(text)


class TestMissingFailurePath:
    """AC-3: a plan whose criteria only describe success."""

    def test_success_only_criteria_are_reported(self) -> None:
        text = _swap(
            "- [ ] AC-2: A missing input is rejected with exit 1 (R-EX-1)",
            "- [ ] AC-2: `out.py` is importable — stage: `make ci` (R-EX-1)",
        )
        assert "MISSING_FAILURE_PATH" in _classes(text)

    def test_one_non_success_criterion_clears_it(self) -> None:
        assert "MISSING_FAILURE_PATH" not in _classes(CONFORMING)

    def test_the_word_fails_counts(self) -> None:
        """The vocabulary's first version had `failure` but not `fails`, and read
        "the gate fails when a dead pattern is present" as success-only. Four of
        its seven findings were that omission."""
        text = _swap(
            "- [ ] AC-2: A missing input is rejected with exit 1 (R-EX-1)",
            "- [ ] AC-2: `test_x` fails when the pattern is dead (R-EX-1)",
        )
        assert "MISSING_FAILURE_PATH" not in _classes(text)

    def test_a_plan_with_no_criteria_reports_nothing_here(self) -> None:
        """MISSING_SECTION is that plan's finding; two reports for one defect is
        the double-counting the defect-class dedup exists to prevent."""
        findings = check_plan("# Spec\n\n## Requirements\n\n- R-X-1: It MUST go.\n", "p.md")
        assert "MISSING_FAILURE_PATH" not in [f.defect_class for f in findings]


class TestOrphanRequirement:
    """AC-5: scoped to plans carrying this framework's sections."""

    def test_an_uncited_requirement_is_reported(self) -> None:
        text = _swap(
            "- R-EX-1: The thing MUST happen.",
            "- R-EX-1: The thing MUST happen.\n- R-EX-2: Another MUST happen.",
        )
        findings = [f for f in check_plan(text, "p.md") if f.defect_class == "ORPHAN_REQUIREMENT"]
        assert [f.ref for f in findings] == ["R-EX-2"]

    def test_a_plan_without_the_new_sections_is_exempt(self) -> None:
        """Applied to the older template this rule scored nine of eleven specs at
        100% orphaned -- measuring non-adoption of a convention the template never
        asked for, which is not a defect."""
        text = CONFORMING.replace("## Steps\n\n1. Do it — produces `out.py`\n\n", "")
        text = text.replace("## Files touched\n\n- `out.py`\n\n", "")
        text = text.replace(" (R-EX-1)", "")
        assert "ORPHAN_REQUIREMENT" not in _classes(text)

    def test_a_citation_in_the_validation_matrix_also_counts(self) -> None:
        text = _swap(
            "- [ ] AC-1: `out.py` exists — verified by `pytest -k test_out` · stage: `make ci` (R-EX-1)",
            "- [ ] AC-1: `out.py` exists — verified by `pytest -k test_out` · stage: `make ci`",
        ) + "\n## Validation matrix\n\n- `make ci` proves R-EX-1\n"
        assert "ORPHAN_REQUIREMENT" not in _classes(text)


class TestMigratedStructuralRules:
    """AC-8: the three rules that moved, and the defects fixed in the move."""

    @pytest.mark.parametrize("section", ["## Requirements", "## Acceptance criteria"])
    def test_a_missing_required_section_is_reported(self, section: str) -> None:
        assert "MISSING_SECTION" in _classes(CONFORMING.replace(section, "## Something else"))

    def test_a_normative_must_without_any_id_is_reported(self) -> None:
        text = _swap("- R-EX-1: The thing MUST happen.", "- The thing MUST happen.")
        assert "UNTRACEABLE_NORMATIVE" in _classes(text)

    def test_an_acceptance_bullet_containing_must_is_accepted(self) -> None:
        """The recorded defect: the rule matched only `[CR]-` IDs, so an `AC-*`
        bullet containing MUST could never satisfy it -- unsatisfiable for exactly
        the bullets the template tells authors to write."""
        text = _swap(
            "- [ ] AC-2: A missing input is rejected with exit 1 (R-EX-1)",
            "- [ ] AC-2: A missing input MUST be rejected with exit 1 (R-EX-1)",
        )
        assert "UNTRACEABLE_NORMATIVE" not in _classes(text)

    def test_an_unfilled_template_scaffold_is_reported(self) -> None:
        """The recorded defect: every structural rule passed on an untouched copy,
        because the placeholder IDs satisfy the ID patterns."""
        text = _swap("- R-EX-1: The thing MUST happen.", "- R-EXAMPLE-1: The thing MUST happen.")
        assert "UNFILLED_TEMPLATE" in _classes(text)

    @pytest.mark.parametrize("phrase", ["works correctly", "as expected", "appropriately"])
    def test_a_banned_phrase_used_as_prose_is_reported(self, phrase: str) -> None:
        text = _swap(
            "- [ ] AC-2: A missing input is rejected with exit 1 (R-EX-1)",
            f"- [ ] AC-2: The module {phrase} when rejected (R-EX-1)",
        )
        assert "UNFALSIFIABLE_ACCEPTANCE" in _classes(text)

    def test_banned_phrase_inside_a_code_span_is_not_a_finding(self) -> None:
        """AC-9 / C-PLR-4: the scan failed any document naming the phrases it bans
        -- including this framework's own spec, which is how it was found."""
        text = _swap(
            "- [ ] AC-2: A missing input is rejected with exit 1 (R-EX-1)",
            "- [ ] AC-2: A criterion saying `works correctly` is rejected — "
            "stage: `make ci` (R-EX-1)",
        )
        assert "UNFALSIFIABLE_ACCEPTANCE" not in _classes(text)


class TestUnparseablePlan:
    """AC-7: reported, never skipped."""

    def test_a_heading_with_no_parseable_criteria_is_a_finding(self) -> None:
        text = "# Spec\n\n## Requirements\n\n- R-X-1: It MUST go.\n\n## Acceptance criteria\n\nTBD.\n"
        assert "UNPARSEABLE_PLAN" in _classes(text)

    def test_a_plan_with_criteria_is_not_reported(self) -> None:
        assert "UNPARSEABLE_PLAN" not in _classes(CONFORMING)


class TestParsingHelpers:
    def test_a_wrapped_bullet_is_joined_with_its_continuation(self) -> None:
        """Criteria here routinely wrap; reading them line-by-line would report a
        finding for every observable that happened to fall on the second line."""
        joined = split_bullets("- [ ] AC-1: something\n      verified by `make ci`\n")
        assert len(joined) == 1
        assert "`make ci`" in joined[0]

    def test_code_spans_are_removed_not_emptied(self) -> None:
        assert "verified" not in strip_code_spans("a `verified by review` b")

    def test_sections_and_ids_are_parsed(self) -> None:
        plan = parse_plan(CONFORMING, "p.md")
        assert plan.declared == {"R-EX-1"}
        assert plan.carries_new_sections is True
        assert len(plan.acceptance) == 2


class TestTheRuleRegistryIsComplete:
    """A rule not in a registry is a rule nothing runs."""

    def test_structural_rules_are_a_subset_of_all_rules(self) -> None:
        assert set(STRUCTURAL_RULES) <= set(RULES)

    def test_structural_findings_uses_only_the_structural_tier(self) -> None:
        text = _swap(
            "- [ ] AC-2: A missing input is rejected with exit 1 (R-EX-1)",
            "- [ ] AC-2: The design is sound (R-EX-1)",
        )
        assert not [f for f in structural_findings(text, "p.md")
                    if f.defect_class == "UNFALSIFIABLE_ACCEPTANCE"]

    def test_every_rule_returns_findings_naming_its_own_class(self) -> None:
        plan = parse_plan("# x\n", "p.md")
        for rule in RULES:
            for finding in rule(plan):
                assert finding.defect_class and finding.remedy, rule.__name__


class TestMessageContract:
    """CI logs and test_validate_specs.py match on these exact strings."""

    def test_missing_section_line(self) -> None:
        finding = structural_findings("# x\n", "p.md")[0]
        assert structural_line(finding) == "p.md: missing ## Requirements"

    def test_untraceable_normative_line(self) -> None:
        text = _swap("- R-EX-1: The thing MUST happen.", "- The thing MUST happen.")
        line = next(structural_line(f) for f in structural_findings(text, "p.md")
                    if f.defect_class == "UNTRACEABLE_NORMATIVE")
        assert line.startswith("p.md: normative MUST has no requirement ID: ")

    def test_banned_phrase_line(self) -> None:
        line = next(structural_line(f) for f in structural_findings(
            "## Requirements\n## Acceptance criteria\n- it works correctly\n", "p.md"))
        assert line == "p.md: unfalsifiable acceptance language 'works correctly'"

    def test_render_names_class_ref_and_remedy(self) -> None:
        finding = structural_findings("# x\n", "p.md")[0]
        rendered = finding.render()
        assert "MISSING_SECTION" in rendered and "remedy:" in rendered
