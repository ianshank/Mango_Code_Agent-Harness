"""In-process coverage for the ImportError bootstrap fallbacks.

Several modules carry a ``try: from harness.shared... except ImportError:``
bootstrap so a bare ``python harness/shared/<name>.py`` works from any CWD.
Under pytest those legs never fire: the repo root is on ``sys.path`` AND the
editable install registers a meta-path finder, so ``harness`` always resolves.
These tests hide both (plus the cached ``harness*`` modules) and re-run the
file via ``runpy`` so the fallback executes in-process, where coverage can see
it — the subprocess probes in ``test_shim_entrypoints`` prove the behavior but
are invisible to the coverage report.
"""

from __future__ import annotations

import runpy
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[3]
SHARED = REPO / "harness" / "shared"

pytestmark = pytest.mark.governance


def _resolves_to_repo(entry: str) -> bool:
    try:
        return Path(entry or ".").resolve() == REPO
    except (OSError, ValueError):
        return False


def _is_editable_finder(finder: object) -> bool:
    return "editable" in type(finder).__module__.lower() or "editable" in getattr(finder, "__name__", "").lower()


class _FailFirstHarnessImport:
    """Meta-path finder that fails the first ``harness*`` import, then defers.

    Simply hiding the repo root makes the failing import wander through
    namespace-package machinery, where coverage loses the line events for the
    ``except ImportError`` leg even though it executes. Raising cleanly from a
    finder keeps the same observable contract (first import fails, the retry
    after the bootstrap succeeds) while staying visible to coverage.
    """

    def __init__(self) -> None:
        self.fired = False

    def find_spec(self, name, path=None, target=None):
        if not self.fired and (name == "harness" or name.startswith("harness.")):
            self.fired = True
            raise ImportError("simulated bare-script environment: repo root not importable yet")
        return None


@pytest.fixture
def hidden_harness(monkeypatch: pytest.MonkeyPatch):
    """Make the first ``import harness`` fail as it does for a bare adopter script.

    Strips the repo root from ``sys.path``, drops the editable-install finder
    from ``sys.meta_path``, purges cached ``harness*`` modules, and arms a
    fail-once finder so the fallback's retry (after it inserts the repo root)
    is what succeeds. Everything is restored exactly afterwards, including
    modules the run re-imported.
    """
    saved_modules = dict(sys.modules)
    saved_path = list(sys.path)
    saved_meta = list(sys.meta_path)
    sys.path[:] = [p for p in saved_path if not _resolves_to_repo(p)]
    sys.meta_path[:] = [_FailFirstHarnessImport()] + [f for f in saved_meta if not _is_editable_finder(f)]
    for name in [n for n in sys.modules if n == "harness" or n.startswith("harness.")]:
        del sys.modules[name]
    sys.modules.pop("json_logging", None)
    try:
        yield
    finally:
        sys.path[:] = saved_path
        sys.meta_path[:] = saved_meta
        for name in [n for n in sys.modules if n not in saved_modules]:
            del sys.modules[name]
        sys.modules.update(saved_modules)


class TestCheckTraceabilityShimFallback:
    def test_import_error_leg_bootstraps_and_retries(self, hidden_harness):
        """Lines 7/11-14 of the shim: the first import fails, the repo root is
        resolved and inserted, and the retry import must then succeed."""
        ns = runpy.run_path(str(SHARED / "check_traceability.py"), run_name="shim_fallback")
        assert callable(ns["check_traceability"])
        assert str(REPO) in sys.path, "the fallback did not insert the repo root it resolved"

    def test_main_dispatch_runs_the_gate(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
    ):
        """The shim's __main__ leg calls the real gate (no sys.exit wrapper: the
        gate returns None on success). Run from a minimal repo whose spec,
        implementation, and test all cite the same requirement ID."""
        import json

        gov = tmp_path / ".governance"
        gov.mkdir()
        (gov / "traceability.json").write_text(
            json.dumps(
                {
                    "spec_globs": ["docs/specs/*.md"],
                    "implementation_globs": ["src/*.py"],
                    "test_globs": ["tests/*.py"],
                }
            ),
            encoding="utf-8",
        )
        for rel in ("docs/specs/feature.md", "src/feature.py", "tests/test_feature.py"):
            target = tmp_path / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text("R-123\n", encoding="utf-8")
        monkeypatch.chdir(tmp_path)
        runpy.run_path(str(SHARED / "check_traceability.py"), run_name="__main__")
        assert "traceability: passed" in capsys.readouterr().out


