"""Tests for harness/shared/check_dedup.py - the per-stack shim drift gate.

Each test builds a throwaway repo layout so the gate is exercised against real files
rather than mocks, and so a future refactor of the real tree cannot silently pass.
"""

import json
import logging
from pathlib import Path

import pytest

from harness.shared import check_dedup as cd

SHIM_IMPORT = """\
import sys
from pathlib import Path

_repo_root = Path(__file__).resolve().parent.parent.parent
if str(_repo_root) not in sys.path:
    sys.path.insert(0, str(_repo_root))

from harness.shared.governance.thing import main

__all__ = ["main"]
"""

SHIM_RUNPY = """\
import runpy
from pathlib import Path

_shared = Path(__file__).resolve().parents[2] / "shared"
runpy.run_path(str(_shared / "thing.py"), run_name="__main__")
"""

REAL_LOGIC = """\
def compute(a, b):
    total = 0
    for i in range(a, b):
        total += i
    return total


if __name__ == "__main__":
    print(compute(1, 10))
"""


@pytest.fixture
def repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A minimal repo: harness/shared plus node and jvm stacks with scripts/."""
    monkeypatch.delenv("MAX_SHIM_LINES", raising=False)
    root = tmp_path / "repo"
    (root / "harness" / "shared" / "governance").mkdir(parents=True)
    for stack in ("node", "jvm"):
        (root / "harness" / stack / "scripts").mkdir(parents=True)
    return root


def _write(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def _policy(root: Path, dedup: dict) -> Path:
    return _write(
        root / "harness" / "shared" / "governance-policy.json",
        json.dumps({"protected_paths": [], "dedup": dedup}),
    )


# --- discovery ---

def test_discover_stacks_finds_stacks_with_scripts(repo: Path):
    assert cd.discover_stacks(repo) == ["jvm", "node"]


def test_discover_stacks_excludes_shared_and_dirs_without_scripts(repo: Path):
    (repo / "harness" / "docs").mkdir()
    assert "shared" not in cd.discover_stacks(repo)
    assert "docs" not in cd.discover_stacks(repo)


def test_discover_stacks_empty_when_no_harness_dir(tmp_path: Path):
    assert cd.discover_stacks(tmp_path / "nope") == []


def test_find_shared_module_prefers_top_level(repo: Path):
    top = _write(repo / "harness" / "shared" / "thing.py", REAL_LOGIC)
    _write(repo / "harness" / "shared" / "governance" / "thing.py", REAL_LOGIC)
    assert cd.find_shared_module(repo / "harness" / "shared", "thing") == top


def test_find_shared_module_falls_back_to_governance_package(repo: Path):
    gov = _write(repo / "harness" / "shared" / "governance" / "thing.py", REAL_LOGIC)
    assert cd.find_shared_module(repo / "harness" / "shared", "thing") == gov


def test_find_shared_module_returns_none_when_absent(repo: Path):
    assert cd.find_shared_module(repo / "harness" / "shared", "ghost") is None


# --- classify_shim ---

@pytest.mark.parametrize(
    "text,expected",
    [
        (SHIM_IMPORT, "import"),
        (SHIM_RUNPY, "runpy"),
        (REAL_LOGIC, None),
        ("import os\n", None),
    ],
)
def test_classify_shim(text: str, expected):
    assert cd.classify_shim(text) == expected


# --- config resolution ---

def test_load_config_defaults_without_policy(repo: Path):
    cfg = cd.load_config(repo)
    assert cfg.max_shim_lines == cd.DEFAULT_MAX_SHIM_LINES
    assert cfg.exempt == frozenset()


def test_load_config_reads_policy(repo: Path):
    _policy(repo, {"max_shim_lines": 12, "exempt": ["json_logging.py"]})
    cfg = cd.load_config(repo)
    assert cfg.max_shim_lines == 12
    assert "json_logging.py" in cfg.exempt


def test_load_config_env_overrides_policy(repo: Path, monkeypatch: pytest.MonkeyPatch):
    _policy(repo, {"max_shim_lines": 12})
    monkeypatch.setenv("MAX_SHIM_LINES", "99")
    assert cd.load_config(repo).max_shim_lines == 99


def test_load_config_argument_overrides_env(repo: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("MAX_SHIM_LINES", "99")
    assert cd.load_config(repo, max_shim_lines=7).max_shim_lines == 7


def test_load_config_ignores_bad_env(repo: Path, monkeypatch: pytest.MonkeyPatch, caplog):
    monkeypatch.setenv("MAX_SHIM_LINES", "many")
    with caplog.at_level(logging.WARNING, logger=cd.logger.name):
        assert cd.load_config(repo).max_shim_lines == cd.DEFAULT_MAX_SHIM_LINES
    assert "MAX_SHIM_LINES" in caplog.text


def test_load_config_survives_malformed_policy(repo: Path, caplog):
    _write(repo / "harness" / "shared" / "governance-policy.json", "{not json")
    with caplog.at_level(logging.WARNING, logger=cd.logger.name):
        cfg = cd.load_config(repo)
    assert cfg.max_shim_lines == cd.DEFAULT_MAX_SHIM_LINES


# --- check_script ---

def test_check_script_accepts_import_shim(repo: Path):
    _write(repo / "harness" / "shared" / "thing.py", REAL_LOGIC)
    script = _write(repo / "harness" / "node" / "scripts" / "thing.py", SHIM_IMPORT)
    cfg = cd.load_config(repo)
    assert cd.check_script(script, repo / "harness" / "shared" / "thing.py", cfg) is None


def test_check_script_accepts_runpy_shim(repo: Path):
    _write(repo / "harness" / "shared" / "thing.py", REAL_LOGIC)
    script = _write(repo / "harness" / "node" / "scripts" / "thing.py", SHIM_RUNPY)
    cfg = cd.load_config(repo)
    assert cd.check_script(script, repo / "harness" / "shared" / "thing.py", cfg) is None


def test_check_script_rejects_byte_identical_copy(repo: Path):
    shared = _write(repo / "harness" / "shared" / "thing.py", REAL_LOGIC)
    script = _write(repo / "harness" / "node" / "scripts" / "thing.py", REAL_LOGIC)
    reason = cd.check_script(script, shared, cd.load_config(repo))
    assert reason is not None and "byte-identical copy" in reason


def test_check_script_rejects_divergent_copy(repo: Path):
    shared = _write(repo / "harness" / "shared" / "thing.py", REAL_LOGIC)
    script = _write(repo / "harness" / "node" / "scripts" / "thing.py", REAL_LOGIC + "\nEXTRA = 1\n")
    reason = cd.check_script(script, shared, cd.load_config(repo))
    assert reason is not None and "not a delegating shim" in reason


def test_check_script_rejects_oversized_shim(repo: Path):
    shared = _write(repo / "harness" / "shared" / "thing.py", REAL_LOGIC)
    fat = SHIM_IMPORT + "\n".join(f"# filler {i}" for i in range(80)) + "\n"
    script = _write(repo / "harness" / "node" / "scripts" / "thing.py", fat)
    reason = cd.check_script(script, shared, cd.load_config(repo))
    assert reason is not None and "shim budget" in reason


def test_check_script_budget_is_configurable(repo: Path):
    """A shim that fails a tight budget must pass a generous one (no hard-coded threshold)."""
    shared = _write(repo / "harness" / "shared" / "thing.py", REAL_LOGIC)
    script = _write(repo / "harness" / "node" / "scripts" / "thing.py", SHIM_IMPORT)
    assert cd.check_script(script, shared, cd.load_config(repo, max_shim_lines=3)) is not None
    assert cd.check_script(script, shared, cd.load_config(repo, max_shim_lines=200)) is None


def test_two_identical_shims_are_not_drift(repo: Path):
    """Regression: shared/X.py and stack/X.py may both be shims onto governance/X.py."""
    _write(repo / "harness" / "shared" / "governance" / "thing.py", REAL_LOGIC)
    shared_shim = _write(repo / "harness" / "shared" / "thing.py", SHIM_IMPORT)
    script = _write(repo / "harness" / "node" / "scripts" / "thing.py", SHIM_IMPORT)
    assert script.read_bytes() == shared_shim.read_bytes()
    assert cd.check_script(script, shared_shim, cd.load_config(repo)) is None


# --- run / report ---

def test_run_passes_on_clean_layout(repo: Path):
    _write(repo / "harness" / "shared" / "thing.py", REAL_LOGIC)
    for stack in ("node", "jvm"):
        _write(repo / "harness" / stack / "scripts" / "thing.py", SHIM_IMPORT)
    report = cd.run(cd.load_config(repo))
    assert report.ok
    assert len(report.checked) == 2
    assert report.failures == []


def test_run_reports_each_drifted_stack(repo: Path):
    _write(repo / "harness" / "shared" / "thing.py", REAL_LOGIC)
    for stack in ("node", "jvm"):
        _write(repo / "harness" / stack / "scripts" / "thing.py", REAL_LOGIC)
    report = cd.run(cd.load_config(repo))
    assert not report.ok
    assert len(report.failures) == 2


def test_run_skips_scripts_without_shared_counterpart(repo: Path):
    _write(repo / "harness" / "node" / "scripts" / "stack_only.py", REAL_LOGIC)
    report = cd.run(cd.load_config(repo))
    assert report.ok
    assert "harness/node/scripts/stack_only.py" in report.skipped
    assert report.checked == []


def test_run_honors_policy_exemptions(repo: Path):
    _write(repo / "harness" / "shared" / "thing.py", REAL_LOGIC)
    _write(repo / "harness" / "node" / "scripts" / "thing.py", REAL_LOGIC)
    _policy(repo, {"exempt": ["thing.py"]})
    report = cd.run(cd.load_config(repo))
    assert report.ok
    assert "harness/node/scripts/thing.py" in report.skipped


def test_report_to_dict_shape(repo: Path):
    payload = cd.DedupReport(checked=["a"], failures=[], skipped=["b"]).to_dict()
    assert payload == {"ok": True, "checked": ["a"], "failures": [], "skipped": ["b"]}


# --- CLI ---

def test_main_returns_zero_on_clean_repo(repo: Path):
    _write(repo / "harness" / "shared" / "thing.py", REAL_LOGIC)
    _write(repo / "harness" / "node" / "scripts" / "thing.py", SHIM_IMPORT)
    assert cd.main(["--repo-root", str(repo)]) == 0


def test_main_returns_one_on_drift(repo: Path):
    _write(repo / "harness" / "shared" / "thing.py", REAL_LOGIC)
    _write(repo / "harness" / "node" / "scripts" / "thing.py", REAL_LOGIC)
    assert cd.main(["--repo-root", str(repo)]) == 1


def test_main_json_output_is_parseable(repo: Path, capsys):
    _write(repo / "harness" / "shared" / "thing.py", REAL_LOGIC)
    _write(repo / "harness" / "node" / "scripts" / "thing.py", SHIM_IMPORT)
    cd.main(["--repo-root", str(repo), "--json"])
    payload = json.loads(capsys.readouterr().out)
    assert payload["ok"] is True
    assert payload["checked"] == ["harness/node/scripts/thing.py"]


def test_main_respects_max_shim_lines_flag(repo: Path):
    _write(repo / "harness" / "shared" / "thing.py", REAL_LOGIC)
    _write(repo / "harness" / "node" / "scripts" / "thing.py", SHIM_IMPORT)
    assert cd.main(["--repo-root", str(repo), "--max-shim-lines", "2"]) == 1


def test_real_repository_has_no_shim_drift():
    """The gate must pass against the actual tree it governs."""
    cfg = cd.load_config(cd.DEFAULT_REPO_ROOT)
    report = cd.run(cfg)
    assert report.ok, f"shim drift detected: {report.failures}"
    assert report.checked, "expected the real repo to contain per-stack governance shims"
