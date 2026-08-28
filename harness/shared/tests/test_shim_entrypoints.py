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


def _run_shim_without_repo_root(monkeypatch: pytest.MonkeyPatch, shim: Path, run_name: str = "shim"):
    """Execute a shim with the repo root absent from sys.path.

    That is the environment the bootstrap exists for (a bare
    `python harness/shared/<shim>.py` from anywhere): the insert branch must
    fire and the delegated import must then succeed.
    """
    stripped = [p for p in sys.path if Path(p).resolve() != REPO]
    monkeypatch.setattr(sys, "path", stripped)
    return runpy.run_path(str(shim), run_name=run_name)


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
