"""Structural invariants of the root pipeline other tooling and docs depend on.

Split out of `test_ci_gate_coverage.py` by concern (tech-debt-hardening-plan
R-TDH-22): the gate-coverage map lives there, the required-status-check list
in `test_ci_gate_required_checks.py`, and the parser they share in
`_ci_gate_helpers.py`.
"""

from __future__ import annotations

import re

import pytest

from harness.shared.tests import _ci_gate_helpers as _shared
from harness.shared.tests._ci_gate_helpers import (
    REPO,
    _expand_make_vars,
    _make_prerequisites,
    _make_targets,
    _numeric_fallback_shape,
    _reachable_from,
    _recipe_body,
    _root_workflow_texts,
    _workflow_jobs,
    _workflow_run_commands,
)

# Fixture bindings, not imports: see the note in test_ci_gate_coverage.py.
ci_reachable = _shared.ci_reachable
makefile = _shared.makefile
root_workflows = _shared.root_workflows

pytestmark = pytest.mark.governance

# Stages that must remain direct prerequisites of `ci`. Checked against `ci`'s own
# prerequisite list rather than transitive reachability, which a stray token could
# otherwise pollute.
REQUIRED_CI_STAGES = {
    "test-node": "the Node suite; without it the TypeScript stack is ungated",
    "verify-zero-skips": "INV-2 (no unapproved skips)",
    "verify-zero-skips-python": "INV-2 (no unapproved skips), the Python half (DEC-026)",
    "check-dedup": "named non-negotiable in CLAUDE.md; detects copied governance scripts",
    "digest-regen": "the control-plane drift baseline `git diff --exit-code` compares against",
    "specs": "the spec structural, plan-defect, and strict tiers",
    "remotes": "INV-3 (push destination allowlist)",
    "validate": "the governance validator set, including the protected-path gate",
}


