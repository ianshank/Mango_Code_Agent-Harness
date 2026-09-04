"""Tests for harness/shared/check_dedup.py - the per-stack shim drift gate.

Each test builds a throwaway repo layout so the gate is exercised against real files
rather than mocks, and so a future refactor of the real tree cannot silently pass.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

import pytest

from harness.shared import check_dedup as cd
from harness.shared.tests.conftest import write_text_file

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


_write = write_text_file


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
        ("# from harness.shared.governance.thing import main\n", None),
        ("syntax error :::", None),
    ],
)
def test_classify_shim(text: str, expected):
    assert cd.classify_shim(text) == expected


def test_classify_shim_verifies_target_stem():
    shared_thing = Path("/path/to/harness/shared/thing.py")
    shared_other = Path("/path/to/harness/shared/other.py")
    # SHIM_IMPORT imports harness.shared.governance.thing
    assert cd.classify_shim(SHIM_IMPORT, shared_module=shared_thing) == "import"
    assert cd.classify_shim(SHIM_IMPORT, shared_module=shared_other) is None
    # SHIM_RUNPY runs thing.py
    assert cd.classify_shim(SHIM_RUNPY, shared_module=shared_thing) == "runpy"
    assert cd.classify_shim(SHIM_RUNPY, shared_module=shared_other) is None


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


def test_load_config_env_may_only_tighten_the_policy(repo: Path, monkeypatch: pytest.MonkeyPatch):
    """Replaces `test_load_config_env_overrides_policy`, which pinned that
    `MAX_SHIM_LINES=99` raised a policy budget of 12 — so anyone who could set
    an environment variable could switch the dedup gate off while it still
    printed `[PASS] N per-stack script(s) delegate` (R-CQ-8).

    Tightening keeps working, because a stricter local run is a real use and
    cannot weaken what the policy states."""
    _policy(repo, {"max_shim_lines": 12})
    monkeypatch.setenv("MAX_SHIM_LINES", "99")
    assert cd.load_config(repo).max_shim_lines == 12, "an override must not raise the budget"
    monkeypatch.setenv("MAX_SHIM_LINES", "5")
    assert cd.load_config(repo).max_shim_lines == 5, "an override must still tighten it"


def test_load_config_says_why_it_ignored_a_loosening_override(
    repo: Path, monkeypatch: pytest.MonkeyPatch, caplog
):
    """A silently ignored override is its own trap: the caller believes the
    budget moved and reads the PASS as meaning something it does not."""
    _policy(repo, {"max_shim_lines": 12})
    monkeypatch.setenv("MAX_SHIM_LINES", "99")
    with caplog.at_level(logging.WARNING, logger=cd.logger.name):
        cd.load_config(repo)
    assert "only tighten" in caplog.text and "99" in caplog.text and "12" in caplog.text


def test_load_config_argument_overrides_env(repo: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("MAX_SHIM_LINES", "99")
    assert cd.load_config(repo, max_shim_lines=7).max_shim_lines == 7


def test_load_config_ignores_bad_env(repo: Path, monkeypatch: pytest.MonkeyPatch, caplog):
    monkeypatch.setenv("MAX_SHIM_LINES", "many")
    with caplog.at_level(logging.WARNING, logger=cd.logger.name):
        assert cd.load_config(repo).max_shim_lines == cd.DEFAULT_MAX_SHIM_LINES
    assert "MAX_SHIM_LINES" in caplog.text


def test_load_config_fails_closed_on_malformed_policy(repo: Path, caplog):
    """A policy that exists but cannot be parsed is corruption, not an adopter default.

    This previously degraded to DEFAULT_MAX_SHIM_LINES, which silently relaxed the
    shim budget on exactly the input that should stop the gate. The old test
    asserted that fail-open behaviour; it encoded the defect.
    """
    _write(repo / "harness" / "shared" / "governance-policy.json", "{not json")
    with caplog.at_level(logging.ERROR, logger=cd.logger.name):
        with pytest.raises(SystemExit) as excinfo:
            cd.load_config(repo)
    assert excinfo.value.code == 1
    assert "Malformed governance policy" in caplog.text


def test_load_config_uses_defaults_when_policy_is_absent(repo: Path):
    """An absent policy is the adopter path and still legitimately defaults."""
    assert cd.load_config(repo).max_shim_lines == cd.DEFAULT_MAX_SHIM_LINES


def test_load_config_reads_a_distinguishable_policy_value(repo: Path):
    """Proves the policy is read at all, rather than coinciding with the default."""
    _write(repo / "harness" / "shared" / "governance-policy.json",
           '{"dedup": {"max_shim_lines": 1}}')
    assert cd.load_config(repo).max_shim_lines == 1


def test_load_config_fails_closed_on_unreadable_policy(repo: Path, caplog):
    """`read_json_object`'s "unreadable" classification is proven correct by
    test_governance_json.py directly; what is untested is check_dedup.py's own
    handling of that outcome -- it must raise closed like "malformed", not slip
    through as though the policy were merely absent.

    A directory in place of the file is a portable way to force a non-missing
    OSError (IsADirectoryError): unlike a chmod'd file it fires identically
    whether or not the test happens to run as root.
    """
    (repo / "harness" / "shared" / "governance-policy.json").mkdir(parents=True)
    with caplog.at_level(logging.ERROR, logger=cd.logger.name):
        with pytest.raises(SystemExit) as excinfo:
            cd.load_config(repo)
    assert excinfo.value.code == 1
    assert "Could not read governance policy" in caplog.text


def test_load_config_ignores_a_wrongly_typed_max_shim_lines(repo: Path):
    """`isinstance(..., int)` guards the assignment -- a policy author who
    quotes the number ("12" instead of 12) must degrade to the module default,
    not raise and not silently coerce the string."""
    _policy(repo, {"max_shim_lines": "12"})
    assert cd.load_config(repo).max_shim_lines == cd.DEFAULT_MAX_SHIM_LINES


def test_load_config_ignores_a_wrongly_typed_exempt(repo: Path):
    """`isinstance(..., list)` guards the assignment -- a policy author who
    writes a bare string instead of a one-element list must degrade to no
    exemptions, not iterate the string's characters as filenames."""
    _policy(repo, {"exempt": "thing.py"})
    assert cd.load_config(repo).exempt == frozenset()


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


