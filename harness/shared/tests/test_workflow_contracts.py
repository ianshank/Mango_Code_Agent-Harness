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
}


def job_sections(workflow_text: str) -> dict[str, str]:
    """Map job id -> the job's YAML body (text at deeper indentation)."""
    marker = "\njobs:\n"
    start = workflow_text.index(marker) + len(marker)
    body = workflow_text[start:]
    parts = re.split(r"\n  ([A-Za-z0-9_-]+):\n", "\n" + body)
    # parts[0] is any preamble; then alternating (job id, body).
    return {parts[i]: parts[i + 1] for i in range(1, len(parts) - 1, 2)}


def uses_lines(workflow_text: str) -> list[tuple[str, int]]:
    """Every `uses: owner/action@vN` as (action, major)."""
    return [
        (m.group(1), int(m.group(2)))
        for m in re.finditer(r"^\s*(?:-\s*)?uses:\s*([A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+)@v(\d+)", workflow_text, re.M)
    ]


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


class TestRulesetExportMirrorsTheWorkflow:
    """R-TDH-1 / DEC-024: the committed export requires exactly the checks CI reports."""

    @pytest.fixture(scope="class")
    def ruleset(self) -> dict[str, Any]:
        assert RULESET.is_file(), f"{RULESET} is missing; DEC-024 commits the export beside the workflow"
        loaded = json.loads(RULESET.read_text(encoding="utf-8"))
        assert isinstance(loaded, dict), "the ruleset export must be a JSON object"
        return loaded

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

    def test_checks_are_strict_and_a_code_owner_review_is_required(self, ruleset: dict) -> None:
        rules = self._rules(ruleset)
        assert rules["required_status_checks"]["strict_required_status_checks_policy"] is True
        assert rules["pull_request"]["require_code_owner_review"] is True
        assert rules["pull_request"]["required_approving_review_count"] >= 1

    def test_nobody_can_bypass(self, ruleset: dict) -> None:
        assert ruleset.get("bypass_actors", []) == [], "a bypass actor is how #60 would merge again"


class TestParserIsNotVacuous:
    def test_job_sections_finds_the_known_jobs(self, jobs: dict[str, str]) -> None:
        assert {"build", "build-full", "secrets", "audit"} <= set(jobs)

    def test_job_sections_on_a_minimal_document(self) -> None:
        text = "name: x\non: push\njobs:\n  one:\n    runs-on: a\n  two:\n    runs-on: b\n"
        assert job_sections(text) == {"one": "    runs-on: a", "two": "    runs-on: b\n"}

    def test_uses_lines_reads_both_list_and_mapping_forms(self) -> None:
        text = "      - uses: actions/checkout@v5\n      - name: x\n        uses: actions/setup-go@v6\n"
        assert uses_lines(text) == [("actions/checkout", 5), ("actions/setup-go", 6)]


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

    def test_the_description_reaches_the_script_as_data(self, jobs: dict[str, str]) -> None:
        """A PR body is author-controlled text; it must never be interpolated into a shell."""
        job = jobs["build-full"]
        assert "PR_BODY: ${{ github.event.pull_request.body }}" in job
        assert 'printf \'%s\' "$PR_BODY"' in job
        assert "${{ github.event.pull_request.body }}" not in job.split("env:")[-1].split("run:")[-1]
