"""Tests for harness/shared/check_py_compat.py - legacy-runtime compatibility gate."""

import json
import logging
from pathlib import Path

import pytest

from harness.shared import check_py_compat as cc

WORKFLOW = """\
name: CI
on: [push]
jobs:
  build:
    runs-on: ubuntu-latest
    strategy:
      matrix:
        python-version: ["3.9", "3.10", "3.11"]
    steps:
      - uses: actions/checkout@v4
"""

PEP604_RUNTIME = """\
def f(x: str | None = None) -> int | None:
    return None
"""

PEP604_WITH_FUTURE = """\
from __future__ import annotations


def f(x: str | None = None) -> int | None:
    return None
"""

LEGACY_SAFE = """\
from typing import Optional


def f(x: Optional[str] = None) -> Optional[int]:
    return None
"""

DATETIME_UTC = """\
from datetime import UTC, datetime

print(datetime.now(tz=UTC))
"""


@pytest.fixture
def repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.delenv("MIN_PYTHON", raising=False)
    root = tmp_path / "repo"
    wf = root / ".github" / "workflows"
    wf.mkdir(parents=True)
    (wf / "ci.yml").write_text(WORKFLOW, encoding="utf-8")
    (root / "harness" / "shared").mkdir(parents=True)
    return root


def _write(root: Path, rel: str, text: str) -> Path:
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")
    return p


# --- minimum version resolution ---

def test_resolve_min_version_from_workflow_matrix(repo: Path):
    assert cc.resolve_min_version(repo) == (3, 9)


def test_resolve_min_version_picks_lowest_across_workflows(repo: Path):
    _write(repo, ".github/workflows/other.yml", WORKFLOW.replace('"3.9", "3.10", "3.11"', '"3.8"'))
    assert cc.resolve_min_version(repo) == (3, 8)


def test_resolve_min_version_explicit_override_wins(repo: Path):
    assert cc.resolve_min_version(repo, override="3.12") == (3, 12)


