"""Shape contracts for the root GitHub workflows that no other gate reads.

`test_ci_gate_coverage.py` proves every policy-required *gate* is reached by
CI. This module pins the *install, environment and runtime* wiring around
those gates, which that suite deliberately does not read and which has drifted
silently before: no CI leg installed the LangGraph runtime, so every
`langgraph`-marked test skipped on every leg and the StateGraph package went
unmeasured for weeks; every action ran on a Node 20 runtime the runners had
deprecated, with nothing but a warning in each job log to say so
(tech-debt-hardening-plan R-TDH-4, R-TDH-9, R-TDH-10, R-TDH-11).

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
from harness.shared.tests._helpers import REPO
from harness.shared.tests.conftest import LANGGRAPH_DESELECT_ENV

pytestmark = pytest.mark.governance

WORKFLOW_DIR = REPO / ".github" / "workflows"
WORKFLOW = WORKFLOW_DIR / "python-package.yml"
DRIFT_WORKFLOW = WORKFLOW_DIR / "scheduled-drift.yml"
DEPENDABOT = REPO / ".github" / "dependabot.yml"
RULESET = REPO / ".github" / "rulesets" / "main.json"
LOCK = REPO / "requirements-lock.txt"
LOCK_NAME = LOCK.name
# The oldest interpreter in the matrix; langgraph declares Requires-Python >=3.10.
UNSUPPORTED_LEG = "3.9"

#: Lowest major of each action whose runtime is Node 24, verified against each
#: action's `action.yml` (`runs.using: node24`) on 2026-09-02. A `uses:` below
#: these majors runs on the Node 20 runtime GitHub deprecated on its runners.
NODE24_ACTION_MAJORS: dict[str, int] = {
    "actions/checkout": 5,
    "actions/setup-python": 6,
    "actions/setup-node": 5,
    "actions/setup-go": 6,
    "pnpm/action-setup": 5,
    # Not in use yet; R-CQ-23's build caching is the reference that will need it.
    "actions/cache": 4,
}

#: The only `uses:` form this repository accepts (R-CQ-9): a full 40-hex commit
#: SHA followed by the version comment Dependabot writes. A tag is a moving
#: reference — `@v5` is whatever the owner last pointed `v5` at, so an account
#: compromise upstream reaches this repository's runners without a commit here.
#: The comment is not decoration: a bare SHA says nothing about what it is, and
#: `NODE24_ACTION_MAJORS` is enforced against the major *it* states.
PINNED_USES = re.compile(
    r"^\s*(?:-\s*)?uses:\s*"
    r"(?P<action>[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+)"
    r"@(?P<sha>[0-9a-f]{40})"
    r"\s+#\s*v(?P<major>\d+)\.(?P<minor>\d+)\.(?P<patch>\d+)\s*$",
    re.M,
)
#: Any `uses:` at all, so a reference the strict form rejects is reported rather
#: than skipped. A `./`-relative composite action lives in this repository and
#: has no SHA to pin, so it is not a finding.
ANY_USES = re.compile(r"^\s*(?:-\s*)?uses:\s*(?P<reference>\S.*?)\s*$")


def job_sections(workflow_text: str) -> dict[str, str]:
    """Map job id -> the job's YAML body (text at deeper indentation)."""
    marker = "\njobs:\n"
    start = workflow_text.index(marker) + len(marker)
    body = workflow_text[start:]
    parts = re.split(r"\n  ([A-Za-z0-9_-]+):\n", "\n" + body)
    # parts[0] is any preamble; then alternating (job id, body).
    return {parts[i]: parts[i + 1] for i in range(1, len(parts) - 1, 2)}


def uses_lines(workflow_text: str) -> list[tuple[str, int]]:
    """Every SHA-pinned `uses:` as (action, major), the major read off its comment.

    Only well-formed references are returned. Anything the strict form rejects
    is `unpinned_uses`' to report — splitting them keeps a malformed reference
    from arriving here as a silently missing row, which is how an unpinned
    action would otherwise pass the Node 24 table by being invisible to it.
    """
    return [(m.group("action"), int(m.group("major"))) for m in PINNED_USES.finditer(workflow_text)]


def pinnable_uses(workflow_text: str) -> list[str]:
    """Every `uses:` line the pin rule applies to, stripped.

    The `./`-relative exemption lives here and nowhere else. It was duplicated
    once — `unpinned_uses` skipped local composite actions while the test that
    reconciles the graded and reported sets counted them — which passed only
    because neither workflow uses one, and would have failed the first time
    either did.
    """
    lines = []
    for line in workflow_text.splitlines():
        reference = ANY_USES.match(line)
        if reference is None or reference.group("reference").startswith("./"):
            continue
        lines.append(line.strip())
    return lines


