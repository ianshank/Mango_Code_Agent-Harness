"""Every workflow job has a ceiling, and the PR workflow runs one live run per ref.

Split from `test_workflow_contracts.py`, which sits at the test size budget
(DEC-035's precedent for the seam): that module pins the *shape* of the
workflows' steps, this one pins the *runtime limits* around every job.

Neither workflow declared `timeout-minutes` on any job, and neither declared a
`concurrency` group (2026 standards audit, M16). Without a timeout a hung step
holds a runner for GitHub's six-hour default, and a required check stays
pending for the same six hours; without a concurrency group every push to a PR
branch queues a full run for a head that no longer exists. The two are pinned
separately because they are wanted in different places: every job in both
workflows gets a ceiling, but only the PR workflow cancels superseded runs --
the scheduled workflow's runs open issues, and a cancelled run there is a lost
notification.

Parsing is textual, per job, like the sibling modules: PyYAML is not a declared
dependency of this repository and a gate must not depend on a transitive one.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from harness.shared.tests._workflow_paths import DRIFT_WORKFLOW, WORKFLOW
from harness.shared.tests.test_workflow_contracts import job_sections

pytestmark = pytest.mark.governance

#: A job-level `timeout-minutes`: four spaces of indentation, an integer value.
#: A step-level one (eight spaces, under `steps:`) bounds one step and leaves
#: the rest of the job on the six-hour default, so it does not count.
JOB_TIMEOUT = re.compile(r"^    timeout-minutes:\s*(\d+)\s*$", re.M)


def job_timeouts(workflow_text: str) -> dict[str, int | None]:
    """Map job id -> its job-level `timeout-minutes`, or None when it has none."""
    return {
        job: (int(match.group(1)) if (match := JOB_TIMEOUT.search(body)) else None)
        for job, body in job_sections(workflow_text).items()
    }


def jobs_without_timeout(workflow_text: str) -> list[str]:
    return [job for job, minutes in job_timeouts(workflow_text).items() if minutes is None]


def concurrency_block(workflow_text: str) -> dict[str, str] | None:
    """The top-level `concurrency:` mapping as {key: value}, or None when absent.

    Top-level means column zero; a `concurrency:` nested under a job would scope
    the group to that job alone and leave the other jobs of a superseded run
    queued.
    """
    match = re.search(r"^concurrency:\n((?:[ ]{2}\S.*\n)+)", workflow_text, re.M)
    if match is None:
        return None
    return {
        key.strip(): value.strip()
        for key, value in (line.split(":", 1) for line in match.group(1).splitlines())
    }


class TestEveryJobHasACeiling:
    @pytest.mark.parametrize("path", [WORKFLOW, DRIFT_WORKFLOW], ids=lambda p: p.name)
    def test_no_job_runs_on_the_six_hour_default(self, path: Path) -> None:
        text = path.read_text(encoding="utf-8")
        assert job_timeouts(text), f"{path.name} has no jobs; the parser or the file is broken"
        missing = jobs_without_timeout(text)
        assert not missing, (
            f"{path.name} jobs with no job-level timeout-minutes: {missing}. A hung step there "
            "holds a runner, and a required check, for six hours"
        )

    @pytest.mark.parametrize("path", [WORKFLOW, DRIFT_WORKFLOW], ids=lambda p: p.name)
    def test_every_ceiling_is_a_ceiling_not_a_default(self, path: Path) -> None:
        """A value at or above GitHub's default is the same as no value."""
        for job, minutes in job_timeouts(path.read_text(encoding="utf-8")).items():
            assert minutes is not None and 0 < minutes < 360, f"{path.name} job {job!r}: timeout-minutes={minutes}"

    @pytest.mark.parametrize(
        ("body", "why"),
        [
            pytest.param("    runs-on: ubuntu-latest\n", "a job with no timeout at all", id="no-timeout"),
            pytest.param(
                "    runs-on: ubuntu-latest\n    steps:\n      - run: make ci\n        timeout-minutes: 30\n",
                "a step-level timeout, which bounds one step and leaves the job on the default",
                id="step-level-only",
            ),
        ],
    )
    def test_a_job_without_a_job_level_timeout_is_reported(self, body: str, why: str) -> None:
        """Without these the check would pass on a workflow with no jobs at all."""
        text = f"name: x\non: push\njobs:\n  one:\n{body}"
        assert jobs_without_timeout(text) == ["one"], f"{why} must be reported"

    def test_a_job_with_a_job_level_timeout_is_not_reported(self) -> None:
        """The control, with the timeout after other keys so position is not what passes it."""
        text = "name: x\non: push\njobs:\n  one:\n    runs-on: ubuntu-latest\n    timeout-minutes: 30\n    steps: []\n"
        assert jobs_without_timeout(text) == []
        assert job_timeouts(text) == {"one": 30}


class TestSupersededPullRequestRunsAreCancelled:
    def test_the_pr_workflow_keeps_one_live_run_per_ref(self) -> None:
        block = concurrency_block(WORKFLOW.read_text(encoding="utf-8"))
        assert block is not None, f"{WORKFLOW.name} declares no top-level concurrency group"
        assert "github.workflow" in block.get("group", "") and "github.ref" in block.get("group", ""), (
            f"the group must be keyed on both the workflow and the ref, not {block.get('group')!r}: "
            "without the ref every PR shares one group, without the workflow the drift runs join it"
        )
        assert block.get("cancel-in-progress") == "true", (
            "a superseded run must be cancelled, or the group only queues it behind the old one"
        )

    def test_the_scheduled_workflow_has_none(self) -> None:
        """Its runs open issues; cancelling one loses the notification that is its job."""
        assert concurrency_block(DRIFT_WORKFLOW.read_text(encoding="utf-8")) is None

    @pytest.mark.parametrize(
        ("text", "why"),
        [
            pytest.param("name: x\non: push\njobs:\n  one:\n    runs-on: a\n", "no block at all", id="absent"),
            pytest.param(
                "name: x\njobs:\n  one:\n    concurrency:\n      group: g\n      cancel-in-progress: true\n",
                "a block nested under one job, which scopes the group to that job",
                id="job-scoped",
            ),
        ],
    )
    def test_a_workflow_without_a_top_level_group_is_reported(self, text: str, why: str) -> None:
        assert concurrency_block(text) is None, f"{why} must read as absent"

    def test_a_group_that_only_queues_is_distinguishable(self) -> None:
        """`cancel-in-progress: false` is a valid block that does not do the job."""
        group = "${{ github.workflow }}-${{ github.ref }}"
        text = f"name: x\nconcurrency:\n  group: {group}\n  cancel-in-progress: false\njobs:\n"
        assert concurrency_block(text) == {"group": group, "cancel-in-progress": "false"}
