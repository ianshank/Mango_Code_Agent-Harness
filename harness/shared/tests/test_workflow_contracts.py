"""Shape contracts for the root GitHub workflows that no other gate reads.

`test_ci_gate_coverage.py` proves every policy-required *gate* is reached by
CI. This module pins the *install, environment and runtime* wiring around
those gates, which that suite deliberately does not read and which has drifted
silently before: no CI leg installed the LangGraph runtime, so every
`langgraph`-marked test skipped on every leg and the StateGraph package went
unmeasured for weeks; every action ran on a Node 20 runtime the runners had
deprecated, with nothing but a warning in each job log to say so
(tech-debt-hardening-plan R-TDH-4, R-TDH-9, R-TDH-10, R-TDH-11).

SHA-pin / Node-24 majors live in ``test_workflow_pins.py``; attestation and
the scheduled protection report live in ``test_workflow_attestation.py``.
Parser helpers live in ``_workflow_parse.py`` and are re-exported here so
``from harness.shared.tests.test_workflow_contracts import job_sections``
keeps working.

Deliberately unprotected (unlike `test_ci_gate_coverage.py`) so it can grow
with each workflow change without an `infra-reviewed` round of its own; the
workflows it reads are protected, which is where the attestation belongs.

Parsing is textual, per job, matching how `test_ci_gate_coverage.py` reads the
same files: PyYAML is not a declared dependency of this repository and a gate
must not depend on a transitive one.
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from harness.shared.tests._ci_gate_helpers import _reported_check_names
from harness.shared.tests._workflow_parse import (
    ANY_USES,
    NODE24_ACTION_MAJORS,
    PINNED_USES,
    job_sections,
    pinnable_uses,
    unpinned_uses,
    uses_lines,
)
from harness.shared.tests._workflow_paths import (
    DRIFT_WORKFLOW,
    RULESET,
    WORKFLOW,
)
from harness.shared.tests.conftest import LANGGRAPH_DESELECT_ENV

pytestmark = pytest.mark.governance

__all__ = [
    "ANY_USES",
    "NODE24_ACTION_MAJORS",
    "PINNED_USES",
    "job_sections",
    "pinnable_uses",
    "unchosen_shape_reason",
    "unpinned_uses",
    "uses_lines",
]


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


class TestNoLegDeselectsLangGraph:
    """R-RHI-1 (DEC-064): every leg installs langgraph unconditionally now
    that the floor is >=3.10 (langgraph's own floor); no CI leg has a reason
    to set the deselect variable, so none should. The deselect mechanism
    itself (`_session_hooks.py`, `coverage.optional_extras`) stays live for an
    adopter fork that chooses not to install the extra at all -- this test
    only pins that this repository's own workflow does not (re)introduce a
    3.9-shaped carve-out."""

    def test_build_does_not_set_the_deselect_variable(self, jobs: dict[str, str]) -> None:
        assert LANGGRAPH_DESELECT_ENV not in jobs["build"], (
            "every build leg supports langgraph's own >=3.10 floor; setting "
            f"{LANGGRAPH_DESELECT_ENV} here would silently reintroduce a skip-shaped carve-out"
        )

    def test_build_full_does_not_set_the_deselect_variable(self, jobs: dict[str, str]) -> None:
        assert LANGGRAPH_DESELECT_ENV not in jobs["build-full"], (
            "build-full runs the regression tier with langgraph present; deselecting there "
            "would hide the very tests the lock exists to run"
        )


class TestNightlyDriftCatchesWhatBrokeMain:
    """R-TDH-11: the nightly loop typechecks, so a mypy break on main opens an issue."""

    def test_the_main_drift_loop_runs_lint(self, drift_text: str) -> None:
        loop = re.search(r"for target in ([^;]+); do", drift_text)
        assert loop, "the main-drift loop is gone or reshaped; this probe needs updating"
        targets = loop.group(1).split()
        assert "lint" in targets, f"main-drift runs {targets} but not `lint`"
        assert "coverage-python" in targets, "DEC-021's coverage check left the loop"


def _committed_export() -> dict[str, Any]:
    """The ruleset a maintainer would paste into GitHub, read off disk."""
    loaded = json.loads(RULESET.read_text(encoding="utf-8"))
    assert isinstance(loaded, dict), "the ruleset export must be a JSON object"
    return loaded


def unchosen_shape_reason(ruleset: dict[str, Any]) -> str | None:
    """Why ``ruleset`` is not the shape DEC-044 chose, or ``None`` if it is.

    R-CQ-1 offered three shapes a single-maintainer repository could merge
    under. DEC-044 took the second — no human-approval requirement, the nine
    status checks still required, nobody exempt — because the other two either
    hand one actor a key that opens the check rules too (a bypass actor is
    scoped to the ruleset, not to the review rule the maintainer actually
    cannot satisfy: that is how #60 merged red), or need a second account that
    does not exist. This function is the shape's definition; both the committed
    export and the negatives below are graded by it, so a shape that drifts
    back cannot pass by being merely well-formed.
    """
    if ruleset.get("bypass_actors", []):
        return (
            "a bypass actor exempts its holder from the required status checks too, "
            "not just from the review count; that is how #60 merged with every check red"
        )
    stated = ruleset.get("rules")
    if not isinstance(stated, list) or any(not isinstance(rule, dict) or "type" not in rule for rule in stated):
        return (
            f"the export states no readable `rules` list ({stated!r}); a shape whose rules "
            "cannot be read is a shape nobody has graded, so it is rejected rather than "
            "raised — the caller wants a reason, not a KeyError from inside its own grader"
        )
    rules = {rule["type"]: rule.get("parameters", {}) for rule in stated}
    pull_request = rules.get("pull_request", {})
    count = pull_request.get("required_approving_review_count")
    if count != 0:
        return (
            f"required_approving_review_count is {count!r}: the sole maintainer authors "
            "every pull request and GitHub does not accept an author's approval of their "
            "own, so any count above zero makes `main` unmergeable rather than reviewed"
        )
    if pull_request.get("require_code_owner_review") is not False:
        return (
            "require_code_owner_review is still set: .github/CODEOWNERS routes `*` to the "
            "one account that authors every pull request, so the rule asks for an approval "
            "no one is permitted to give"
        )
    return None


class TestRulesetExportMirrorsTheWorkflow:
    """R-TDH-1 / DEC-024: the committed export requires exactly the checks CI reports."""

    @pytest.fixture(scope="class")
    def ruleset(self) -> dict[str, Any]:
        assert RULESET.is_file(), f"{RULESET} is missing; DEC-024 commits the export beside the workflow"
        return _committed_export()

    @staticmethod
    def _rules(ruleset: dict[str, Any]) -> dict[str, dict[str, Any]]:
        return {rule["type"]: rule.get("parameters", {}) for rule in ruleset["rules"]}

    def test_required_contexts_are_exactly_the_reported_check_names(self, ruleset: dict, workflow_text: str) -> None:
        required = {c["context"] for c in self._rules(ruleset)["required_status_checks"]["required_status_checks"]}
        reported = _reported_check_names(workflow_text)
        assert required == reported, (
            f"ruleset requires {sorted(required - reported)} that CI never reports and omits "
            f"{sorted(reported - required)} that CI does report"
        )

    def test_the_ruleset_targets_the_default_branch_and_is_active(self, ruleset: dict) -> None:
        assert ruleset["target"] == "branch"
        assert ruleset["enforcement"] == "active"
        assert "~DEFAULT_BRANCH" in ruleset["conditions"]["ref_name"]["include"]

    def test_checks_are_strict(self, ruleset: dict) -> None:
        assert self._rules(ruleset)["required_status_checks"]["strict_required_status_checks_policy"] is True

    def test_nobody_can_bypass(self, ruleset: dict) -> None:
        assert unchosen_shape_reason(ruleset) is None


class TestTheOtherTwoShapesAreRejected:
    """R-CQ-1 named three shapes; a grader that accepts all three grades nothing.

    Each negative is the committed export edited on a `tmp_path` copy into one
    of the two shapes DEC-044 did not take, so the assertion above fails the
    moment the export drifts into either. Reading the copy back off disk rather
    than mutating the dict in memory is deliberate: the export is what a
    maintainer pastes into GitHub, so the round trip through JSON is the thing
    under test.
    """

    @staticmethod
    def _reshaped(tmp_path: Path, edit: Callable[[dict[str, Any]], None]) -> dict[str, Any]:
        loaded = _committed_export()
        edit(loaded)
        copy = tmp_path / "main.json"
        copy.write_text(json.dumps(loaded), encoding="utf-8")
        reloaded = json.loads(copy.read_text(encoding="utf-8"))
        assert isinstance(reloaded, dict)
        return reloaded

    def test_a_bypass_actor_for_the_admin_role_is_rejected(self, tmp_path: Path) -> None:
        def add_admin_bypass(ruleset: dict[str, Any]) -> None:
            ruleset["bypass_actors"] = [{"actor_id": 5, "actor_type": "RepositoryRole", "bypass_mode": "always"}]

        reason = unchosen_shape_reason(self._reshaped(tmp_path, add_admin_bypass))
        assert reason is not None and "bypass actor" in reason

    def test_keeping_the_review_count_for_a_second_account_is_rejected(self, tmp_path: Path) -> None:
        def restore_review_count(ruleset: dict[str, Any]) -> None:
            for rule in ruleset["rules"]:
                if rule["type"] == "pull_request":
                    rule["parameters"]["required_approving_review_count"] = 1

        reason = unchosen_shape_reason(self._reshaped(tmp_path, restore_review_count))
        assert reason is not None and "required_approving_review_count is 1" in reason

    def test_a_code_owner_review_requirement_is_rejected_on_its_own(self, tmp_path: Path) -> None:
        """Zeroing the count while leaving the code-owner rule set changes nothing.

        `*  @ianshank` in `.github/CODEOWNERS` means every pull request needs an
        approval from the account that wrote it, whatever the count says. A
        grader reading only the count would call that shape adopted.
        """

        def restore_code_owner_review(ruleset: dict[str, Any]) -> None:
            for rule in ruleset["rules"]:
                if rule["type"] == "pull_request":
                    rule["parameters"]["require_code_owner_review"] = True

        reason = unchosen_shape_reason(self._reshaped(tmp_path, restore_code_owner_review))
        assert reason is not None and "require_code_owner_review" in reason

    @pytest.mark.parametrize(
        "rules",
        [
            pytest.param(None, id="rules-key-absent"),
            pytest.param("pull_request", id="rules-is-a-string"),
            pytest.param([{"parameters": {}}], id="a-rule-has-no-type"),
        ],
    )
    def test_an_export_whose_rules_cannot_be_read_is_rejected_not_raised(self, tmp_path: Path, rules: Any) -> None:
        """A grader that raises instead of answering turns drift into a stack trace.

        `unchosen_shape_reason` is what `test_nobody_can_bypass` asserts on, so
        every way the export can be unreadable has to arrive as a reason. Each
        of these three raised `KeyError` or `TypeError` before.
        """

        def break_the_rules(ruleset: dict[str, Any]) -> None:
            if rules is None:
                del ruleset["rules"]
            else:
                ruleset["rules"] = rules

        reason = unchosen_shape_reason(self._reshaped(tmp_path, break_the_rules))
        assert reason is not None and "`rules`" in reason

    def test_the_committed_export_is_the_shape_that_passes(self) -> None:
        """Without this the four negatives above could all pass on a broken grader."""
        assert unchosen_shape_reason(_committed_export()) is None
