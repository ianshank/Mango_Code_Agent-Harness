"""Tests for harness/shared/coverage_gate.py — per-metric floors, fail-closed reads.

The gate's contract: thresholds come only from governance-policy.json, each
metric is compared against its own numerator/denominator from coverage.json,
and every unreadable or malformed input exits 1 with a reason (absence of
evidence is never a pass).
"""

from __future__ import annotations

import importlib
import json
import logging
import runpy
import sys
from pathlib import Path

import pytest

from harness.shared import coverage_gate as cg
from harness.shared import coverage_scope as cs

GATE = Path(cg.__file__).resolve()

#: Capture on the package logger, not on one module's. The gate's scope concern
#: moved to `coverage_scope.py`, and every `caplog.at_level(..., logger=cg.logger.name)`
#: silently stopped seeing the records it asserted on -- the behaviour was
#: unchanged, the capture target had moved. Anchoring on the common parent
#: survives the next move too, since child loggers inherit its level.
SHARED_LOGGER = "harness.shared"

pytestmark = pytest.mark.governance


def _write_json(path: Path, obj: object) -> Path:
    path.write_text(json.dumps(obj), encoding="utf-8")
    return path


@pytest.fixture
def policy_file(tmp_path: Path) -> Path:
    return _write_json(tmp_path / "policy.json", {"coverage": {"lines": 80, "branches": 70}})


@pytest.fixture
def coverage_file(tmp_path: Path) -> Path:
    return _write_json(
        tmp_path / "coverage.json",
        {
            "totals": {
                "covered_lines": 90,
                "num_statements": 100,
                "covered_branches": 75,
                "num_branches": 100,
            }
        },
    )


# --- load_thresholds ---


def test_load_thresholds_reads_both_metrics(policy_file: Path):
    assert cg.load_thresholds(policy_file) == {"lines": 80.0, "branches": 70.0}


def test_load_thresholds_missing_coverage_block_fails_closed(tmp_path: Path, caplog):
    policy = _write_json(tmp_path / "policy.json", {"limits": {}})
    with caplog.at_level(logging.ERROR, logger=SHARED_LOGGER):
        with pytest.raises(SystemExit) as exc:
            cg.load_thresholds(policy)
    assert exc.value.code == 1
    assert "no coverage block" in caplog.text


@pytest.mark.parametrize("bad_value", ["90", None, True])
def test_load_thresholds_non_numeric_metric_fails_closed(tmp_path: Path, bad_value, caplog):
    policy = _write_json(tmp_path / "policy.json", {"coverage": {"lines": bad_value, "branches": 70}})
    with caplog.at_level(logging.ERROR, logger=SHARED_LOGGER):
        with pytest.raises(SystemExit) as exc:
            cg.load_thresholds(policy)
    assert exc.value.code == 1
    assert "missing or non-numeric" in caplog.text


def test_load_thresholds_unreadable_policy_fails_closed(tmp_path: Path):
    with pytest.raises(SystemExit) as exc:
        cg.load_thresholds(tmp_path / "absent.json")
    assert exc.value.code == 1


def test_load_thresholds_non_object_root_fails_closed(tmp_path: Path, caplog):
    policy = _write_json(tmp_path / "policy.json", ["not", "an", "object"])
    with caplog.at_level(logging.ERROR, logger=SHARED_LOGGER):
        with pytest.raises(SystemExit) as exc:
            cg.load_thresholds(policy)
    assert exc.value.code == 1
    assert "root must be a JSON object" in caplog.text


# --- measure ---


def test_measure_extracts_percentages(coverage_file: Path):
    measured = cg.measure(coverage_file)
    assert measured == {"lines": 90.0, "branches": 75.0}


def test_measure_missing_totals_fails_closed(tmp_path: Path, caplog):
    report = _write_json(tmp_path / "coverage.json", {"files": {}})
    with caplog.at_level(logging.ERROR, logger=SHARED_LOGGER):
        with pytest.raises(SystemExit) as exc:
            cg.measure(report)
    assert exc.value.code == 1
    assert "no totals block" in caplog.text


