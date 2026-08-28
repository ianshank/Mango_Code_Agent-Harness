"""Tests for the traceability gate's failure diagnostics.

The gate previously reported only that an ID was "missing implementation and/or
test citation", which does not tell an operator which half to fix. These tests pin
the per-side detail, and pin that the original sentence still leads the message —
CI logs and `test_validators.py` both match on it.
"""

from __future__ import annotations

import importlib
import json
import logging
import os
from pathlib import Path

import pytest

# The package re-exports `check_traceability` as a *function*, shadowing the
# submodule name, so `from ... import check_traceability` yields the callable.
# Import the module explicitly to reach its internals.
ct = importlib.import_module("harness.shared.governance.check_traceability")

LEADING_SENTENCE = "traceability: requirement IDs missing implementation and/or test citation"


@pytest.fixture
def project(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A minimal tree with the layout the gate expects, entered as CWD.

    The gate resolves its config and globs relative to the working directory, so
    the fixture must chdir rather than pass paths.
    """
    (tmp_path / ".governance").mkdir()
    (tmp_path / "docs" / "specs").mkdir(parents=True)
    (tmp_path / "src").mkdir()
    (tmp_path / "tests").mkdir()
    (tmp_path / ".governance" / "traceability.json").write_text(
        json.dumps(
            {
                "spec_globs": ["docs/specs/**/*.md"],
                "implementation_globs": ["src/**/*.*"],
                "test_globs": ["tests/**/*.*"],
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)
    return tmp_path


def _write(project: Path, spec: str, impl: str = "", test: str = "") -> None:
    (project / "docs" / "specs" / "s.md").write_text(spec, encoding="utf-8")
    (project / "src" / "impl.py").write_text(impl, encoding="utf-8")
    (project / "tests" / "t.py").write_text(test, encoding="utf-8")


class TestPassingPath:
    def test_passes_when_every_id_is_cited_on_both_sides(self, project, capsys):
        _write(project, spec="R-ONE", impl="# covers R-ONE", test="# tests R-ONE")
        ct.check_traceability()
        assert "traceability: passed (1 requirements)" in capsys.readouterr().out


class TestFailureDiagnostics:
    def test_names_the_implementation_side_specifically(self, project):
        _write(project, spec="R-ONE", impl="", test="# tests R-ONE")
        with pytest.raises(SystemExit) as excinfo:
            ct.check_traceability()
        message = str(excinfo.value)
        assert "R-ONE: absent from implementation" in message
        assert "tests" not in message.split("R-ONE: absent from")[1].split("\n")[0]

    def test_names_the_test_side_specifically(self, project):
        _write(project, spec="R-ONE", impl="# covers R-ONE", test="")
        with pytest.raises(SystemExit) as excinfo:
            ct.check_traceability()
        assert "R-ONE: absent from tests" in str(excinfo.value)

    def test_names_both_sides_when_an_id_is_cited_nowhere(self, project):
        _write(project, spec="R-ONE", impl="", test="")
        with pytest.raises(SystemExit) as excinfo:
            ct.check_traceability()
        assert "R-ONE: absent from implementation and tests" in str(excinfo.value)

    def test_preserves_the_leading_sentence_other_tests_match_on(self, project):
        """Backward compatibility: the detail is appended, never a replacement."""
        _write(project, spec="R-ONE", impl="", test="")
        with pytest.raises(SystemExit) as excinfo:
            ct.check_traceability()
        assert str(excinfo.value).startswith(LEADING_SENTENCE)

    def test_reports_every_failing_id_not_just_the_first(self, project):
        _write(project, spec="R-ONE R-TWO R-THREE", impl="# covers R-TWO", test="")
        with pytest.raises(SystemExit) as excinfo:
            ct.check_traceability()
        message = str(excinfo.value)
        assert "R-ONE: absent from implementation and tests" in message
        assert "R-TWO: absent from tests" in message
        assert "R-THREE: absent from implementation and tests" in message

    def test_a_passing_id_is_not_listed_among_the_gaps(self, project):
        _write(project, spec="R-OK R-BAD", impl="# covers R-OK", test="# tests R-OK")
        with pytest.raises(SystemExit) as excinfo:
            ct.check_traceability()
        message = str(excinfo.value)
        assert "R-BAD" in message
        assert "R-OK:" not in message


class TestFailClosedInputs:
    def test_no_matching_spec_files_is_a_failure_not_a_pass(self, project):
        (project / "src" / "impl.py").write_text("", encoding="utf-8")
        with pytest.raises(SystemExit) as excinfo:
            ct.check_traceability()
        assert "no spec files matched" in str(excinfo.value)

    def test_specs_without_requirement_ids_is_a_failure_not_a_pass(self, project):
        _write(project, spec="prose with no identifiers", impl="", test="")
        with pytest.raises(SystemExit) as excinfo:
            ct.check_traceability()
        assert "specs contain no requirement IDs" in str(excinfo.value)


class TestDebugDiagnostics:
    def test_debug_reports_glob_match_counts_on_stderr(self, project, capsys, monkeypatch):
        """The fastest way to spot a glob scoped to the wrong tree."""
        monkeypatch.setenv("LOG_LEVEL", "DEBUG")
        reloaded = ct._gate_logger()
        reloaded.setLevel("DEBUG")
        for handler in reloaded.handlers:
            handler.setLevel("DEBUG")
        _write(project, spec="R-ONE", impl="# covers R-ONE", test="# tests R-ONE")
        ct.check_traceability()
        captured = capsys.readouterr()
        assert "spec_globs" in captured.err
        assert "matched" in captured.err
        # Diagnostics must never contaminate the verdict channel.
        assert "spec_globs" not in captured.out
        assert "traceability: passed" in captured.out


class TestGateLoggerDegradation:
    def test_logger_falls_back_instead_of_raising(self, monkeypatch):
        """Diagnostics must never be able to fail the gate: if the shared logging
        package cannot be imported, a plain logger is returned."""
        import builtins

        real_import = builtins.__import__

        def explode(name, *args, **kwargs):
            if "json_logging" in name:
                raise ImportError("simulated missing shared package")
            return real_import(name, *args, **kwargs)

        monkeypatch.setattr(builtins, "__import__", explode)
        logger = ct._gate_logger()
        # `assert logger is not None` cannot fail -- _gate_logger returns a
        # Logger or raises. Assert the properties the fallback exists for: a
        # usable logger that does not propagate into a root handler (which
        # would let a gate's diagnostics contaminate machine-read stdout).
        assert isinstance(logger, logging.Logger)
        assert logger.propagate is False
        logger.debug("must not raise")

    def test_repo_root_bootstrap_targets_the_actual_repository(self):
        """parents[3] must resolve to the repo root, or the sys.path insert is wrong."""
        module_path = Path(ct.__file__).resolve()
        assert (module_path.parents[3] / "harness" / "shared" / "json_logging.py").is_file()
        assert os.path.basename(module_path.parents[3]) != "harness"