def test_resolve_min_version_env_override(repo: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("MIN_PYTHON", "3.11")
    assert cc.resolve_min_version(repo) == (3, 11)


def test_resolve_min_version_ignores_bad_override(repo: Path, caplog):
    with caplog.at_level(logging.WARNING, logger=cc.logger.name):
        assert cc.resolve_min_version(repo, override="banana") == (3, 9)
    assert "banana" in caplog.text


def test_resolve_min_version_none_without_matrix(tmp_path: Path, caplog):
    with caplog.at_level(logging.WARNING, logger=cc.logger.name):
        assert cc.resolve_min_version(tmp_path) is None


def test_parse_matrix_versions_regex_fallback():
    """Parsing must work without PyYAML, since CI images may not install it."""
    line = '        python-version: ["3.9", "3.13"]\n'
    assert cc._parse_matrix_versions(line) == [(3, 9), (3, 13)]


# --- AST detection ---

def test_find_pep604_detects_arg_and_return():
    import ast

    assert cc.find_pep604(ast.parse(PEP604_RUNTIME)) == [1]


def test_find_pep604_clean_on_legacy_safe_code():
    import ast

    assert cc.find_pep604(ast.parse(LEGACY_SAFE)) == []


def test_has_future_annotations():
    import ast

    assert cc.has_future_annotations(ast.parse(PEP604_WITH_FUTURE)) is True
    assert cc.has_future_annotations(ast.parse(PEP604_RUNTIME)) is False


def test_find_datetime_utc():
    import ast

    assert cc.find_datetime_utc(ast.parse(DATETIME_UTC)) == [1]
    assert cc.find_datetime_utc(ast.parse(LEGACY_SAFE)) == []


# --- run ---

def test_run_flags_pep604_without_future(repo: Path):
    _write(repo, "pkg/mod.py", PEP604_RUNTIME)
    report = cc.run(repo, (3, 9))
    assert not report.ok
    assert any("PEP 604" in v for v in report.violations)


def test_run_accepts_pep604_with_future(repo: Path):
    _write(repo, "pkg/mod.py", PEP604_WITH_FUTURE)
    assert cc.run(repo, (3, 9)).ok


def test_run_accepts_legacy_safe_code(repo: Path):
    _write(repo, "pkg/mod.py", LEGACY_SAFE)
    assert cc.run(repo, (3, 9)).ok


def test_run_flags_datetime_utc(repo: Path):
    _write(repo, "pkg/mod.py", DATETIME_UTC)
    report = cc.run(repo, (3, 9))
    assert any("3.11+" in v for v in report.violations)


def test_run_allows_datetime_utc_when_min_is_311(repo: Path):
    _write(repo, "pkg/mod.py", DATETIME_UTC)
    assert cc.run(repo, (3, 11)).ok


def test_run_allows_pep604_when_min_is_310(repo: Path):
    """The gate must relax automatically as the matrix moves forward."""
    _write(repo, "pkg/mod.py", PEP604_RUNTIME)
    assert cc.run(repo, (3, 10)).ok


def test_run_noop_without_declared_minimum(repo: Path):
    _write(repo, "pkg/mod.py", PEP604_RUNTIME)
    report = cc.run(repo, None)
    assert report.ok
    assert report.scanned == 0


def test_run_skips_configured_directories(repo: Path):
    _write(repo, ".venv/lib/bad.py", PEP604_RUNTIME)
    assert cc.run(repo, (3, 9)).ok


def test_run_honors_policy_skip_dirs(repo: Path):
    _write(repo, "vendor/bad.py", PEP604_RUNTIME)
    _write(
        repo,
        "harness/shared/governance-policy.json",
        json.dumps({"py_compat": {"skip_dirs": ["vendor"]}}),
    )
    assert cc.run(repo, (3, 9), skip_dirs=cc.load_skip_dirs(repo)).ok


def test_run_reports_syntax_errors(repo: Path):
    _write(repo, "pkg/broken.py", "def f(:\n")
    report = cc.run(repo, (3, 9))
    assert any("syntax error" in v for v in report.violations)


# --- CLI ---

def test_main_returns_zero_when_compatible(repo: Path):
    _write(repo, "pkg/mod.py", LEGACY_SAFE)
    assert cc.main(["--repo-root", str(repo)]) == 0


def test_main_returns_one_on_violation(repo: Path):
    _write(repo, "pkg/mod.py", PEP604_RUNTIME)
    assert cc.main(["--repo-root", str(repo)]) == 1


def test_main_json_report(repo: Path, capsys):
    _write(repo, "pkg/mod.py", PEP604_RUNTIME)
    cc.main(["--repo-root", str(repo), "--json"])
    payload = json.loads(capsys.readouterr().out)
    assert payload["ok"] is False
    assert payload["min_version"] == "3.9"
    assert payload["violations"]


def test_main_min_version_flag_relaxes_gate(repo: Path):
    _write(repo, "pkg/mod.py", PEP604_RUNTIME)
    assert cc.main(["--repo-root", str(repo), "--min-version", "3.10"]) == 0


def test_report_to_dict_shape():
    payload = cc.CompatReport(min_version=(3, 9), scanned=2, violations=[]).to_dict()
    assert payload == {"ok": True, "min_version": "3.9", "scanned": 2, "violations": []}


def test_real_repository_is_compatible_with_its_declared_minimum():
    """The gate must pass against the actual tree, at whatever minimum the matrix declares."""
    root = cc.DEFAULT_REPO_ROOT
    min_version = cc.resolve_min_version(root)
    assert min_version is not None, "CI workflow must declare a python-version matrix"
    report = cc.run(root, min_version)
    assert report.ok, f"compatibility violations: {report.violations}"
    assert report.scanned > 0


def test_parse_matrix_versions_import_error(monkeypatch: pytest.MonkeyPatch):
    import builtins
    real_import = builtins.__import__
    def fake_import(name, *args, **kwargs):
        if name == "yaml":
            raise ImportError("no yaml")
        return real_import(name, *args, **kwargs)
    monkeypatch.setattr(builtins, "__import__", fake_import)
    assert cc._parse_matrix_versions('        python-version: ["3.9"]\n') == [(3, 9)]

def test_resolve_min_version_read_error(repo: Path, monkeypatch: pytest.MonkeyPatch, caplog):
    monkeypatch.setattr(Path, "read_text", lambda *args, **kwargs: 1/0)
    with caplog.at_level(logging.DEBUG, logger=cc.logger.name):
        cc.resolve_min_version(repo)
    assert "Could not read" in caplog.text

def test_load_skip_dirs_fails_closed_on_malformed_policy(repo: Path, caplog):
    """Silently using the built-in skip set could skip directories the policy meant
    to scan. The old test asserted that fail-open behaviour."""
    _write(repo, "harness/shared/governance-policy.json", "{ bad json")
    with caplog.at_level(logging.ERROR, logger=cc.logger.name):
        with pytest.raises(SystemExit) as excinfo:
            cc.load_skip_dirs(repo)
    assert excinfo.value.code == 1
    assert "Malformed governance policy" in caplog.text


def test_load_skip_dirs_uses_defaults_when_policy_is_absent(repo: Path):
    """An absent policy is the adopter path and still legitimately defaults."""
    assert cc.load_skip_dirs(repo) == frozenset(cc.DEFAULT_SKIP_DIRS)

def test_run_read_file_error(repo: Path, monkeypatch: pytest.MonkeyPatch, caplog):
    """An unreadable *source file* is skipped with a diagnostic, not fatal.

    `skip_dirs` is passed explicitly so the patched `read_text` only stands in for
    the per-file read this test is about. Patching it globally would also hit the
    policy read inside `load_skip_dirs`, which now fails closed by design -- the
    test would then pass for the wrong reason (or fail for an unrelated one).
    `OSError` is the realistic failure here: a permission or I/O error, which is
    what the `except` clause has to survive in production.
    """
    _write(repo, "pkg/mod.py", "print(1)")
    monkeypatch.setattr(
        Path, "read_text", lambda *args, **kwargs: (_ for _ in ()).throw(OSError("boom"))
    )
    with caplog.at_level(logging.DEBUG, logger=cc.logger.name):
        report = cc.run(repo, (3, 9), skip_dirs=frozenset(cc.DEFAULT_SKIP_DIRS))
    assert "Skipping unreadable" in caplog.text
    assert report.scanned == 0


def test_load_skip_dirs_fails_closed_on_an_unreadable_policy(
    repo: Path, monkeypatch: pytest.MonkeyPatch
):
    """Present-but-unreadable is corruption, not the adopter path.

    Distinct from the absent-policy case: `FileNotFoundError` is a subclass of
    `OSError`, so the two legs are only separable if ordering is preserved. This
    pins that ordering.
    """
    (repo / cc.POLICY_RELPATH).write_text(json.dumps({"py_compat": {}}), encoding="utf-8")
    monkeypatch.setattr(
        Path, "read_text", lambda *args, **kwargs: (_ for _ in ()).throw(PermissionError("denied"))
    )
    with pytest.raises(SystemExit) as exc:
        cc.load_skip_dirs(repo)
    assert exc.value.code == 1

def test_main_block(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr("sys.argv", ["check_py_compat.py", "--min-version", "3.12"])
    with pytest.raises(SystemExit) as exc:
        import runpy
        runpy.run_path(str(cc.DEFAULT_REPO_ROOT / "harness" / "shared" / "check_py_compat.py"), run_name="__main__")
    assert exc.value.code == 0


def test_find_pep604_assignments(repo: Path):
    import ast
    code_alias = "MyType = str | None\nflags = 1 | 2\n"
    tree = ast.parse(code_alias)
    assert cc.find_pep604_assignments(tree) == [1]
    _write(repo, "pkg/alias.py", "Alias = str | int\n")
    report = cc.run(repo, (3, 9))
    assert not report.ok
    assert any("runtime type alias" in v for v in report.violations)



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
        [sys.executable, str(Path(cc.__file__).resolve()), "--repo-root", str(repo)],
        env={**os.environ, "LOG_LEVEL": "BOGUS"},
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    assert "Unknown level" not in result.stderr


def test_load_skip_dirs_fails_closed_on_a_non_object_policy(repo: Path):
    """Valid JSON that is not an object previously escaped as a raw AttributeError."""
    (repo / cc.POLICY_RELPATH).write_text("[]", encoding="utf-8")
    with pytest.raises(SystemExit) as exc:
        cc.load_skip_dirs(repo)
    assert exc.value.code == 1
