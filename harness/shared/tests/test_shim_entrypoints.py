"""Branch coverage for the compatibility shims' bootstrap and __main__ legs.

Each `harness/shared/<name>.py` shim has two branches that ordinary package
imports never take: the `sys.path` insert (pytest always has the repo root on
the path already) and the `__main__` dispatch. With branch coverage enabled
those untaken legs are visible; these tests exercise them the way real callers
do -- `runpy` over the actual file -- rather than asserting on source text.
"""

from __future__ import annotations

import io
import json
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
    """Meta-path finder failing the first ``harness*`` import, then deferring.

    Since the shims moved to the import-first try/except bootstrap (spec:
    policy-single-source), stripping the repo root from sys.path is no longer
    enough to make the insert leg fire under pytest: the editable-install
    finder and the ``sys.modules`` cache still satisfy the first import. Same
    device as test_bootstrap_fallbacks."""

    def __init__(self) -> None:
        self.fired = False

    def find_spec(self, name, path=None, target=None):
        if not self.fired and (name == "harness" or name.startswith("harness.")):
            self.fired = True
            raise ImportError("simulated bare-script environment: repo root not importable yet")
        return None


def _run_shim_without_repo_root(monkeypatch: pytest.MonkeyPatch, shim: Path, run_name: str = "shim"):
    """Execute a shim in the bare-script environment its bootstrap exists for.

    The first ``harness`` import must fail (repo root off sys.path, editable
    finder removed, module cache purged, fail-once finder armed) so the
    except-leg resolves and inserts the repo root, and the retry import
    succeeds.
    """
    saved_modules = dict(sys.modules)
    monkeypatch.setattr(sys, "path", [p for p in sys.path if not _resolves_to_repo(p)])
    monkeypatch.setattr(
        sys, "meta_path", [_FailFirstHarnessImport()] + [f for f in sys.meta_path if not _is_editable_finder(f)]
    )
    for name in [n for n in sys.modules if n == "harness" or n.startswith("harness.")]:
        monkeypatch.delitem(sys.modules, name)
    try:
        return runpy.run_path(str(shim), run_name=run_name)
    finally:
        for name in [n for n in sys.modules if n not in saved_modules]:
            del sys.modules[name]
        sys.modules.update(saved_modules)


class TestBootstrapInsertBranch:
    def test_verify_zero_skips_shim_bootstraps_off_path(self, monkeypatch):
        namespace = _run_shim_without_repo_root(monkeypatch, SHARED / "verify_zero_skips.py")
        assert callable(namespace["verify_zero_skips_main"])
        assert str(REPO) in sys.path, "the shim did not insert the repo root it resolved"

    def test_pretooluse_guard_shim_bootstraps_off_path(self, monkeypatch):
        namespace = _run_shim_without_repo_root(monkeypatch, SHARED / "pretooluse_guard.py")
        assert callable(namespace["main"])

    def test_remotes_shim_bootstraps_off_path(self, monkeypatch):
        namespace = _run_shim_without_repo_root(monkeypatch, SHARED / "remotes.py")
        assert callable(namespace["main"])


class TestMainDispatchBranch:
    def test_pretooluse_guard_main_leg_blocks_dangerous_command(self, monkeypatch, capsys):
        """run_name='__main__' takes the dispatch branch; a dangerous command must
        exit non-zero, so the guard's verdict -- not just its importability -- is
        what this pins."""
        monkeypatch.setattr(
            sys, "stdin", io.StringIO(json.dumps({"tool_input": {"command": "git push --force origin main"}}))
        )
        with pytest.raises(SystemExit) as exc:
            runpy.run_path(str(SHARED / "pretooluse_guard.py"), run_name="__main__")
        assert exc.value.code not in (0, None)

    def test_pretooluse_guard_main_leg_allows_benign_command(self, monkeypatch):
        monkeypatch.setattr(
            sys, "stdin", io.StringIO(json.dumps({"tool_input": {"command": "git status"}}))
        )
        with pytest.raises(SystemExit) as exc:
            runpy.run_path(str(SHARED / "pretooluse_guard.py"), run_name="__main__")
        assert exc.value.code == 0

    def test_remotes_main_leg_checks_an_explicit_url(self, monkeypatch):
        """The __main__ branch must reach governance.remotes.main and apply the
        allowlist: an allowed URL exits 0 through the same dispatch a real
        `python harness/shared/remotes.py` invocation uses."""
        allowlist = REPO / "harness" / "node" / ".governance" / "allowed-remotes.txt"
        allowed = next(
            line.strip()
            for line in allowlist.read_text(encoding="utf-8").splitlines()
            if line.strip() and not line.startswith("#")
        )
        monkeypatch.setattr(
            sys, "argv", ["remotes.py", "--check-url", allowed, "--allowlist", str(allowlist)]
        )
        with pytest.raises(SystemExit) as exc:
            runpy.run_path(str(SHARED / "remotes.py"), run_name="__main__")
        assert exc.value.code == 0


class TestCheckTraceabilityShim:
    def test_bootstrap_is_load_bearing_without_site_packages(self, tmp_path: Path):
        """The one shim that had NO sys.path bootstrap.

        In this checkout the package is also importable via the editable install,
        which masks a missing bootstrap for every in-process test. `python -S`
        disables site processing, so the shim's own bootstrap is the only way
        `harness.shared` can resolve -- exactly an adopter's bare-invocation
        environment. Gutting the bootstrap makes this fail with ImportError.
        """
        import subprocess

        probe = (
            "import runpy; "
            f"ns = runpy.run_path({str(SHARED / 'check_traceability.py')!r}); "
            "assert callable(ns['check_traceability'])"
        )
        result = subprocess.run(
            [sys.executable, "-S", "-c", probe], cwd=tmp_path, capture_output=True, text=True
        )
        assert result.returncode == 0, result.stderr
