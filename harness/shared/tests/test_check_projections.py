"""Tests for check_projections, importable since the policy-single-source
change (argparse under main()); covers the policy-loaded decision-ID grammar
and the projection drift verdicts."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from harness.shared import check_projections as cp

pytestmark = pytest.mark.governance


class TestDecisionIdRegex:
    def test_no_policy_file_uses_fallback(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        monkeypatch.setattr(cp, "POLICY_PATH", tmp_path / "absent.json")
        assert cp.decision_id_regex().pattern == cp.FALLBACK_ID_PATTERN

    def test_policy_pattern_is_loaded_and_converted(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        policy = tmp_path / "policy.json"
        policy.write_text(json.dumps({"decision_id_pattern": "^(ZZ-[0-9]+)$"}), encoding="utf-8")
        monkeypatch.setattr(cp, "POLICY_PATH", policy)
        regex = cp.decision_id_regex()
        assert regex.findall("see ZZ-7 and DEC-1") == ["ZZ-7"]

    @pytest.mark.parametrize(
        "content",
        [
            "{not json",
            json.dumps({}),
            json.dumps({"decision_id_pattern": "no-anchors"}),
            json.dumps({"decision_id_pattern": 42}),
        ],
    )
    def test_malformed_policy_fails_closed(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, content: str
    ) -> None:
        policy = tmp_path / "policy.json"
        policy.write_text(content, encoding="utf-8")
        monkeypatch.setattr(cp, "POLICY_PATH", policy)
        with pytest.raises(SystemExit, match="unusable decision_id_pattern"):
            cp.decision_id_regex()


class TestMainVerdicts:
    def _write(self, tmp_path: Path, cfg: dict, log: str = "DEC-000 recorded") -> list[str]:
        config = tmp_path / "projections.json"
        config.write_text(json.dumps(cfg), encoding="utf-8")
        decision_log = tmp_path / "decision-log.md"
        decision_log.write_text(log, encoding="utf-8")
        return ["--config", str(config), "--decision-log", str(decision_log)]

    def _run(self, monkeypatch: pytest.MonkeyPatch, argv: list[str]) -> None:
        monkeypatch.setattr("sys.argv", ["check_projections.py", *argv])
        cp.main()

    def test_disabled_with_logged_decision_passes(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture
    ) -> None:
        argv = self._write(tmp_path, {"enabled": False, "decision_id": "DEC-000"})
        with pytest.raises(SystemExit) as exc:
            self._run(monkeypatch, argv)
        assert exc.value.code == 0
        assert "not applicable under DEC-000" in capsys.readouterr().out

    def test_disabled_without_decision_fails(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        argv = self._write(tmp_path, {"enabled": False, "decision_id": "DEC-999"})
        with pytest.raises(SystemExit, match="disabled without a decision-log entry"):
            self._run(monkeypatch, argv)

    def test_missing_mapping_endpoint_fails(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        argv = self._write(
            tmp_path,
            {"enabled": True, "mappings": [{"source": str(tmp_path / "a"), "projection": str(tmp_path / "b")}]},
        )
        with pytest.raises(SystemExit, match="missing mapping endpoint"):
            self._run(monkeypatch, argv)

    def test_drifted_mapping_fails(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        a, b = tmp_path / "a.txt", tmp_path / "b.txt"
        a.write_text("one", encoding="utf-8")
        b.write_text("two", encoding="utf-8")
        argv = self._write(tmp_path, {"enabled": True, "mappings": [{"source": str(a), "projection": str(b)}]})
        with pytest.raises(SystemExit, match="drift"):
            self._run(monkeypatch, argv)

    def test_enabled_without_mappings_fails(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        argv = self._write(tmp_path, {"enabled": True, "mappings": []})
        with pytest.raises(SystemExit, match="enabled but no mappings"):
            self._run(monkeypatch, argv)

    def test_identical_mappings_pass(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture
    ) -> None:
        a, b = tmp_path / "a.txt", tmp_path / "b.txt"
        a.write_text("same", encoding="utf-8")
        b.write_text("same", encoding="utf-8")
        argv = self._write(tmp_path, {"enabled": True, "mappings": [{"source": str(a), "projection": str(b)}]})
        self._run(monkeypatch, argv)
        assert "projections: passed" in capsys.readouterr().out
