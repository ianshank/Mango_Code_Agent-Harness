"""SHA-pin and Node-24 major contracts for the root GitHub workflows.

Split from ``test_workflow_contracts.py`` along the pin-vs-ruleset seam when
that file sat at 692/700. Public test names are unchanged so ticked spec
selectors keep collecting. Parser helpers live in ``_workflow_parse.py``.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from harness.shared.tests._workflow_parse import (
    NODE24_ACTION_MAJORS,
    job_sections,
    pinnable_uses,
    unpinned_uses,
    uses_lines,
)
from harness.shared.tests._workflow_paths import DEPENDABOT, DRIFT_WORKFLOW, WORKFLOW

pytestmark = pytest.mark.governance


@pytest.fixture(scope="module")
def workflow_text() -> str:
    return WORKFLOW.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def drift_text() -> str:
    return DRIFT_WORKFLOW.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def jobs(workflow_text: str) -> dict[str, str]:
    sections = job_sections(workflow_text)
    assert {"build", "build-full"} <= set(sections), f"expected jobs missing: {sorted(sections)}"
    return sections


class TestActionsRunOnNode24:
    """R-TDH-10: no action major that still runs on the deprecated Node 20 runtime."""

    @pytest.mark.parametrize("path", [WORKFLOW, DRIFT_WORKFLOW], ids=lambda p: p.name)
    def test_every_known_action_is_at_or_above_its_node24_major(self, path: Path) -> None:
        found = uses_lines(path.read_text(encoding="utf-8"))
        assert found, f"{path.name} uses no actions; the parser or the file is broken"
        below = [
            f"{action}@v{major} (< v{NODE24_ACTION_MAJORS[action]})"
            for action, major in found
            if action in NODE24_ACTION_MAJORS and major < NODE24_ACTION_MAJORS[action]
        ]
        assert not below, f"{path.name} uses action majors on the Node 20 runtime: {below}"

    @pytest.mark.parametrize("path", [WORKFLOW, DRIFT_WORKFLOW], ids=lambda p: p.name)
    def test_every_action_in_use_is_in_the_table(self, path: Path) -> None:
        """An action this table does not know is an action nobody checked."""
        in_use = {action for action, _ in uses_lines(path.read_text(encoding="utf-8"))}
        unknown = sorted(in_use - set(NODE24_ACTION_MAJORS))
        assert not unknown, f"add these to NODE24_ACTION_MAJORS after checking their runtime: {unknown}"

    @pytest.mark.parametrize("path", [WORKFLOW, DRIFT_WORKFLOW], ids=lambda p: p.name)
    def test_every_reference_is_sha_pinned(self, path: Path) -> None:
        """R-CQ-9: a tag is whatever its owner last pointed it at.

        `@v5` resolves at run time, so an upstream account compromise reaches
        this repository's runners with no commit here and nothing for the secret
        scan or the diff review to catch. A pin is a commit, and the version
        comment is what keeps the pin readable and what the Node 24 table below
        is enforced against.
        """
        offenders = unpinned_uses(path.read_text(encoding="utf-8"))
        assert not offenders, (
            f"{path.name} has {len(offenders)} reference(s) that are not `@<40-hex sha> # vX.Y.Z`: {offenders}"
        )

    @pytest.mark.parametrize(
        "source",
        [
            pytest.param(WORKFLOW, id=WORKFLOW.name),
            pytest.param(DRIFT_WORKFLOW, id=DRIFT_WORKFLOW.name),
            # Neither real workflow uses a local composite action, so on those two
            # alone this assertion cannot tell `pinnable_uses` from a raw count of
            # every `uses:` line — which is how the exemption came to be stated in
            # two places that disagreed. This case is the one that can.
            pytest.param(
                "jobs:\n"
                "  one:\n"
                "    steps:\n"
                "      - uses: ./.github/actions/setup\n"
                "      - uses: actions/checkout@fbc6f3992d24b796d5a048ff273f7fcc4a7b6c09 # v5.1.0\n"
                "      - uses: actions/checkout@v5\n",
                id="a-workflow-with-a-local-composite-action",
            ),
        ],
    )
    def test_the_pin_check_sees_every_reference_it_grades(self, source: Path | str) -> None:
        """Every pinnable `uses:` is either graded or reported — never neither.

        `uses_lines` returning only well-formed references is what lets the Node
        24 table stay simple, and is also how an unpinned action could vanish
        from every assertion at once. This pins the two halves to the whole,
        against the same set the exemption defines rather than a second count.
        """
        text = source.read_text(encoding="utf-8") if isinstance(source, Path) else source
        name = source.name if isinstance(source, Path) else "the probe"
        every = pinnable_uses(text)
        assert every, f"{name} has no pinnable `uses:` line; the parser or the file is broken"
        assert len(uses_lines(text)) + len(unpinned_uses(text)) == len(every), (
            f"{name}: {len(every)} pinnable `uses:` lines, but only "
            f"{len(uses_lines(text))} graded and {len(unpinned_uses(text))} reported"
        )

    @pytest.mark.parametrize(
        ("reference", "why"),
        [
            pytest.param("actions/checkout@v5", "a tag", id="a-bare-tag"),
            pytest.param(
                "actions/checkout@fbc6f3992d24b796d5a048ff273f7fcc4a7b6c09",
                "a SHA with no version comment",
                id="a-sha-with-no-comment",
            ),
            pytest.param(
                "actions/checkout@fbc6f3992d24b796d5a048ff273f7fcc4a7b6c09 # v5",
                "a comment that states no patch version",
                id="a-comment-without-a-full-version",
            ),
            # The three form cases below carry a valid version comment on
            # purpose. The first draft of the 39-hex case did not, so the
            # pattern rejected it for the missing comment and loosening `{40}`
            # to `+` left it passing — a case that cannot fail for the reason it
            # names pins nothing.
            #
            # Two of these were first written with reasons that were simply
            # untrue: git resolves an abbreviated object id, and resolves an
            # upper-case one, both verified against a real `git rev-parse`. The
            # rule they enforce is this repository's, not git's — one canonical
            # 40-hex lowercase form — and each case now says so, because a
            # failure message stating a false reason misleads whoever hits it.
            pytest.param(
                "actions/checkout@fbc6f3992d24b796d5a048ff273f7fcc4a7b6c0 # v5.1.0",
                "an abbreviated object id: git resolves one today, but an abbreviation is only "
                "unambiguous until the upstream repository grows a colliding prefix, and a pin "
                "has to stay resolvable for as long as the workflow does",
                id="a-short-sha",
            ),
            pytest.param(
                "actions/checkout@fbc6f3992d24b796d5a048ff273f7fcc4a7b6c099 # v5.1.0",
                "41 hex characters, which is not an object id at all and resolves to nothing",
                id="an-over-long-sha",
            ),
            pytest.param(
                "actions/checkout@FBC6F3992D24B796D5A048FF273F7FCC4A7B6C09 # v5.1.0",
                "an upper-case object id: git resolves it, but `git ls-remote` and Dependabot both "
                "emit lowercase, and one canonical spelling is what lets a reviewer compare pins by "
                "eye and keeps Dependabot's rewrite a one-line diff",
                id="an-upper-case-sha",
            ),
        ],
    )
    def test_a_workflow_that_is_not_pinned_is_a_finding(self, tmp_path: Path, reference: str, why: str) -> None:
        """Without these the pin check would pass on a file with no actions at all."""
        workflow = tmp_path / "probe.yml"
        workflow.write_text(f"jobs:\n  one:\n    steps:\n      - uses: {reference}\n", encoding="utf-8")
        text = workflow.read_text(encoding="utf-8")
        assert unpinned_uses(text) == [f"- uses: {reference}"], f"{why} must be reported"
        assert uses_lines(text) == [], f"{why} must not be graded as a pin"

    def test_a_local_composite_action_is_not_a_finding(self, tmp_path: Path) -> None:
        """A `./`-relative action is in this repository; there is no SHA to pin."""
        workflow = tmp_path / "probe.yml"
        workflow.write_text("jobs:\n  one:\n    steps:\n      - uses: ./.github/actions/setup\n", encoding="utf-8")
        assert unpinned_uses(workflow.read_text(encoding="utf-8")) == []

    def test_the_exemption_holds_when_a_workflow_actually_uses_one(self, tmp_path: Path) -> None:
        """The reconciliation and the exemption have to agree on the same set.

        Neither workflow has a local composite action today, so a reconciliation
        counting *every* `uses:` line while `unpinned_uses` skipped `./` ones
        passed anyway — and would have failed the first time either grew one.
        This is that workflow, written by hand.
        """
        workflow = tmp_path / "probe.yml"
        workflow.write_text(
            "jobs:\n"
            "  one:\n"
            "    steps:\n"
            "      - uses: ./.github/actions/setup\n"
            "      - uses: actions/checkout@fbc6f3992d24b796d5a048ff273f7fcc4a7b6c09 # v5.1.0\n"
            "      - uses: actions/checkout@v5\n",
            encoding="utf-8",
        )
        text = workflow.read_text(encoding="utf-8")
        assert pinnable_uses(text) == [
            "- uses: actions/checkout@fbc6f3992d24b796d5a048ff273f7fcc4a7b6c09 # v5.1.0",
            "- uses: actions/checkout@v5",
        ], "the local action must be excluded from the set the pin rule applies to"
        assert uses_lines(text) == [("actions/checkout", 5)]
        assert unpinned_uses(text) == ["- uses: actions/checkout@v5"]
        assert len(uses_lines(text)) + len(unpinned_uses(text)) == len(pinnable_uses(text))

    def test_dependabot_keeps_the_actions_moving(self) -> None:
        text = DEPENDABOT.read_text(encoding="utf-8")
        assert re.search(r'package-ecosystem:\s*"github-actions"', text), (
            ".github/dependabot.yml must declare the github-actions ecosystem"
        )


class TestParserIsNotVacuous:
    def test_job_sections_finds_the_known_jobs(self, jobs: dict[str, str]) -> None:
        assert {"build", "build-full", "secrets", "audit"} <= set(jobs)

    def test_job_sections_on_a_minimal_document(self) -> None:
        text = "name: x\non: push\njobs:\n  one:\n    runs-on: a\n  two:\n    runs-on: b\n"
        assert job_sections(text) == {"one": "    runs-on: a", "two": "    runs-on: b\n"}

    def test_uses_lines_reads_both_list_and_mapping_forms(self) -> None:
        text = (
            "      - uses: actions/checkout@fbc6f3992d24b796d5a048ff273f7fcc4a7b6c09 # v5.1.0\n"
            "      - name: x\n"
            "        uses: actions/setup-go@924ae3a1cded613372ab5595356fb5720e22ba16 # v6.5.0\n"
        )
        assert uses_lines(text) == [("actions/checkout", 5), ("actions/setup-go", 6)]
        assert unpinned_uses(text) == []