def unpinned_uses(workflow_text: str) -> list[str]:
    """Every `uses:` line that is not a SHA pin with a version comment."""
    return [line for line in pinnable_uses(workflow_text) if not PINNED_USES.match(line)]


def pip_install_lines(workflow_text: str) -> list[str]:
    return [line.strip() for line in workflow_text.splitlines() if re.match(r"^\s*python -m pip install ", line)]


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


class TestDependenciesComeFromTheLock:
    """R-TDH-9: what CI installs is what the committed lock says, on every leg."""

    @pytest.mark.parametrize("path", [WORKFLOW, DRIFT_WORKFLOW], ids=lambda p: p.name)
    def test_every_requirements_install_reads_the_lock(self, path: Path) -> None:
        installs = [line for line in pip_install_lines(path.read_text(encoding="utf-8")) if " -r " in line]
        assert installs, f"{path.name} installs no requirements file at all"
        offenders = [line for line in installs if LOCK_NAME not in line]
        assert not offenders, (
            f"{path.name} installs from an unlocked requirements file: {offenders}. "
            f"Install from {LOCK_NAME} so an upstream release cannot change what CI runs."
        )

    @pytest.mark.parametrize("path", [WORKFLOW, DRIFT_WORKFLOW], ids=lambda p: p.name)
    def test_the_editable_install_does_not_resolve_dependencies(self, path: Path) -> None:
        editable = [line for line in pip_install_lines(path.read_text(encoding="utf-8")) if " -e " in line]
        assert editable, f"{path.name} never installs the project itself"
        assert all("--no-deps" in line for line in editable), (
            f"`pip install -e .` without --no-deps re-resolves the project's ranges and can "
            f"override the lock: {editable}"
        )

    @pytest.mark.parametrize("path", [WORKFLOW, DRIFT_WORKFLOW], ids=lambda p: p.name)
    def test_pip_cache_keys_follow_the_lock(self, path: Path) -> None:
        keys = re.findall(r"cache-dependency-path:\s*(\S+)", path.read_text(encoding="utf-8"))
        python_keys = [k for k in keys if k.startswith("requirements")]
        assert python_keys, f"{path.name} declares no pip cache key"
        assert set(python_keys) == {LOCK_NAME}, f"pip cache keyed on something other than the lock: {python_keys}"

    def test_the_lock_carries_langgraph_behind_a_marker(self) -> None:
        """The 3.9 leg must not receive langgraph; every other leg must."""
        text = LOCK.read_text(encoding="utf-8")
        entry = re.search(r"^langgraph==[^\s;]+ ; (.+)$", text, re.M)
        assert entry, f"{LOCK_NAME} pins no langgraph; the StateGraph suites would skip everywhere again"
        assert re.search(r"python_full_version >= '3\.10'", entry.group(1)), (
            f"langgraph's marker in {LOCK_NAME} is {entry.group(1)!r}; it must exclude {UNSUPPORTED_LEG}"
        )

    def test_the_lock_does_not_carry_the_postgres_checkpointer(self) -> None:
        text = LOCK.read_text(encoding="utf-8")
        assert not re.search(r"^(psycopg|langgraph-checkpoint-postgres)==", text, re.M), (
            "the Postgres checkpointer is its own extra; nothing under harness/ imports it "
            "and pip-audit would scan a driver no gate exercises"
        )

    def test_the_lock_is_universal_not_interpreter_specific(self) -> None:
        text = LOCK.read_text(encoding="utf-8")
        assert "--universal" in text.splitlines()[1], (
            "the header must show the lock was compiled with --universal; a per-interpreter "
            "compile evaluates the markers away and cannot serve the 3.9/3.10/3.12 matrix"
        )