def test_measure_missing_branch_counters_fails_closed(tmp_path: Path, caplog):
    """A coverage.json produced without branch coverage lacks num_branches;
    that must exit 1 with the actionable hint, not divide by a default."""
    report = _write_json(
        tmp_path / "coverage.json",
        {"totals": {"covered_lines": 90, "num_statements": 100}},
    )
    with caplog.at_level(logging.ERROR, logger=SHARED_LOGGER):
        with pytest.raises(SystemExit) as exc:
            cg.measure(report)
    assert exc.value.code == 1
    assert "branch coverage enabled" in caplog.text


def test_measure_zero_denominator_fails_closed(tmp_path: Path, caplog):
    report = _write_json(
        tmp_path / "coverage.json",
        {
            "totals": {
                "covered_lines": 0,
                "num_statements": 0,
                "covered_branches": 0,
                "num_branches": 10,
            }
        },
    )
    with caplog.at_level(logging.ERROR, logger=SHARED_LOGGER):
        with pytest.raises(SystemExit) as exc:
            cg.measure(report)
    assert exc.value.code == 1
    assert "measured zero" in caplog.text


# --- check / main ---


def test_check_passes_when_all_floors_met(caplog):
    with caplog.at_level(logging.INFO, logger=SHARED_LOGGER):
        assert cg.check({"lines": 80.0, "branches": 70.0}, {"lines": 90.0, "branches": 75.0}) is True
    assert "[PASS]" in caplog.text


def test_check_fails_when_one_metric_below_floor(caplog):
    with caplog.at_level(logging.ERROR, logger=SHARED_LOGGER):
        assert cg.check({"lines": 80.0, "branches": 90.0}, {"lines": 90.0, "branches": 75.0}) is False
    assert "below the policy floor" in caplog.text


def test_main_returns_zero_on_pass(policy_file: Path, coverage_file: Path):
    assert cg.main(["--coverage-json", str(coverage_file), "--policy", str(policy_file)]) == 0


def test_main_returns_one_on_violation(tmp_path: Path, coverage_file: Path):
    policy = _write_json(tmp_path / "strict.json", {"coverage": {"lines": 99, "branches": 99}})
    assert cg.main(["--coverage-json", str(coverage_file), "--policy", str(policy)]) == 1


def test_main_dispatch_leg(policy_file: Path, coverage_file: Path, monkeypatch: pytest.MonkeyPatch):
    """The `if __name__ == "__main__"` leg (basicConfig + sys.exit) run exactly
    as `python harness/shared/coverage_gate.py` would run it."""
    monkeypatch.setattr(
        sys,
        "argv",
        ["coverage_gate.py", "--coverage-json", str(coverage_file), "--policy", str(policy_file)],
    )
    with pytest.raises(SystemExit) as exc:
        runpy.run_path(str(GATE), run_name="__main__")
    assert exc.value.code == 0


# --- optional_extra_waivers / per-file waivers (DEC-028) ---
#
# A CI leg that cannot install an optional extra deselects its tests; the
# extra's modules then have no test that could execute there. The per-file
# floor is waived for exactly those files, on exactly that leg, and only when
# the extra is genuinely not importable. Everything else stays enforced.

_ABSENT_MODULE = "mango_no_such_extra_for_tests"
_ENV = "MANGO_TEST_DESELECT_EXTRA"
_PREFIX = "harness/shared/optional/"


def _extras_policy(tmp_path: Path, import_name: str = _ABSENT_MODULE, **overrides: object) -> Path:
    spec: dict[str, object] = {"import_name": import_name, "deselect_env": _ENV, "path_prefixes": [_PREFIX]}
    spec.update(overrides)
    return _write_json(
        tmp_path / "extras.json",
        {"coverage": {"lines": 90, "branches": 80, "per_file": True, "optional_extras": {"opt": spec}}},
    )


def _per_file_report(tmp_path: Path) -> Path:
    def entry(covered: int, total: int) -> dict:
        return {"summary": {"covered_lines": covered, "num_statements": total}}

    return _write_json(
        tmp_path / "per_file.json",
        {
            "totals": {"covered_lines": 95, "num_statements": 100, "covered_branches": 90, "num_branches": 100},
            "files": {f"{_PREFIX}nodes.py": entry(2, 10), "harness/shared/core.py": entry(10, 10)},
        },
    )


