"""Protected-path attestation and branch-protection report workflow contracts.

Split from ``test_workflow_contracts.py`` along the attestation-vs-ruleset
seam when that file sat at 692/700. Public test names are unchanged so
ticked spec selectors keep collecting.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from harness.shared.tests._workflow_parse import job_sections
from harness.shared.tests._workflow_paths import DRIFT_WORKFLOW, WORKFLOW, pull_request_branch_globs

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

    def test_stacked_prs_onto_the_cursor_agent_namespace_are_gated(self, workflow_text: str) -> None:
        """A PR whose base is `cursor/**` must still run `make ci`.

        Asserted against the parsed `pull_request.branches` list, not the
        comment. Cloud-agent branches here use `cursor/`; `claude/**` is the
        earlier namespace and must stay gated too. A comment-only
        `cursor/**` would leave this green — the same mutation that left
        `test_a_corrected_description_can_re_run_the_check` green on a
        comment-only `edited`.
        """
        globs = pull_request_branch_globs(workflow_text)
        assert "cursor/**" in globs, "a stacked PR onto the cursor/ agent namespace must still run make ci"
        assert "claude/**" in globs
        assert "main" in globs

    def test_pull_request_branch_globs_ignore_the_push_filter(self) -> None:
        """The helper must not return `on.push.branches` when the PR list is absent."""
        push_only = (
            "on:\n"
            "  push:\n"
            '    branches: ["main", "release/**"]\n'
            "  pull_request:\n"
            "    types: [opened]\n"
            "permissions:\n"
            "  contents: read\n"
        )
        both = (
            "on:\n"
            "  push:\n"
            '    branches: ["main", "release/**"]\n'
            "  pull_request:\n"
            '    branches: ["main", "cursor/**"]\n'
            "permissions:\n"
            "  contents: read\n"
        )
        assert pull_request_branch_globs(push_only) == frozenset()
        assert pull_request_branch_globs(both) == frozenset({"main", "cursor/**"})

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


class TestAttestationShaBinding:
    """R-SR-24 / R-RHI-3: the table binds to the PR head SHA, not the merge SHA."""

    def test_attestation_sha_is_read_from_the_pr_head(self, jobs: dict[str, str]) -> None:
        job = jobs["build-full"]
        step = job.split("Verify the protected-path attestation table")[-1].split("Run unified CI")[0]
        assert '["head"]["sha"]' in step
        assert "HEAD_SHA=" in step

    def test_attestation_sha_mismatch_fails(self, tmp_path: Path) -> None:
        from harness.shared.governance import attestation

        head, stale = "a" * 40, "b" * 40
        body = tmp_path / "pr.md"
        body.write_text(
            "## Protected-path attestation\n\n"
            f"Attested-head: {stale}\n\n"
            "| Protected path | Why |\n| --- | --- |\n| `Makefile` | x |\n",
            encoding="utf-8",
        )
        assert attestation._check(["Makefile"], body, head_sha=head) == 1

    def test_attestation_sha_match_passes(self, tmp_path: Path) -> None:
        from harness.shared.governance import attestation

        head = "a" * 40
        body = tmp_path / "pr.md"
        body.write_text(
            "## Protected-path attestation\n\n"
            f"Attested-head: {head}\n\n"
            "| Protected path | Why |\n| --- | --- |\n| `Makefile` | x |\n",
            encoding="utf-8",
        )
        assert attestation._check(["Makefile"], body, head_sha=head) == 0


class TestProtectionReport:
    def test_protection_report_queries_branch_rules(self, drift_text: str) -> None:
        jobs = job_sections(drift_text)
        assert "protection_report" in jobs
        body = jobs["protection_report"]
        assert "/rules/branches/main" in body
        assert "timeout-minutes:" in body
        assert "cat .github/rulesets/main.json" not in body
        assert "gh issue" in body
        assert "isinstance(data, list) and not data" in body

    def test_protection_report_does_not_fail_the_workflow_on_query_errors(self, drift_text: str) -> None:
        """Scheduled jobs notify; a GitHub API blip must not paint the run red."""
        body = job_sections(drift_text)["protection_report"]
        assert "set -euo pipefail" not in body
        assert "set +e" in body
        assert "curl -sSf" not in body
        assert 'echo "empty=0"' in body
        assert "|| gh issue create" in body
