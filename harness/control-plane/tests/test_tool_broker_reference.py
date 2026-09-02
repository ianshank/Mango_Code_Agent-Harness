"""Tests for the control-plane reference PDP CLI (tool_broker_reference.py).

The script previously ran argparse at module scope and was unimportable; it is
wrapped in ``main()`` under a ``__main__`` guard with identical CLI behaviour
(same flags, same output, same exit codes). Importing is side-effect free, and
the ``__main__`` dispatch drives the same allow/deny matrix as before. The
module lives in a hyphenated directory, so it is loaded via importlib / runpy.
Colocated here by tech-debt-hardening-plan R-TDH-26 (was test_control_plane_clis.py).
"""

from __future__ import annotations

import importlib.util
import json
import runpy
import sys
from pathlib import Path

import pytest

CONTROL_PLANE = Path(__file__).resolve().parents[1]
BROKER = CONTROL_PLANE / "tool_broker_reference.py"
SCRIPT = BROKER

pytestmark = pytest.mark.governance


def _load(path: Path):
    spec = importlib.util.spec_from_file_location(path.stem, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _run_main(monkeypatch: pytest.MonkeyPatch, script: Path, args: list) -> None:
    """Execute a CLI's __main__ dispatch with the given argv, in-process."""
    monkeypatch.setattr(sys, "argv", [script.name] + [str(a) for a in args])
    runpy.run_path(str(script), run_name="__main__")



def test_import_has_no_side_effects(capsys: pytest.CaptureFixture):
    """Importing must neither parse argv nor exit; it only defines main()."""
    module = _load(SCRIPT)
    assert callable(module.main)
    out = capsys.readouterr()
    assert out.out == "" and out.err == ""


class TestToolBroker:
    @pytest.fixture
    def policy(self, tmp_path: Path) -> Path:
        path = tmp_path / "agent-policy.json"
        path.write_text(
            json.dumps(
                {
                    "agents": [
                        {
                            "id": "implementer",
                            "allowed_actions": ["edit", "push"],
                            "human_approval_required_for": ["push"],
                        },
                        {"id": "planner", "allowed_actions": ["plan"]},
                    ]
                }
            ),
            encoding="utf-8",
        )
        return path

    def test_allowed_action_prints_allow(self, monkeypatch, capsys, policy: Path):
        _run_main(monkeypatch, BROKER, ["--policy", policy, "--agent", "implementer", "--action", "edit"])
        assert capsys.readouterr().out.strip() == "ALLOW"

    def test_unknown_agent_denies(self, monkeypatch, policy: Path):
        with pytest.raises(SystemExit, match="DENY: unknown agent identity"):
            _run_main(monkeypatch, BROKER, ["--policy", policy, "--agent", "ghost", "--action", "edit"])

    def test_ungranted_action_denies(self, monkeypatch, policy: Path):
        with pytest.raises(SystemExit, match="DENY: action not granted to this agent"):
            _run_main(monkeypatch, BROKER, ["--policy", policy, "--agent", "planner", "--action", "push"])

    def test_high_risk_action_without_human_approval_denies(self, monkeypatch, policy: Path):
        with pytest.raises(SystemExit, match="DENY: human approval required"):
            _run_main(monkeypatch, BROKER, ["--policy", policy, "--agent", "implementer", "--action", "push"])

    def test_high_risk_action_with_human_approval_allows(self, monkeypatch, capsys, policy: Path):
        _run_main(
            monkeypatch,
            BROKER,
            ["--policy", policy, "--agent", "implementer", "--action", "push", "--human-approved"],
        )
        assert capsys.readouterr().out.strip() == "ALLOW"

    def test_missing_required_flag_exits_with_usage_error(self, monkeypatch, policy: Path):
        with pytest.raises(SystemExit) as exc:
            _run_main(monkeypatch, BROKER, ["--policy", policy, "--agent", "planner"])
        assert exc.value.code == 2  # argparse usage error, unchanged by the restructure


# ---------------------------------------------------------------------------
# verify_repository: protected-digest verification matrix
# ---------------------------------------------------------------------------