def test_waiver_applies_only_when_env_is_set_and_extra_is_absent(tmp_path: Path, caplog):
    policy = _extras_policy(tmp_path)
    assert cg.optional_extra_waivers(policy, environ={}) == {}
    assert cg.optional_extra_waivers(policy, environ={_ENV: "yes"}) == {}
    with caplog.at_level(logging.WARNING, logger=SHARED_LOGGER):
        assert cg.optional_extra_waivers(policy, environ={_ENV: "1"}) == {"opt": (_PREFIX,)}
    assert "[WAIVED]" in caplog.text


def test_waiver_is_refused_when_the_extra_is_importable(tmp_path: Path, caplog):
    policy = _extras_policy(tmp_path, import_name="json")
    with caplog.at_level(logging.INFO, logger=SHARED_LOGGER):
        assert cg.optional_extra_waivers(policy, environ={_ENV: "1"}) == {}
    assert "stays enforced" in caplog.text


def test_absent_extras_block_waives_nothing(policy_file: Path):
    assert cg.optional_extra_waivers(policy_file, environ={_ENV: "1"}) == {}


def test_extras_without_a_coverage_block_fail_closed(tmp_path: Path):
    policy = _write_json(tmp_path / "no_cov.json", {"limits": {}})
    with pytest.raises(SystemExit) as exc:
        cg.optional_extra_waivers(policy, environ={})
    assert exc.value.code == 1


@pytest.mark.parametrize(
    "overrides",
    [
        {"import_name": ""},
        {"deselect_env": 7},
        {"deselect_env": ""},
        {"path_prefixes": []},
        {"path_prefixes": ["ok/", ""]},
        {"path_prefixes": "harness/"},
    ],
)
def test_malformed_extra_fails_closed(tmp_path: Path, overrides: dict, caplog):
    policy = _extras_policy(tmp_path, **overrides)
    with caplog.at_level(logging.ERROR, logger=SHARED_LOGGER), pytest.raises(SystemExit) as exc:
        cg.optional_extra_waivers(policy, environ={})
    assert exc.value.code == 1
    assert "coverage.optional_extras" in caplog.text


@pytest.mark.parametrize("extras", [[1], {"opt": 3}, {"opt": {"deselect_env": _ENV}}])
def test_malformed_extras_container_fails_closed(tmp_path: Path, extras: object):
    policy = _write_json(tmp_path / "bad.json", {"coverage": {"lines": 90, "branches": 80, "optional_extras": extras}})
    with pytest.raises(SystemExit) as exc:
        cg.optional_extra_waivers(policy, environ={})
    assert exc.value.code == 1


def test_check_per_file_reports_waived_files_and_still_enforces_the_rest(tmp_path: Path, caplog):
    report = _per_file_report(tmp_path)
    assert cg.check_per_file(report, 90.0) is False
    with caplog.at_level(logging.INFO, logger=SHARED_LOGGER):
        assert cg.check_per_file(report, 90.0, {"opt": (_PREFIX,)}) is True
    assert f"[WAIVED] Coverage per-file: {_PREFIX}nodes.py at 20.00% lines" in caplog.text
    assert "(1 waived)" in caplog.text


def test_a_waiver_does_not_rescue_a_file_outside_its_prefixes(tmp_path: Path):
    report = _per_file_report(tmp_path)
    assert cg.check_per_file(report, 90.0, {"opt": ("harness/shared/elsewhere/",)}) is False


def _synthetic_root_for(tmp_path: Path, report: Path) -> Path:
    """A repo root whose first-party sources are exactly the report's files.

    `main` bounds the measured set whenever per-file enforcement is on, so a
    per-file test must supply a tree the report can be compared against --
    otherwise it measures this repository's real layout against a synthetic
    report and fails for a reason unrelated to what it is testing.
    """
    root = tmp_path / "synthetic-root"
    for relative in json.loads(report.read_text(encoding="utf-8"))["files"]:
        target = root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("x = 1\n", encoding="utf-8")
    (root / "pyproject.toml").write_text(
        '[tool.coverage.run]\nsource = ["harness/shared"]\n\n[tool.z]\nk = 1\n', encoding="utf-8"
    )
    return root


