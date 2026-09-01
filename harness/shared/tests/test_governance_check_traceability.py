"""Tests for governance/check_traceability: requirement traceability gate."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from harness.shared.governance.check_traceability import TRACEABILITY_CONFIG, check_traceability


def _scaffold_traceability(root: Path, *, spec_text: str, impl_text: str, test_text: str) -> None:
    """Build a traceability config and file tree under ``root``."""
    gov = root / ".governance"
    gov.mkdir(parents=True, exist_ok=True)

    specs = root / "docs" / "specs"
    specs.mkdir(parents=True, exist_ok=True)
    (specs / "spec.md").write_text(spec_text, encoding="utf-8")

    src = root / "src"
    src.mkdir(parents=True, exist_ok=True)
    (src / "impl.py").write_text(impl_text, encoding="utf-8")

    tests = root / "tests"
    tests.mkdir(parents=True, exist_ok=True)
    (tests / "test_impl.py").write_text(test_text, encoding="utf-8")

    config = {
        "spec_globs": [str(specs / "*.md")],
        "implementation_globs": [str(src / "*.py")],
        "test_globs": [str(tests / "*.py")],
    }
    (root / TRACEABILITY_CONFIG).write_text(json.dumps(config), encoding="utf-8")


class TestCheckTraceability:
    """Exercises the bidirectional traceability gate."""

    def test_all_cited_passes(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
    ) -> None:
        _scaffold_traceability(
            tmp_path,
            spec_text="R-FOO-1 and C-BAR-2 are required",
            impl_text="# R-FOO-1 implemented here\n# C-BAR-2 implemented",
            test_text="# R-FOO-1 tested\n# C-BAR-2 tested",
        )
        monkeypatch.chdir(tmp_path)
        check_traceability()  # no SystemExit
        assert "passed" in capsys.readouterr().out

    def test_missing_implementation_citation_fails(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        _scaffold_traceability(
            tmp_path,
            spec_text="R-FOO-1 is required",
            impl_text="# no references",
            test_text="# R-FOO-1 tested",
        )
        monkeypatch.chdir(tmp_path)
        with pytest.raises(SystemExit) as exc_info:
            check_traceability()
        assert "R-FOO-1" in str(exc_info.value)
        assert "implementation" in str(exc_info.value)

    def test_missing_test_citation_fails(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        _scaffold_traceability(
            tmp_path,
            spec_text="R-FOO-1 is required",
            impl_text="# R-FOO-1 implemented",
            test_text="# no references",
        )
        monkeypatch.chdir(tmp_path)
        with pytest.raises(SystemExit) as exc_info:
            check_traceability()
        assert "R-FOO-1" in str(exc_info.value)
        assert "tests" in str(exc_info.value)

    def test_no_specs_matched_fails(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        gov = tmp_path / ".governance"
        gov.mkdir(parents=True, exist_ok=True)
        config = {"spec_globs": ["nonexistent/*.md"], "implementation_globs": [], "test_globs": []}
        (tmp_path / TRACEABILITY_CONFIG).write_text(json.dumps(config), encoding="utf-8")
        monkeypatch.chdir(tmp_path)
        with pytest.raises(SystemExit) as exc_info:
            check_traceability()
        assert "no spec files" in str(exc_info.value).lower()

    def test_specs_with_no_requirement_ids_fails(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        _scaffold_traceability(
            tmp_path,
            spec_text="No requirement IDs here",
            impl_text="nothing",
            test_text="nothing",
        )
        monkeypatch.chdir(tmp_path)
        with pytest.raises(SystemExit) as exc_info:
            check_traceability()
        assert "no requirement ids" in str(exc_info.value).lower()
