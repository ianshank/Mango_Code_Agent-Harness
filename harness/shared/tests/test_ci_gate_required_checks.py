"""`NEXT_STEPS.md`'s required-status-check list must match what CI reports.

Split out of `test_ci_gate_coverage.py` by concern (tech-debt-hardening-plan
R-TDH-22); the workflow parser it exercises lives in `_ci_gate_helpers.py`.
"""

from __future__ import annotations

import re

import pytest

from harness.shared.tests._ci_gate_helpers import (
    NEXT_STEPS,
    ROOT_WORKFLOW_DIR,
    _job_check_names,
    _reported_check_names,
    _workflow_jobs,
)

pytestmark = pytest.mark.governance


class TestRequiredStatusChecksListIsAccurate:
    """`NEXT_STEPS.md` hands a human the literal check names for the branch
    ruleset GitHub has no API this repo's CI can configure on its own behalf --
    someone pastes this list into Settings -> Rules by hand, once. A list that
    silently drifts from what CI actually reports is exactly how the ruleset
    would end up requiring a `build (3.11)` that never runs, or omitting a real
    gate like `dependency-audit`: the ruleset would enforce a check GitHub
    never sends, or leave a check GitHub does send permanently unrequired,
    with nothing here to say so.
    """

    @pytest.fixture()
    def workflow_text(self) -> str:
        path = ROOT_WORKFLOW_DIR / "python-package.yml"
        assert path.is_file(), f"{path} does not exist"
        return path.read_text(encoding="utf-8")

    @pytest.fixture()
    def next_steps_text(self) -> str:
        assert NEXT_STEPS.is_file(), f"{NEXT_STEPS} does not exist"
        return NEXT_STEPS.read_text(encoding="utf-8")

    @staticmethod
    def _documented_required_checks(next_steps_text: str) -> set[str]:
        # Scoped to the sentence between "Required status checks" and its
        # terminating period: the paragraph after it repeats one of these
        # names in different prose, which would corrupt an unscoped search.
        sentence = re.search(r"Required status checks[^:]*:\s*(.+?)\.\s*\n", next_steps_text, re.S)
        assert sentence, "NEXT_STEPS.md has no 'Required status checks' sentence to parse"
        return set(re.findall(r"`([^`]+)`", sentence.group(1)))

    def test_documented_checks_match_what_ci_reports(self, workflow_text: str, next_steps_text: str) -> None:
        reported = _reported_check_names(workflow_text)
        documented = self._documented_required_checks(next_steps_text)
        missing = sorted(reported - documented)
        extra = sorted(documented - reported)
        assert not missing and not extra, (
            "NEXT_STEPS.md's required-status-check list has drifted from what "
            f"python-package.yml reports. CI reports but the doc omits: {missing}. "
            f"The doc lists but CI no longer reports: {extra}. A branch ruleset "
            "built from the doc as it stands would misconfigure at least one check."
        )

    def test_every_job_contributes_at_least_one_check_name(self, workflow_text: str) -> None:
        """A job that silently derives zero names would make the comparison
        above vacuously agree with an incomplete `reported` set -- this pins
        that every job in the workflow contributes something to compare."""
        jobs = _workflow_jobs(workflow_text)
        assert jobs, "no jobs found in python-package.yml; the parser or the file is broken"
        for job_id, body in jobs.items():
            assert _job_check_names(job_id, body), f"job '{job_id}' derived no check name"

    def test_quoted_name_and_matrix_values_parse_the_same_as_unquoted(self) -> None:
        """YAML quoting is syntax, not content -- this repo's workflow never
        quotes a job `name:`, but a future edit that adds quotes for style
        reasons alone must not read as a check-name change. Covers exactly
        the two cases a Copilot review of this file flagged as unverified."""
        unquoted = "  audit:\n    name: dependency-audit\n    steps:\n"
        double_quoted = '  audit:\n    name: "dependency-audit"\n    steps:\n'
        single_quoted = "  audit:\n    name: 'dependency-audit'\n    steps:\n"
        for body in (unquoted, double_quoted, single_quoted):
            assert _job_check_names("audit", body) == ["dependency-audit"]

        double_quoted_matrix = (
            '  build:\n    strategy:\n      matrix:\n        python-version: ["3.9", "3.10"]\n    steps:\n'
        )
        single_quoted_matrix = (
            "  build:\n    strategy:\n      matrix:\n        python-version: ['3.9', '3.10']\n    steps:\n"
        )
        for body in (double_quoted_matrix, single_quoted_matrix):
            assert _job_check_names("build", body) == ["build (3.9)", "build (3.10)"]

    def test_block_list_matrix_syntax_parses_the_same_as_inline(self) -> None:
        """GitHub Actions treats an inline flow list and a block list as the
        identical matrix axis; a Copilot review of this file correctly
        flagged that only the inline form was recognized, which would have
        read a purely stylistic reformat as the matrix disappearing."""
        inline = '  build:\n    strategy:\n      matrix:\n        python-version: ["3.9", "3.10"]\n    steps:\n'
        block = (
            "  build:\n    strategy:\n      matrix:\n"
            "        python-version:\n"
            '          - "3.9"\n'
            '          - "3.10"\n'
            "    steps:\n"
        )
        block_single_quoted = (
            "  build:\n    strategy:\n      matrix:\n"
            "        python-version:\n"
            "          - '3.9'\n"
            "          - '3.10'\n"
            "    steps:\n"
        )
        for body in (inline, block, block_single_quoted):
            assert _job_check_names("build", body) == ["build (3.9)", "build (3.10)"]

    def test_matrix_search_is_scoped_to_pre_steps(self) -> None:
        """A step's `with:` input is a different context than the job's own
        `strategy.matrix`; matching a bracket-list-shaped step input there
        would be inspecting the wrong thing, not just a false drift signal."""
        body = (
            "  build:\n    runs-on: ubuntu-latest\n    steps:\n"
            "      - name: Some future step\n"
            "        with:\n"
            '          python-version: ["3.9", "3.10"]\n'
        )
        assert _job_check_names("build", body) == ["build"]

    def test_steps_split_tolerates_a_trailing_comment(self) -> None:
        """YAML allows `steps:  # comment`; a split that only recognizes the
        bare key would leave the whole body -- steps included -- searched for
        a job-level `name:`, and a step written in the rarer `-` / `name:`
        two-line list-item style would then be mistaken for it. A Copilot
        review of this file flagged exactly this gap."""
        body = (
            "  build:\n    runs-on: ubuntu-latest\n"
            "    steps:  # comment\n"
            "      -\n"
            "        name: Checkout\n"
            "        uses: actions/checkout@v4\n"
        )
        assert _job_check_names("build", body) == ["build"]

    def test_a_trailing_comment_on_the_job_name_is_stripped(self) -> None:
        """The other half of the same Copilot suggestion: a comment on the
        job-level `name:` line itself must not become part of the derived
        check name, quoted or not."""
        unquoted = "  secrets:\n    name: secret-scan  # the security gate\n    steps:\n"
        double_quoted = '  secrets:\n    name: "secret-scan"  # the security gate\n    steps:\n'
        single_quoted = "  secrets:\n    name: 'secret-scan'  # the security gate\n    steps:\n"
        for body in (unquoted, double_quoted, single_quoted):
            assert _job_check_names("secrets", body) == ["secret-scan"]