def test_main_waives_through_the_env_and_keeps_aggregate_floors(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    policy = _extras_policy(tmp_path)
    report = _per_file_report(tmp_path)
    root = _synthetic_root_for(tmp_path, report)
    args = ["--coverage-json", str(report), "--policy", str(policy), "--repo-root", str(root)]
    monkeypatch.delenv(_ENV, raising=False)
    assert cg.main(args) == 1
    monkeypatch.setenv(_ENV, "1")
    assert cg.main(args) == 0
    strict_policy = json.loads(policy.read_text(encoding="utf-8"))
    strict_policy["coverage"]["lines"] = 99
    strict = _write_json(tmp_path / "strict.json", strict_policy)
    assert cg.main(["--coverage-json", str(report), "--policy", str(strict), "--repo-root", str(root)]) == 1, (
        "aggregate floor still applies"
    )


def test_shipped_policy_declares_langgraph_the_way_conftest_and_ci_use_it():
    """Liveness: the extra the 3.9 leg deselects is the one the gate waives, by the same name."""
    from harness.shared.langgraph import LANGGRAPH_AVAILABLE
    from harness.shared.tests.conftest import LANGGRAPH_DESELECT_ENV

    repo_policy = cg.DEFAULT_REPO_ROOT / cg.POLICY_RELPATH
    extras = json.loads(repo_policy.read_text(encoding="utf-8"))["coverage"][cg.OPTIONAL_EXTRAS_KEY]
    assert extras["langgraph"]["deselect_env"] == LANGGRAPH_DESELECT_ENV
    # The gate's importability verdict must agree with the one conftest deselects on,
    # whichever interpreter runs this: both true with the extra, both false without.
    assert cg._importable(extras["langgraph"]["import_name"]) is LANGGRAPH_AVAILABLE
    for prefix in extras["langgraph"]["path_prefixes"]:
        assert (cg.DEFAULT_REPO_ROOT / prefix).is_dir(), prefix


# Shadowing reproduction (own-directory on sys.path) lives in
# regression/test_coverage_gate_shadowing_regression.py (NS-11).

def test_a_namespace_stub_does_not_count_as_importable(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """A directory with no `__init__.py` is a namespace hit with nothing importable under it."""
    (tmp_path / "nsonly").mkdir()
    monkeypatch.syspath_prepend(str(tmp_path))
    importlib.invalidate_caches()
    assert cg._importable("nsonly") is False
    assert cg._importable("nsonly.graph") is False
    assert cg._importable("no_such_parent_for_tests.child") is False
    assert cg._importable("json") is True
    assert cg._importable("json.decoder") is True


def test_the_probe_restores_a_module_it_set_aside(monkeypatch: pytest.MonkeyPatch):
    """A caller that already imported the extra keeps its module object afterwards."""
    import json as real_json

    assert cg._importable("json") is True
    assert sys.modules["json"] is real_json


# --- fail-closed arcs of the per-file readers (tech-debt-hardening-plan R-TDH-25) ---


def test_per_file_enabled_without_a_coverage_block_fails_closed(tmp_path: Path, caplog):
    """``per_file_enabled`` decides whether a gate runs at all. A policy with no
    coverage block cannot answer that, and answering "off" would disable
    enforcement while the gate reported success -- so it exits 1 with the reason,
    like every other reader in the module."""
    policy = _write_json(tmp_path / "policy.json", {"limits": {}})
    with caplog.at_level(logging.ERROR, logger=SHARED_LOGGER), pytest.raises(SystemExit) as exc:
        cg.per_file_enabled(policy)
    assert exc.value.code == 1
    assert "no coverage block" in caplog.text


@pytest.mark.parametrize("entry", [{"missing_lines": [1]}, "not-an-object", None])
def test_check_per_file_entry_without_a_summary_fails_closed(tmp_path: Path, entry: object, caplog):
    """A files entry with no summary block is evidence the report was not produced
    the way the gate expects; per-file compliance cannot be proven from it, so the
    gate must exit 1 rather than skip the file and pass."""
    report = _write_json(tmp_path / "coverage.json", {"files": {"harness/shared/x.py": entry}})
    with caplog.at_level(logging.ERROR, logger=SHARED_LOGGER), pytest.raises(SystemExit) as exc:
        cg.check_per_file(report, 90.0)
    assert exc.value.code == 1
    assert "harness/shared/x.py has no summary block" in caplog.text


@pytest.mark.parametrize(
    "summary",
    [{"covered_lines": "9", "num_statements": 10}, {"covered_lines": 9}, {"covered_lines": 9.0, "num_statements": 10}],
)
def test_check_per_file_entry_with_non_integer_counters_fails_closed(tmp_path: Path, summary: dict, caplog):
    """Counters that are missing or not integers are not measured, they are guessed;
    the gate exits 1 naming the file instead of computing a percentage from them."""
    report = _write_json(tmp_path / "coverage.json", {"files": {"harness/shared/x.py": {"summary": summary}}})
    with caplog.at_level(logging.ERROR, logger=SHARED_LOGGER), pytest.raises(SystemExit) as exc:
        cg.check_per_file(report, 90.0)
    assert exc.value.code == 1
    assert "harness/shared/x.py lacks covered_lines/num_statements" in caplog.text


def test_a_prefix_without_a_trailing_slash_does_not_waive_siblings(tmp_path: Path):
    """Deleting one character from a policy prefix used to widen the waiver.

    `harness/shared/langgraph` (no slash) matched `langgraph_helpers.py` and
    `langgraphX.py` under a raw `str.startswith`. The policy check only asserts
    the prefix names a real directory, which the slashless form does, so nothing
    caught it — and widening a coverage waiver by one character is not a change
    a reviewer would notice.
    """
    waived: dict[str, tuple[str, ...]] = {"opt": ("harness/shared/langgraph",)}
    assert cg._waiving_extra("harness/shared/langgraph/nodes.py", waived) == "opt"
    assert cg._waiving_extra("harness/shared/langgraph", waived) == "opt", "the directory itself still matches"
    assert cg._waiving_extra("harness/shared/langgraph_helpers.py", waived) is None
    assert cg._waiving_extra("harness/shared/langgraphX.py", waived) is None


def test_a_waiver_covering_every_measured_file_is_not_a_pass(tmp_path: Path, caplog):
    """Absence of evidence is never a pass — this module's own contract.

    One policy edit (`path_prefixes: ["harness/"]`) waived every file while the
    gate still printed `[PASS]`, with a 0 in the count nobody reads.
    """
    report = _per_file_report(tmp_path)
    with caplog.at_level(logging.ERROR, logger=SHARED_LOGGER):
        assert cg.check_per_file(report, 90.0, {"opt": ("harness/",)}) is False
    assert "0 file(s) measured" in caplog.text


class TestMeasuredSetIsBounded:
    """R-GT-3: the omit list cannot silently shrink what the floors judge.

    `check_per_file` iterates whatever `coverage.json`'s `files` block holds, so
    adding a source file to `[tool.coverage.run] omit` drops it from the per-file
    floor *and* raises the aggregate, because the uncovered lines it contributed
    disappear. Every number improves and no gate objects. Its only emptiness
    guard fires when a waiver swallows the whole set, which is a different and
    much larger mistake.
    """

    def _tree(self, tmp_path: Path, measured: list[str]) -> tuple[Path, Path]:
        """A miniature repository: two source roots, a test tree, a report."""
        (tmp_path / "pkg").mkdir()
        (tmp_path / "pkg" / "tests").mkdir()
        (tmp_path / "pkg" / "alpha.py").write_text("x = 1\n", encoding="utf-8")
        (tmp_path / "pkg" / "beta.py").write_text("y = 2\n", encoding="utf-8")
        (tmp_path / "pkg" / "tests" / "test_alpha.py").write_text("z = 3\n", encoding="utf-8")
        (tmp_path / "pyproject.toml").write_text(
            '[tool.coverage.run]\nbranch = true\nsource = ["pkg"]\nomit = []\n\n[tool.other]\nk = 1\n',
            encoding="utf-8",
        )
        report = _write_json(
            tmp_path / "coverage.json",
            {"files": {path: {"summary": {"covered_lines": 1, "num_statements": 1}} for path in measured}},
        )
        return report, tmp_path / "pyproject.toml"

    def test_the_full_first_party_set_passes(self, tmp_path: Path) -> None:
        report, pyproject = self._tree(tmp_path, ["pkg/alpha.py", "pkg/beta.py"])
        assert cg.check_measured_set(report, tmp_path, pyproject) is True

    def test_a_source_file_dropped_from_the_report_fails_by_name(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        """The omit-list mutation: beta.py stops being measured."""
        report, pyproject = self._tree(tmp_path, ["pkg/alpha.py"])
        with caplog.at_level(logging.ERROR):
            assert cg.check_measured_set(report, tmp_path, pyproject) is False
        assert "pkg/beta.py" in caplog.text

    def test_a_test_file_counted_as_source_fails(self, tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
        """The inverse drift: test code measured as source inflates every number."""
        report, pyproject = self._tree(tmp_path, ["pkg/alpha.py", "pkg/beta.py", "pkg/tests/test_alpha.py"])
        with caplog.at_level(logging.ERROR):
            assert cg.check_measured_set(report, tmp_path, pyproject) is False
        assert "pkg/tests/test_alpha.py" in caplog.text

    def test_no_first_party_sources_fails_closed(self, tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
        """Absence of evidence is never a pass -- this module's own contract."""
        (tmp_path / "pyproject.toml").write_text(
            '[tool.coverage.run]\nsource = ["absent"]\n\n[tool.other]\nk = 1\n', encoding="utf-8"
        )
        report = _write_json(tmp_path / "coverage.json", {"files": {}})
        with caplog.at_level(logging.ERROR):
            assert cg.check_measured_set(report, tmp_path, tmp_path / "pyproject.toml") is False
        assert "vacuously" in caplog.text

    def test_a_report_without_a_files_block_fails(self, tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
        report, pyproject = self._tree(tmp_path, [])
        _write_json(report, {"totals": {}})
        with caplog.at_level(logging.ERROR):
            assert cg.check_measured_set(report, tmp_path, pyproject) is False

    def test_the_source_roots_are_read_from_the_coverage_table_only(self, tmp_path: Path) -> None:
        """An unscoped parse would take the first `source = [` in the file."""
        pyproject = tmp_path / "pyproject.toml"
        pyproject.write_text(
            '[tool.something]\nsource = ["wrong"]\n\n[tool.coverage.run]\nsource = ["right"]\n\n[tool.z]\nk = 1\n',
            encoding="utf-8",
        )
        assert cg.declared_source_roots(pyproject) == ["right"]

    @pytest.mark.parametrize(
        ("content", "why"),
        [
            ("[tool.other]\nk = 1\n\n[tool.z]\nj = 2\n", "no [tool.coverage.run] table"),
            ("[tool.coverage.run]\nbranch = true\n\n[tool.z]\nk = 1\n", "no source roots"),
        ],
    )
    def test_an_unusable_pyproject_exits_rather_than_defaulting(self, tmp_path: Path, content: str, why: str) -> None:
        pyproject = tmp_path / "pyproject.toml"
        pyproject.write_text(content, encoding="utf-8")
        with pytest.raises(SystemExit):
            cg.declared_source_roots(pyproject)

    def test_an_unreadable_pyproject_exits(self, tmp_path: Path) -> None:
        with pytest.raises(SystemExit):
            cg.declared_source_roots(tmp_path / "does-not-exist.toml")

    def test_the_coverage_table_may_be_the_last_table_in_the_file(self, tmp_path: Path) -> None:
        """Found by review: the lookahead required a following `[`, so a
        pyproject ending with [tool.coverage.run] matched nothing and the gate
        failed closed reporting "declares no table" -- accurate about the
        regex, wrong about the file. An adopter fork whose config ends there
        would have been unable to run the gate at all.
        """
        pyproject = tmp_path / "pyproject.toml"
        pyproject.write_text(
            '[tool.other]\nk = 1\n\n[tool.coverage.run]\nsource = ["pkg", "other"]\n',
            encoding="utf-8",
        )
        assert cg.declared_source_roots(pyproject) == ["pkg", "other"]

    def test_caches_and_test_trees_are_not_first_party(self, tmp_path: Path) -> None:
        (tmp_path / "pkg" / "__pycache__").mkdir(parents=True)
        (tmp_path / "pkg" / "__pycache__" / "cached.py").write_text("x = 1\n", encoding="utf-8")
        (tmp_path / "pkg" / "real.py").write_text("x = 1\n", encoding="utf-8")
        assert cg.first_party_sources(tmp_path, ["pkg"]) == {"pkg/real.py"}

    def test_a_declared_root_that_does_not_exist_contributes_nothing(self, tmp_path: Path) -> None:
        """Adopter forks declare roots they may not ship; that is not a failure here."""
        assert cg.first_party_sources(tmp_path, ["absent"]) == set()
