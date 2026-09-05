"""Branch arcs of ``harness/control-plane/regenerate_bundle_digests.py`` (R-TDH-25).

A sibling of ``test_regenerate_bundle_digests.py`` rather than part of it: that
module tests the script's behaviour through ``regenerate()``/``main()``, this one
tests the bootstrap and process-boundary arcs, which need ``sys.path`` and
``__file__`` manipulation the behavioural tests should not inherit. Colocated under
``harness/control-plane/tests/`` (R-TDH-26). The script is loaded by path through
``harness.shared.tests._helpers`` because ``harness/control-plane`` is not an
importable package name.

The three arcs are the ones its behavioural tests cannot reach by calling
``regenerate()``/``main()``: inserting the repo root when it is not importable,
the fallback logger declining to stack a second handler, and the ``__main__``
guard -- which is run against a fixture tree, never against the real bundle.
"""

from __future__ import annotations

import hashlib
import json
import logging
import sys
from collections.abc import Iterator
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

from harness.shared import json_logging
from harness.shared.tests._helpers import CONTROL_PLANE, REPO, imported_module

SCRIPT = CONTROL_PLANE / "regenerate_bundle_digests.py"

pytestmark = pytest.mark.governance


def _is_repo_root(entry: str) -> bool:
    try:
        return Path(entry or ".").resolve() == REPO
    except (OSError, ValueError):
        return False


@pytest.fixture
def regen() -> Iterator[ModuleType]:
    """The script under a private module name, unregistered again afterwards."""
    with imported_module(SCRIPT, "regenerate_bundle_digests_arcs_probe") as module:
        yield module


class TestGateLogger:
    def test_the_repo_root_is_inserted_when_it_is_not_importable(
        self, regen: ModuleType, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """``python harness/control-plane/regenerate_bundle_digests.py`` puts the
        script's own directory on sys.path, not the repository root, so
        ``harness.shared.json_logging`` is unimportable until the script inserts the
        root itself. It must insert it at the head and then hand back the shared gate
        logger (non-propagating, tagged handler), not the bare fallback."""
        monkeypatch.setattr(sys, "path", [entry for entry in sys.path if not _is_repo_root(entry)])
        assert not any(_is_repo_root(entry) for entry in sys.path), "precondition: root hidden"

        logger = regen._gate_logger()

        assert _is_repo_root(sys.path[0]), "the root was not inserted at the head of sys.path"
        assert logger.propagate is False
        assert any(getattr(handler, "_mango_gate_handler", False) for handler in logger.handlers)

    def test_the_fallback_logger_does_not_stack_handlers_across_calls(
        self, regen: ModuleType, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """When the shared logger cannot be configured the script degrades to a bare
        stderr logger. The first call attaches exactly one handler; a second call
        must reuse it -- otherwise every re-import in a session would duplicate
        each diagnostic line."""

        def unavailable(name: str | None = None) -> logging.Logger:
            raise RuntimeError("json_logging unavailable")

        monkeypatch.setattr(json_logging, "configure_gate_logging", unavailable)
        fallback = logging.getLogger(regen.__name__)
        monkeypatch.setattr(fallback, "handlers", [])

        first = regen._gate_logger()
        assert first is fallback
        assert first.propagate is False
        assert len(first.handlers) == 1 and isinstance(first.handlers[0], logging.StreamHandler)

        second = regen._gate_logger()
        assert second is first
        assert second.handlers == first.handlers[:1], "a second call added another handler"


class TestScriptEntryPoint:
    def test_running_the_script_regenerates_the_bundle_next_to_its_own_file(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
    ) -> None:
        """The ``__main__`` guard (``raise SystemExit(main())``) with the zero-argument
        defaults the Makefile uses. The module derives REPO/BUNDLE/STACK_ROOTS from
        its own ``__file__``, so the real source is compiled under its real filename
        (coverage attributes it) but executed with ``__file__`` pointing into a
        fixture tree -- a test must never rewrite the repository's bundle."""
        fixture_repo = tmp_path / "repo"
        script_home = fixture_repo / "harness" / "control-plane"
        script_home.mkdir(parents=True)
        stacks = {"node": b"node-bytes", "jvm": b"jvm-bytes"}
        for stack, content in stacks.items():
            root = fixture_repo / "harness" / stack
            root.mkdir()
            (root / "policy.json").write_bytes(content)
        bundle = script_home / "policy-bundle.example.json"
        bundle.write_text(
            json.dumps({"profiles": {stack: {"protected_files": {"policy.json": "stale"}} for stack in stacks}}),
            encoding="utf-8",
        )
        monkeypatch.setattr(sys, "path", list(sys.path))  # the script inserts its (fixture) root
        script_globals: dict[str, Any] = {"__name__": "__main__", "__file__": str(script_home / SCRIPT.name)}

        with pytest.raises(SystemExit) as exc:
            exec(compile(SCRIPT.read_text(encoding="utf-8"), str(SCRIPT), "exec"), script_globals)

        assert exc.value.code == 0
        written = json.loads(bundle.read_text(encoding="utf-8"))
        for stack, content in stacks.items():
            assert written["profiles"][stack]["protected_files"]["policy.json"] == hashlib.sha256(content).hexdigest()
        out = capsys.readouterr().out
        assert f"[PASS] Regenerated digests for {bundle}" in out
        assert "node: 1 protected file digests" in out
