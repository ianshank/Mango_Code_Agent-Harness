"""Behavioural tests for the spec gate (`make specs` -> harness/shared/validate_specs.sh).

`specs` is a `ci_required_targets` gate wired into `make ci`, and until now the only
thing asserting anything about it was `test_ci_gate_coverage.py`, which checks that
the Makefile *invokes* it. That is a name check, not a behaviour check: the script
could be gutted to `exit 0` and every existing assertion would still pass.

Each test here drives the real script as a subprocess against a fixture spec
directory (`SPEC_DIR` is already a parameter of the script, so no code had to change
to make it testable) and asserts on the exit status and the diagnostic. Every
failing case is a mutation the gate must catch; every passing case pins a shape the
gate must *not* reject, so the rules cannot be tightened into uselessness either.

The two tiers are tested separately:

* structural tier -- always runs, and is the tier that actually does work today.
* strict tier (`openspec validate`) -- unenforced at root; see
  `PARTIAL_COVERAGE["specs"]` in test_ci_gate_coverage.py. What is pinned here is
  the *fail-closed* contract: when the caller demands it, an absent validator must
  stop the gate rather than warn.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

from harness.shared.tests.conftest import POSIX_ONLY

pytestmark = [POSIX_ONLY, pytest.mark.governance]

REPO = Path(__file__).resolve().parents[3]
SCRIPT = REPO / "harness" / "shared" / "validate_specs.sh"

# A spec that satisfies every structural rule. Each test mutates one aspect of this
# baseline, so a failure localises to the rule under test rather than to the fixture.
VALID_SPEC = """\
# Widget pipeline

## Requirements

- R-widget-1 The pipeline MUST reject a payload larger than the configured limit.
- R-widget-2 The pipeline MUST emit one audit record per accepted payload.

## Acceptance criteria