class TestCoverageGateFallback:
    def test_import_error_leg_uses_sibling_module(self, hidden_harness, monkeypatch: pytest.MonkeyPatch):
        """coverage_gate's fallback imports top-level ``json_logging``, which is
        how a direct ``python harness/shared/coverage_gate.py`` resolves it
        (the interpreter puts the script's directory on sys.path)."""
        monkeypatch.syspath_prepend(str(SHARED))
        ns = runpy.run_path(str(SHARED / "coverage_gate.py"), run_name="coverage_gate_fallback")
        assert callable(ns["main"])
        assert callable(ns["resolve_log_level"])


class TestCheckDedupFallback:
    def test_main_dispatch_with_fallback_import_detects_drift(
        self, hidden_harness, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ):
        """check_dedup.py's except-ImportError leg (top-level ``governance_json`` and
        ``json_logging``) plus its ``__main__`` dispatch, as ``python
        harness/shared/check_dedup.py`` runs for an adopter. The fixture repo carries a
        byte-identical stack copy, so exit 1 proves the fallback-imported gate actually
        checked something rather than passing vacuously."""
        for name in ("governance_json", "json_logging"):
            monkeypatch.delitem(sys.modules, name, raising=False)
        logic = "def compute():\n    return 1\n"
        for rel in ("harness/shared/thing.py", "harness/node/scripts/thing.py"):
            target = tmp_path / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(logic, encoding="utf-8")
        monkeypatch.syspath_prepend(str(SHARED))
        monkeypatch.setattr(sys, "argv", ["check_dedup.py", "--repo-root", str(tmp_path)])
        with pytest.raises(SystemExit) as exc:
            runpy.run_path(str(SHARED / "check_dedup.py"), run_name="__main__")
        assert exc.value.code == 1
        assert "governance_json" in sys.modules, "the fallback did not import the sibling module by bare name"
        assert "harness.shared.governance_json" not in sys.modules, "the package import succeeded; the leg was skipped"


class TestCheckPyCompatFallback:
    def test_main_dispatch_with_fallback_import_flags_a_violation(
        self, hidden_harness, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ):
        """check_py_compat.py's except-ImportError leg (top-level ``ast_visitors`` and
        ``json_logging``) reached the way a bare ``python harness/shared/check_py_compat.py``
        reaches it. A PEP 604 union in the fixture repo must still be found through the
        fallback-imported visitors: exit 1 is the proof the gate ran, not merely loaded."""
        for name in ("ast_visitors", "json_logging"):
            monkeypatch.delitem(sys.modules, name, raising=False)
        (tmp_path / "pkg").mkdir()
        (tmp_path / "pkg" / "mod.py").write_text("def f(x: str | None = None) -> int | None:\n    return None\n")
        monkeypatch.syspath_prepend(str(SHARED))
        monkeypatch.setattr(
            sys, "argv", ["check_py_compat.py", "--repo-root", str(tmp_path), "--min-version", "3.9"]
        )
        with pytest.raises(SystemExit) as exc:
            runpy.run_path(str(SHARED / "check_py_compat.py"), run_name="__main__")
        assert exc.value.code == 1
        assert "ast_visitors" in sys.modules, "the fallback did not import the sibling module by bare name"
        assert "harness.shared.ast_visitors" not in sys.modules, "the package import succeeded; the leg was skipped"


class TestValidateInvariantsMainFallback:
    def test_main_dispatch_with_fallback_import_passes(self, hidden_harness, monkeypatch: pytest.MonkeyPatch):
        """The ``__main__`` block's except-ImportError leg, plus the dispatch
        itself, exactly as ``python harness/shared/validate_invariants.py``
        runs for an adopter. The gate runs against this repository (the CLI
        takes no --repo-root); the attestation env keeps a dirty-but-permitted
        working tree from failing the protected-path check."""
        monkeypatch.syspath_prepend(str(SHARED))
        monkeypatch.setenv("ALLOW_GITHUB_CHANGES", "1")
        monkeypatch.setenv("GITHUB_BASE_REF", "")
        with pytest.raises(SystemExit) as exc:
            runpy.run_path(str(SHARED / "validate_invariants.py"), run_name="__main__")
        assert exc.value.code == 0
