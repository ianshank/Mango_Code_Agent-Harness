"""Shape contracts for the root GitHub workflows that no other gate reads.

`test_ci_gate_coverage.py` proves every policy-required *gate* is reached by
CI. This module pins the *install and environment* wiring around those gates,
which that suite deliberately does not read and which has drifted silently
before: no CI leg installed the LangGraph runtime, so every `langgraph`-marked
test skipped on every leg and the StateGraph package went unmeasured for
weeks (tech-debt-hardening-plan R-TDH-4).

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

import pytest

from harness.shared.tests._helpers import REPO
from harness.shared.tests.conftest import LANGGRAPH_DESELECT_ENV
from harness.shared.tests.test_ci_gate_coverage import _reported_check_names

pytestmark = pytest.mark.governance

WORKFLOW = REPO / ".github" / "workflows" / "python-package.yml"
LANGGRAPH_REQUIREMENTS = "requirements-langgraph.txt"
# The oldest interpreter in the matrix; langgraph declares Requires-Python >=3.10.
UNSUPPORTED_LEG = "3.9"


def job_sections(workflow_text: str) -> dict[str, str]:
    """Map job id -> the job's YAML body (text at deeper indentation)."""
    marker = "\njobs:\n"
    start = workflow_text.index(marker) + len(marker)
    body = workflow_text[start:]
    parts = re.split(r"\n  ([A-Za-z0-9_-]+):\n", "\n" + body)
    # parts[0] is any preamble; then alternating (job id, body).
    return {parts[i]: parts[i + 1] for i in range(1, len(parts) - 1, 2)}


@pytest.fixture(scope="module")
def jobs() -> dict[str, str]:
    sections = job_sections(WORKFLOW.read_text(encoding="utf-8"))
    assert {"build", "build-full"} <= set(sections), f"expected jobs missing: {sorted(sections)}"
    return sections


class TestLanggraphIsInstalledWhereItCanBe:
    def test_matrix_legs_install_the_runtime_except_the_unsupported_one(self, jobs: dict[str, str]) -> None:
        build = jobs["build"]
        guard = rf"if: matrix\.python-version != '{re.escape(UNSUPPORTED_LEG)}'"
        install = rf"run: .*{re.escape(LANGGRAPH_REQUIREMENTS)}"
        step = re.search(rf"{guard}\s*\n\s*{install}", build)
        assert step, (
            f"the `build` matrix must install {LANGGRAPH_REQUIREMENTS} on every leg except "
            f"{UNSUPPORTED_LEG}; without it the langgraph-marked suites skip everywhere"
        )

    def test_the_primary_leg_installs_the_runtime(self, jobs: dict[str, str]) -> None:
        assert LANGGRAPH_REQUIREMENTS in jobs["build-full"], (
            "`build-full` runs the regression tier and the full gate; it must install "
            f"{LANGGRAPH_REQUIREMENTS} so those tests run rather than skip"
        )

    def test_the_unsupported_leg_deselects_rather_than_skips(self, jobs: dict[str, str]) -> None:
        leg = re.escape(UNSUPPORTED_LEG)
        pattern = rf"{LANGGRAPH_DESELECT_ENV}: \$\{{\{{ matrix\.python-version == '{leg}' && '1' \|\| '' \}}\}}"
        assert re.search(pattern, jobs["build"]), (
            f"the {UNSUPPORTED_LEG} leg must set {LANGGRAPH_DESELECT_ENV}=1 so conftest deselects the "
            "langgraph-marked suites; a skip there would be an unwaived INV-2 violation"
        )

    def test_no_leg_installs_the_postgres_checkpointer(self) -> None:
        text = WORKFLOW.read_text(encoding="utf-8")
        assert "langgraph-postgres" not in text and "[langgraph]" not in text, (
            "install the library from requirements-langgraph.txt, not an extra that pulls "
            "langgraph-checkpoint-postgres and psycopg past pip-audit"
        )


class TestParserIsNotVacuous:
    def test_job_sections_finds_the_known_jobs(self, jobs: dict[str, str]) -> None:
        assert {"build", "build-full", "secrets", "audit"} <= set(jobs)

    def test_job_sections_on_a_minimal_document(self, tmp_path: Path) -> None:
        text = "name: x\non: push\njobs:\n  one:\n    runs-on: a\n  two:\n    runs-on: b\n"
        assert job_sections(text) == {"one": "    runs-on: a", "two": "    runs-on: b\n"}


# --- The committed ruleset export mirrors the workflow --------------------------
#
# `.github/rulesets/main.json` is what the owner imports to make CI a merge
# requirement on `main` (DEC-024). Its required-check contexts must be exactly
# the check names the workflow reports, derived the same way
# `test_ci_gate_coverage.py` derives them for `NEXT_STEPS.md`; a stale export
# would require a check GitHub never sends or leave a real gate unrequired.

RULESET = REPO / ".github" / "rulesets" / "main.json"


def _ruleset_rules(ruleset: dict) -> dict[str, dict]:
    return {rule["type"]: rule.get("parameters", {}) for rule in ruleset["rules"]}


class TestRulesetExportMirrorsTheWorkflow:
    @pytest.fixture(scope="class")
    def ruleset(self) -> dict:
        assert RULESET.is_file(), f"{RULESET} is missing; DEC-024 commits the export beside the workflow"
        return json.loads(RULESET.read_text(encoding="utf-8"))

    def test_required_contexts_are_exactly_the_reported_check_names(self, ruleset: dict) -> None:
        required = {
            check["context"] for check in _ruleset_rules(ruleset)["required_status_checks"]["required_status_checks"]
        }
        reported = _reported_check_names(WORKFLOW.read_text(encoding="utf-8"))
        assert required == reported, (
            f"ruleset requires {sorted(required - reported)} that CI never reports and omits "
            f"{sorted(reported - required)} that CI does report"
        )

    def test_the_ruleset_targets_the_default_branch_and_is_active(self, ruleset: dict) -> None:
        assert ruleset["target"] == "branch"
        assert ruleset["enforcement"] == "active"
        assert "~DEFAULT_BRANCH" in ruleset["conditions"]["ref_name"]["include"]

    def test_checks_are_strict_and_a_code_owner_review_is_required(self, ruleset: dict) -> None:
        rules = _ruleset_rules(ruleset)
        assert rules["required_status_checks"]["strict_required_status_checks_policy"] is True
        assert rules["pull_request"]["require_code_owner_review"] is True
        assert rules["pull_request"]["required_approving_review_count"] >= 1

    def test_nobody_can_bypass(self, ruleset: dict) -> None:
        assert ruleset.get("bypass_actors", []) == [], "a bypass actor is how #60 would merge again"