- A payload of limit+1 bytes returns HTTP 413 and increments `rejected_total`.
- Each accepted payload produces exactly one row in the audit table.
"""


def _run(spec_dir: Path, **env_overrides: str) -> subprocess.CompletedProcess[str]:
    """Invoke the gate against a fixture directory.

    Via `bash` deliberately: validate_specs.sh is mode 644, so a bare `./` call is a
    guaranteed "Permission denied" -- the same reason the Makefile invokes it this way.
    """
    env = {**os.environ, "SPEC_DIR": str(spec_dir)}
    env.update(env_overrides)
    return subprocess.run(
        ["bash", str(SCRIPT)], capture_output=True, text=True, env=env, cwd=REPO
    )


@pytest.fixture
def spec_dir(tmp_path: Path) -> Path:
    d = tmp_path / "specs"
    d.mkdir()
    return d


def _write(spec_dir: Path, name: str, text: str) -> Path:
    path = spec_dir / name
    path.write_text(text, encoding="utf-8")
    return path


class TestStructuralTierAccepts:
    """Negative space: rules that reject a conforming spec are worse than no rules."""

    def test_a_conforming_spec_passes(self, spec_dir: Path):
        _write(spec_dir, "widget.md", VALID_SPEC)
        result = _run(spec_dir)
        assert result.returncode == 0, result.stderr
        assert "structural validation passed" in result.stdout

    def test_the_document_count_reflects_the_specs_scanned(self, spec_dir: Path):
        _write(spec_dir, "a.md", VALID_SPEC)
        _write(spec_dir, "b.md", VALID_SPEC)
        result = _run(spec_dir)
        assert result.returncode == 0, result.stderr
        assert "(2 documents)" in result.stdout

    def test_nested_specs_are_discovered(self, spec_dir: Path):
        """rglob, not glob: a spec in a subdirectory must not escape the gate."""
        (spec_dir / "sub").mkdir()
        _write(spec_dir, "sub/nested.md", VALID_SPEC)
        result = _run(spec_dir)
        assert result.returncode == 0, result.stderr
        assert "(1 documents)" in result.stdout

    def test_a_non_normative_mention_of_must_needs_no_id(self, spec_dir: Path):
        """Only *bullet* lines are normative. Prose is allowed to use the word."""
        prose = VALID_SPEC + "\n## Notes\n\nCallers MUST generally be careful here.\n"
        _write(spec_dir, "widget.md", prose)
        assert _run(spec_dir).returncode == 0

    def test_a_bullet_without_must_needs_no_id(self, spec_dir: Path):
        extra = VALID_SPEC + "\n- A non-normative note about the pipeline.\n"
        _write(spec_dir, "widget.md", extra)
        assert _run(spec_dir).returncode == 0

    def test_asterisk_bullets_are_treated_the_same_as_dashes(self, spec_dir: Path):
        """Both markdown bullet markers must be scanned; one being missed would be a
        silent bypass of the requirement-ID rule for anyone who writes `*`."""
        bad = VALID_SPEC.replace(
            "- R-widget-1 The pipeline MUST reject",
            "* The pipeline MUST reject",
        )
        _write(spec_dir, "widget.md", bad)
        assert _run(spec_dir).returncode != 0, "an unidentified `*` MUST bullet was accepted"


class TestStructuralTierRejects:
    """Each case is a mutation the gate must catch."""

    @pytest.mark.parametrize("section", ["## Requirements", "## Acceptance criteria"])
    def test_a_missing_required_section_fails(self, spec_dir: Path, section: str):
        _write(spec_dir, "widget.md", VALID_SPEC.replace(section, "## Something else"))
        result = _run(spec_dir)
        assert result.returncode != 0
        assert f"missing {section}" in result.stderr

    def test_a_normative_must_without_a_requirement_id_fails(self, spec_dir: Path):
        bad = VALID_SPEC.replace("- R-widget-1 The pipeline MUST", "- The pipeline MUST")
        _write(spec_dir, "widget.md", bad)
        result = _run(spec_dir)
        assert result.returncode != 0
        assert "normative MUST has no requirement ID" in result.stderr

    @pytest.mark.parametrize("phrase", ["works correctly", "as expected", "appropriately"])
    def test_unfalsifiable_acceptance_language_fails(self, spec_dir: Path, phrase: str):
        bad = VALID_SPEC + f"\n- The pipeline {phrase} under load.\n"
        _write(spec_dir, "widget.md", bad)
        result = _run(spec_dir)
        assert result.returncode != 0
        assert "unfalsifiable acceptance language" in result.stderr

    def test_unfalsifiable_language_is_matched_case_insensitively(self, spec_dir: Path):
        _write(spec_dir, "widget.md", VALID_SPEC + "\n- Behaves As Expected.\n")
        assert _run(spec_dir).returncode != 0

    def test_the_failing_file_is_named(self, spec_dir: Path):
        """With several specs, an operator needs to know *which* one is bad."""
        _write(spec_dir, "good.md", VALID_SPEC)
        _write(spec_dir, "bad.md", VALID_SPEC.replace("## Requirements", "## Nope"))
        result = _run(spec_dir)
        assert result.returncode != 0
        assert "bad.md" in result.stderr
        assert "good.md" not in result.stderr

    def test_all_violations_are_reported_not_just_the_first(self, spec_dir: Path):
        """A gate that stops at the first failure costs a CI round trip per rule."""
        bad = VALID_SPEC.replace("## Requirements", "## Nope").replace(
            "## Acceptance criteria", "## Nah"
        )
        _write(spec_dir, "widget.md", bad)
        result = _run(spec_dir)
        assert "missing ## Requirements" in result.stderr
        assert "missing ## Acceptance criteria" in result.stderr


class TestSpecDirectoryContract:
    """An empty or absent spec set must fail closed, never pass vacuously."""

    def test_an_empty_spec_directory_fails(self, spec_dir: Path):
        result = _run(spec_dir)
        assert result.returncode != 0
        assert "no markdown specs found" in result.stderr

    def test_a_nonexistent_spec_directory_fails(self, tmp_path: Path):
        result = _run(tmp_path / "absent")
        assert result.returncode != 0
        assert "does not exist" in result.stderr


class TestStrictTier:
    """The strict tier is unenforced at root, but its fail-closed contract is not."""

    def test_absent_validator_fails_closed_when_strict_is_required(self, spec_dir: Path):
        _write(spec_dir, "widget.md", VALID_SPEC)
        result = _run(
            spec_dir,
            REQUIRE_STRICT_SPEC_VALIDATOR="1",
            SPEC_VALIDATOR="definitely-not-installed-validator",
        )
        assert result.returncode == 1
        assert "failing closed" in result.stderr

    def test_absent_validator_warns_loudly_but_still_runs_the_structural_tier(
        self, spec_dir: Path
    ):
        """The degraded path must stay *audible*. A silent skip is how a two-tier
        gate comes to advertise a tier it never runs."""
        _write(spec_dir, "widget.md", VALID_SPEC)
        result = _run(
            spec_dir,
            REQUIRE_STRICT_SPEC_VALIDATOR="0",
            SPEC_VALIDATOR="definitely-not-installed-validator",
        )
        assert result.returncode == 0, result.stderr
        assert "WARNING" in result.stderr
        assert "structural validation passed" in result.stdout

    def test_the_degraded_path_still_rejects_a_bad_spec(self, spec_dir: Path):
        """The one that matters: without the strict tier the gate is *reduced*, not
        disabled. This is the assertion that distinguishes 'degraded' from 'off'."""
        _write(spec_dir, "widget.md", VALID_SPEC.replace("## Requirements", "## Nope"))
        result = _run(
            spec_dir,
            REQUIRE_STRICT_SPEC_VALIDATOR="0",
            SPEC_VALIDATOR="definitely-not-installed-validator",
        )
        assert result.returncode != 0


class TestRepositorySpecsAreConforming:
    def test_the_real_spec_directory_passes(self):
        """Mirrors the `specs` CI stage against the committed specs."""
        result = _run(REPO / "docs" / "specs")
        assert result.returncode == 0, result.stderr