def test_run_honors_a_full_relative_path_exemption(repo: Path):
    """`run()` checks `script.name in cfg.exempt or rel in cfg.exempt` -- the
    bare-filename form is covered above; this is the other half, a policy
    author who disambiguates by writing the whole repo-relative path instead
    (needed when two stacks both ship a same-named script and only one should
    be exempt)."""
    _write(repo / "harness" / "shared" / "thing.py", REAL_LOGIC)
    _write(repo / "harness" / "node" / "scripts" / "thing.py", REAL_LOGIC)
    _policy(repo, {"exempt": ["harness/node/scripts/thing.py"]})
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


def test_cli_survives_a_bogus_log_level(repo: Path):
    """LOG_LEVEL=BOGUS previously crashed the gate with ValueError before any check ran.

    Subprocess deliberately: under pytest the root logger already has a handler,
    and `logging.basicConfig` only applies `level` when there is none -- an
    in-process version of this test passes identically with and without the fix.
    """
    import os
    import subprocess
    import sys

    result = subprocess.run(
        [sys.executable, str(Path(cd.__file__).resolve()), "--repo-root", str(repo)],
        env={**os.environ, "LOG_LEVEL": "BOGUS"},
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    assert "Unknown level" not in result.stderr


def test_load_config_fails_closed_on_a_non_object_policy(repo: Path, caplog):
    """Valid JSON that is not an object previously escaped as a raw AttributeError."""
    _write(repo / "harness" / "shared" / "governance-policy.json", "[]")
    with caplog.at_level(logging.ERROR, logger=cd.logger.name):
        with pytest.raises(SystemExit) as excinfo:
            cd.load_config(repo)
    assert excinfo.value.code == 1
    assert "Malformed governance policy" in caplog.text


# --- classify_shim: the delegation spellings the docstring promises but no shim in
# the tree happens to use (tech-debt-hardening-plan R-TDH-25). Each is a real way an
# adopter can write a shim; a classifier that only recognised the two spellings the
# repository uses today would fail their gate with "not a delegating shim".

SHIM_IMPORT_STATEMENT = """\
import harness.shared.governance.thing as _impl

main = _impl.main
"""

SHIM_RUN_PATH_NAME = """\
from pathlib import Path
from runpy import run_path

_shared = Path(__file__).resolve().parents[2] / "shared"
run_path(str(_shared / "thing.py"), run_name="__main__")
"""


def test_classify_shim_accepts_an_import_statement():
    """`import harness.shared...` (an ``ast.Import``) is the second import spelling
    the module docstring accepts; only the ``from ... import`` form had a test."""
    thing = Path("/x/harness/shared/governance/thing.py")
    other = Path("/x/harness/shared/other.py")
    assert cd.classify_shim(SHIM_IMPORT_STATEMENT) == "import"
    assert cd.classify_shim(SHIM_IMPORT_STATEMENT, shared_module=thing) == "import"
    assert cd.classify_shim(SHIM_IMPORT_STATEMENT, shared_module=other) is None


def test_classify_shim_scans_every_alias_of_an_import_statement():
    """A single ``import a, b`` names two modules. The alias whose stem is not the
    target must not end the scan (it is skipped, not rejected), and the one that
    matches must classify; a scan that stopped at the first alias would misreport
    a valid shim as drift."""
    thing = Path("/x/harness/shared/governance/thing.py")
    text = "import harness.shared.other, harness.shared.governance.thing as _impl\n"
    assert cd.classify_shim(text, shared_module=thing) == "import"
    assert cd.classify_shim(text, shared_module=Path("/x/harness/shared/absent.py")) is None


def test_classify_shim_accepts_a_bare_run_path_call():
    """``from runpy import run_path; run_path(...)`` is an ``ast.Name`` call, not an
    ``ast.Attribute`` one, and reaches the runpy classification through its own leg."""
    thing = Path("/x/harness/shared/thing.py")
    other = Path("/x/harness/shared/other.py")
    assert cd.classify_shim(SHIM_RUN_PATH_NAME) == "runpy"
    assert cd.classify_shim(SHIM_RUN_PATH_NAME, shared_module=thing) == "runpy"
    assert cd.classify_shim(SHIM_RUN_PATH_NAME, shared_module=other) is None


def test_classify_shim_ignores_run_path_of_a_non_shared_target():
    """A ``run_path`` whose argument names no shared module is not delegation:
    a stack script that runs a local helper must still be reported as drift."""
    text = 'import runpy\nrunpy.run_path("tools/local_helper.py", run_name="__main__")\n'
    assert cd.classify_shim(text) is None
    assert cd.classify_shim(text, shared_module=Path("/x/harness/shared/local_helper.py")) is None


def test_classify_shim_treats_an_unrenderable_run_path_argument_as_no_delegation(monkeypatch):
    """``ast.unparse`` failing on the call argument must read as "no shared reference
    found", never as a gate crash -- classification is not allowed to be the thing
    that fails the dedup gate. The import spelling, which never unparses, must be
    unaffected, proving the failure is scoped to the argument it could not render."""
    def boom(node: object) -> str:
        raise ValueError("unrenderable node")

    monkeypatch.setattr(cd.ast, "unparse", boom)
    assert cd.classify_shim(SHIM_RUNPY) is None
    assert cd.classify_shim(SHIM_IMPORT) == "import"


# --- check_script: I/O failures on either side of the comparison ---

def test_check_script_reports_an_unreadable_script(repo: Path):
    """A stack script that cannot be read is itself a failure with a reason, not a
    traceback. A directory named like a script is a portable way to force a
    non-missing read error (IsADirectoryError) whether or not the test runs as root
    -- and ``scripts_dir.glob("*.py")`` really does yield such a directory."""
    shared = _write(repo / "harness" / "shared" / "thing.py", REAL_LOGIC)
    script = repo / "harness" / "node" / "scripts" / "thing.py"
    script.mkdir(parents=True)
    reason = cd.check_script(script, shared, cd.load_config(repo))
    assert reason is not None and "could not read" in reason
    assert reason.startswith("harness/node/scripts/thing.py")


def test_check_script_still_reports_drift_when_the_byte_comparison_fails(repo: Path, caplog):
    """The byte comparison only refines the message. If the shared side cannot be
    read as bytes, the script is still reported as "not a delegating shim" -- the
    verdict must not depend on a diagnostic that failed."""
    script = _write(repo / "harness" / "node" / "scripts" / "thing.py", REAL_LOGIC)
    shared = repo / "harness" / "shared" / "thing.py"
    shared.mkdir(parents=True)
    with caplog.at_level(logging.DEBUG, logger=cd.logger.name):
        reason = cd.check_script(script, shared, cd.load_config(repo))
    assert reason is not None and "not a delegating shim" in reason
    assert "byte-identical" not in reason
    assert "Could not compare bytes" in caplog.text