class TestRootPipelineShape:
    """Guards the structural invariants other tooling and docs depend on."""

    def test_ci_runs_the_specs_stage(self, ci_reachable):
        assert "specs" in ci_reachable, "`make ci` no longer runs the specs gate"

    def test_ci_runs_the_remotes_stage(self, ci_reachable):
        assert "remotes" in ci_reachable, "`make ci` no longer runs the remote allowlist gate"

    def test_specs_target_invokes_the_validator_through_bash(self, makefile):
        """validate_specs.sh is mode 644: a bare ./ invocation is a guaranteed red CI."""
        # _recipe_body (not a hand-rolled regex here) strips comment lines and
        # accepts both `:` and `::` rule syntax, exactly like every other
        # target-body test in this file -- a bespoke regex would silently pass
        # a commented-out invocation as if it were live.
        body = _recipe_body(makefile, "specs")
        assert body, "root Makefile has no specs recipe"
        assert "validate_specs.sh" in body, "specs target does not invoke validate_specs.sh"
        assert re.search(r"\bbash\b\s+\S*validate_specs\.sh", body), (
            "validate_specs.sh must be invoked via `bash`; it is not executable, so a "
            "bare ./ invocation fails with 'Permission denied'"
        )

    def test_secret_scan_gate_fails_closed_and_scans_history(self, makefile, root_workflows):
        """INV-1: a missing tool must fail, and the history scan must not be vacuous."""
        # _recipe_body strips Make comment lines: a commented-out scan still appears
        # in a raw capture, so a substring check would accept a disabled gate.
        body = _recipe_body(makefile, "secrets")
        assert body, "root Makefile has no secrets recipe"
        assert "command -v" in body and "exit 1" in body, (
            "the secrets gate must fail closed when gitleaks is absent, never skip"
        )
        for mode, what in (("dir", "the working tree"), ("git", "git history")):
            assert re.search(rf"(?:\$\(GITLEAKS\)|gitleaks\S*)\s+{mode}\b", body), (
                f"secrets gate does not scan {what}"
            )
        # Scoped per job: a global search for `fetch-depth: 0` is satisfied by the
        # build job's checkout, so the scanning job could go shallow undetected.
        scanning = [
            (job, block)
            for text in _root_workflow_texts()
            for job, block in _workflow_jobs(text).items()
            if re.search(r"\bmake\s+secrets\b(?!-)", _workflow_run_commands(block))
        ]
        assert scanning, (
            "no root workflow job invokes `make secrets`; INV-1 would have no live "
            "enforcement, since GitHub never runs harness/*/.github/workflows/"
        )
        for job, block in scanning:
            assert "fetch-depth: 0" in block, (
                f"job '{job}' runs the secret scan without a full clone; the default "
                "shallow checkout makes the history half of INV-1 vacuous"
            )
            # A conditional can disable the gate while the invocation remains:
            # `if: github.event_name == 'push'` would exempt every pull request.
            guards = re.findall(r"^\s*(?:-\s+)?if:\s*(.+)$", block, re.M)
            assert not guards, (
                f"job '{job}' gates the secret scan behind conditional(s) {guards}; "
                "INV-1 must run unconditionally on every triggering event"
            )

    def test_audit_gate_is_invoked_unconditionally(self) -> None:
        """Mirrors the secret-scan check above: GATE_TO_ROOT_TARGET only proves some
        workflow contains a `make audit` command, not that it always runs. A job- or
        step-level `if:` guard (e.g. `if: github.event_name == 'push'`) would leave
        this gate green while skipping every pull request's dependency audit."""
        auditing = [
            (job, block)
            for text in _root_workflow_texts()
            for job, block in _workflow_jobs(text).items()
            if re.search(r"\bmake\s+audit\b(?!-)", _workflow_run_commands(block))
        ]
        assert auditing, (
            "no root workflow job invokes `make audit`; the dependency-audit gate "
            "would have no live enforcement"
        )
        for job, block in auditing:
            # Same conditional-guard check as the secret scan: the invocation
            # remaining in the file proves nothing if a guard can skip the job.
            guards = re.findall(r"^\s*(?:-\s+)?if:\s*(.+)$", block, re.M)
            assert not guards, (
                f"job '{job}' gates the dependency audit behind conditional(s) "
                f"{guards}; it must run unconditionally on every triggering event"
            )

    @pytest.mark.parametrize("stage", sorted(REQUIRED_CI_STAGES))
    def test_required_stage_is_a_direct_prerequisite_of_ci(self, stage, makefile):
        """Checked against `ci`'s own prerequisites, not transitive reachability,
        which a stray token in a comment could otherwise satisfy."""
        prereqs = _make_prerequisites(makefile, "ci")
        assert stage in prereqs, (
            f"`make ci` no longer runs '{stage}' — {REQUIRED_CI_STAGES[stage]}. "
            f"Current prerequisites: {prereqs}"
        )

    def test_every_ci_prerequisite_is_a_real_target(self, makefile):
        """A fabricated name must never satisfy a reachability assertion."""
        defined = _make_targets(makefile)
        phantom = sorted(t for t in _reachable_from(makefile, "ci") if t not in defined)
        assert not phantom, (
            f"`make ci` depends on names with no rule in the Makefile: {phantom}. "
            "Either they are typos, or the parser accepted comment text as targets."
        )

    def test_coverage_thresholds_are_enforced_by_the_gate_script(self, makefile):
        """The recipe must produce the machine-readable report AND run the gate.

        coverage_gate.py applies coverage.lines and coverage.branches as two
        separate numbers. Its thresholds come from governance-policy.json with no
        numeric default anywhere, so "not hardcoded" is a property of the script;
        what the Makefile must guarantee is that the script actually runs against
        a report produced by this same pytest invocation.
        """
        body = _recipe_body(makefile, "coverage-python")
        assert body, "root Makefile has no coverage-python recipe"
        assert "--cov-report=json" in body, (
            "coverage-python must emit coverage.json; without it the gate script "
            "fails closed on every run instead of measuring anything"
        )
        assert re.search(r"coverage_gate\.py", body), (
            "coverage-python no longer runs coverage_gate.py; the pytest run "
            "would measure coverage without enforcing any threshold"
        )

    def test_digest_regen_regenerates_both_digest_layers(self, makefile):
        """The bundle has two layers: profiles[*].protected_files (refreshed by
        regenerate_bundle_digests.py) and the top-level governance/agent policy
        digests (refreshed ONLY by build_policy_bundle.py). Dropping either tool
        from the recipe silently un-gates its layer, so both invocations -- and
        the `git diff --exit-code` that turns drift red -- are pinned here."""
        body = _recipe_body(makefile, "digest-regen")
        assert body, "root Makefile has no digest-regen recipe"
        for required in (
            "regenerate_bundle_digests.py",
            "build_policy_bundle.py",
            "git diff --exit-code",
        ):
            assert required in body, f"digest-regen recipe no longer runs {required}"

    def test_coverage_gate_script_has_no_numeric_fallback(self):
        """The gate script must carry no default threshold a broken policy could
        silently fall back to -- the COV_MIN=80 inversion, one layer down
        (CHANGELOG: "COV_MIN fell back to the literal 80 whenever the policy
        was unreadable or its coverage block absent").

        Matches ANY numeric fallback in these shapes, not only values equal
        to governance-policy.json's current thresholds: a fallback to an
        arbitrary number unrelated to any real threshold (`.get("lines", 85)`
        while policy says 90) is exactly as forbidden as one that happens to
        collide with today's 80/90, and checking only the current values
        would evade it entirely. Patterns are scoped to fallback-shaped
        syntax (argparse/kwarg `default=`, a `dict.get` fallback, the `or`
        idiom, or a threshold-named constant) rather than any bare `= N`, so
        an unrelated literal that happens to look like one of these shapes
        for a non-threshold reason does not fail this test with no real
        defect present.
        """
        source = (REPO / "harness" / "shared" / "coverage_gate.py").read_text(encoding="utf-8")
        assert "governance-policy.json" in source
        match = _numeric_fallback_shape(source)
        assert not match, (
            f"coverage_gate.py has a fallback shape ({match.group(0)!r}); "
            "thresholds have exactly one source, governance-policy.json"
        )

    def test_numeric_fallback_shape_catches_values_unrelated_to_current_policy(self) -> None:
        """A fallback to an arbitrary number that doesn't equal any of
        governance-policy.json's current thresholds is exactly as forbidden
        as one that does. A Copilot review of this file correctly flagged
        that an earlier version only checked the current (80, 90) pair and
        would have missed a fallback to, say, 85."""
        arbitrary = 'lines_min = policy.get("coverage", {}).get("lines", 85)\n'
        match = _numeric_fallback_shape(arbitrary)
        assert match is not None and match.group(0) == '.get("lines", 85)'

        unrelated = "MAX_LINE_LENGTH = 80\nBYTE_CAP = 90\n"
        assert _numeric_fallback_shape(unrelated) is None

    def test_coverage_run_does_not_exclude_tests(self, makefile):
        """Deselecting governance tests would silently drop these very gates."""
        body = _recipe_body(makefile, "coverage-python")
        for flag in ("--ignore", "--deselect"):
            assert flag not in body, f"coverage-python excludes tests via {flag}"
        markers = re.findall(r'-m\s+"([^"]+)"', body)
        for expression in markers:
            assert "not governance" not in expression, (
                f"coverage-python deselects governance tests via -m {expression!r}"
            )

    def test_coverage_measures_every_declared_source_root(self, makefile):
        """A source root in pyproject's coverage config that the gate never measures
        is configured-but-unmeasured — the state harness/control-plane was in."""
        pyproject = (REPO / "pyproject.toml").read_text(encoding="utf-8")
        # Scoped to the [tool.coverage.run] table: an unscoped search takes the
        # first `source = [` anywhere in the file, which any other [tool.*] table
        # could silently become.
        table = re.search(r"^\[tool\.coverage\.run\]\s*$(.*?)(?=^\[)", pyproject, re.M | re.S)
        assert table, "pyproject declares no [tool.coverage.run] table"
        source_block = re.search(r"^source\s*=\s*\[(.*?)\]", table.group(1), re.M | re.S)
        assert source_block, "pyproject declares no [tool.coverage.run] source"
        declared = re.findall(r'"([^"]+)"', source_block.group(1))
        assert declared, "coverage source list is empty"
        body = _expand_make_vars(makefile, _recipe_body(makefile, "coverage-python"))
        assert body, "root Makefile has no coverage-python recipe"
        # Exact token comparison: `"--cov=harness" in body` is satisfied by
        # `--cov=harness/shared`, so broadening the declared source to ["harness"]
        # would read as measured while most of the tree stayed unmeasured.
        measured = set(re.findall(r"--cov=(\S+)", body))
        unmeasured = sorted(s for s in declared if s not in measured)
        assert not unmeasured, (
            f"coverage source root(s) declared in pyproject but never measured by the "
            f"gate: {unmeasured}. The Makefile's explicit --cov flags take precedence "
            "over the static config, so these read as covered while being ignored."
        )