class TestTheUnsupportedLegDeselectsRatherThanSkips:
    """R-TDH-4: no skip on the leg that cannot install langgraph."""

    def test_the_deselect_variable_is_set_only_on_the_unsupported_leg(self, jobs: dict[str, str]) -> None:
        leg = re.escape(UNSUPPORTED_LEG)
        pattern = rf"{LANGGRAPH_DESELECT_ENV}: \$\{{\{{ matrix\.python-version == '{leg}' && '1' \|\| '' \}}\}}"
        assert re.search(pattern, jobs["build"]), (
            f"the {UNSUPPORTED_LEG} leg must set {LANGGRAPH_DESELECT_ENV}=1 so conftest deselects the "
            "langgraph-marked suites; a skip there would be an unwaived INV-2 violation"
        )

    def test_the_primary_leg_does_not_deselect(self, jobs: dict[str, str]) -> None:
        assert LANGGRAPH_DESELECT_ENV not in jobs["build-full"], (
            "build-full runs the regression tier with langgraph present; deselecting there "
            "would hide the very tests the lock exists to run"
        )


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


class TestTheAttestationCheckRunsWhereItCanBeRead:
    """DEC-038: a verified table has to reach the reviewer *before* they attest.

    The step was first written after `make ci`, which was wrong in a way no
    assertion would have reported: `make ci` ends at the protected-path gate on
    any PR lacking `infra-reviewed`, which is every PR this check exists for, so
    the step would never have executed on one. Green CI would have meant the
    table was unchecked. Both halves of the placement are pinned here.
    """

    def test_it_precedes_the_gate_that_stops_without_the_label(self, jobs: dict[str, str]) -> None:
        job = jobs["build-full"]
        check = job.find("make attestation-check")
        gate = job.find("run: make ci")
        assert check != -1, "build-full must verify the attestation table"
        assert gate != -1, "build-full must still run the unified gate"
        assert check < gate, (
            "the attestation check must run before `make ci`: that target ends at the "
            "protected-path gate whenever `infra-reviewed` is absent, so a step after it "
            "never runs on the PRs the check is for"
        )

    def test_it_is_not_gated_on_the_attestation_it_verifies(self, jobs: dict[str, str]) -> None:
        step = jobs["build-full"].split("make attestation-check")[0].rsplit("- name:", 1)[-1]
        assert "ALLOW_GITHUB_CHANGES" not in step, (
            "deriving the step's own condition from the label would make it verify the table "
            "only once the reviewer had already trusted it"
        )

    def test_the_description_is_read_live_not_from_the_event_payload(self, jobs: dict[str, str]) -> None:
        """The payload's `body` is a snapshot; judging it made the check unclearable.

        On its second real run the step failed against a description that had
        already been corrected, and no re-run could have cleared it: "Re-run
        failed jobs" replays the original event. Reading the description from the
        API is what makes the check reflect the PR as it is now, so the payload
        field must not come back.
        """
        job = jobs["build-full"]
        assert "${{ github.event.pull_request.body }}" not in job, (
            "the event payload's body is a snapshot taken when the run was queued; "
            "fetch the description from the API instead"
        )
        assert "/pulls/$PR_NUMBER" in job

    def test_a_corrected_description_can_re_run_the_check(self, workflow_text: str) -> None:
        """Without `edited`, clearing the check would require an otherwise pointless commit.

        Asserted against the parsed `types:` list, not the surrounding text. The
        first version of this test searched the trigger section for the word
        `edited` and passed on the *comment* that explains why `edited` is there
        — so deleting the type itself left it green. Caught by mutating the
        workflow rather than by reading the assertion.
        """
        match = re.search(r"^\s*types:\s*\[([^\]]*)\]", workflow_text, re.M)
        assert match is not None, "the pull_request trigger declares no explicit types"
        types = {entry.strip() for entry in match.group(1).split(",")}
        assert "edited" in types, "a corrected PR description must be able to re-run the attestation check"
        assert "labeled" in types, "applying `infra-reviewed` must be able to re-run CI"

    def test_the_description_reaches_the_script_as_data(self, jobs: dict[str, str]) -> None:
        """A PR body is author-controlled text; it must never reach the shell as code."""
        job = jobs["build-full"]
        assert 'make attestation-check FILE="$RUNNER_TEMP/pr-body.md"' in job
        assert "set -euo pipefail" in job, (
            "a failed fetch under plain `bash -e` leaves an empty file, which the gate would "
            "report as a missing table rather than a broken request"
        )

    def test_the_pull_request_read_scope_is_scoped_to_the_job_that_needs_it(
        self, workflow_text: str, jobs: dict[str, str]
    ) -> None:
        """Least privilege: only `build-full` reads pull requests."""
        assert "pull-requests: read" in jobs["build-full"]
        assert "pull-requests" not in workflow_text.split("jobs:")[0], (
            "the scope belongs on the one job that fetches the description, not workflow-wide"
        )
