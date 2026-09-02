"""Branch arcs of ``harness/shared/governance/verify_zero_skips.py`` (R-TDH-25).

A sibling of ``test_verify_zero_skips.py``, which sits at the test size budget
(``limits.test_size_budget_lines``). That module drives the gate through the
``harness/shared/verify_zero_skips.py`` shim; the arcs here are the ones that
shim never reaches: the policy-absence probe's second-stage OSError, the
present-but-unusable decision-ID grammar, and the governance module's own
``__main__`` guard.
"""

from __future__ import annotations

import json
import runpy
import sys
from pathlib import Path

import pytest

from harness.shared.governance import verify_zero_skips as vzs
from harness.shared.tests._helpers import SHARED

GOVERNANCE_SCRIPT = SHARED / "governance" / "verify_zero_skips.py"

pytestmark = pytest.mark.governance


class TestPolicyAbsenceProbe:
    def test_an_unreadable_lstat_after_a_missing_stat_exits(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        """``stat()`` reports FileNotFoundError, then ``lstat()`` raises a *different*
        OSError (the path became unreadable between the two probes). That is not
        the adopter path: the gate must exit with the reason rather than fall back
        to the built-in grammar for a policy it could not inspect."""
        target = tmp_path / "governance-policy.json"
        real_lstat = Path.lstat

        def lstat_denied(self: Path):
            if self == target:
                raise PermissionError("lstat denied")
            return real_lstat(self)

        monkeypatch.setattr(Path, "lstat", lstat_denied)
        with pytest.raises(SystemExit, match="is not readable"):
            vzs._policy_is_absent(target, "zero-skip")

    def test_a_missing_path_is_absent(self, tmp_path: Path):
        """Control for the test above: with lstat answering honestly, the same
        missing path is the adopter path."""
        assert vzs._policy_is_absent(tmp_path / "governance-policy.json", "zero-skip") is True


class TestDecisionIdGrammar:
    @pytest.mark.parametrize(
        ("policy_text", "why"),
        [
            ('{"decision_id_pattern": "DEC-[0-9]+"}', "not in the anchored ^(...)$ form"),
            ('{"other": 1}', "decision_id_pattern missing"),
            ('{"decision_id_pattern": 7}', "decision_id_pattern is not a string"),
            ("{not json", "policy is not JSON"),
        ],
    )
    def test_a_present_but_unusable_pattern_fails_closed(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, policy_text: str, why: str
    ):
        """Every way the grammar can be present and unusable exits with the reason.
        Falling back to FALLBACK_ID_PATTERN here would let a corrupt policy widen
        which decision IDs a waiver may cite."""
        policy = tmp_path / "governance-policy.json"
        policy.write_text(policy_text, encoding="utf-8")
        monkeypatch.setattr(vzs, "_POLICY_PATH", policy)
        with pytest.raises(SystemExit, match="unusable decision_id_pattern") as exc:
            vzs._decision_id_regex()
        assert str(policy) in str(exc.value), why

    def test_a_usable_pattern_is_converted_to_the_search_form(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        """The anchored ``^(...)$`` grammar becomes a ``\\b(...)\\b`` search, so IDs
        are found inside prose and the built-in grammar is not consulted."""
        policy = tmp_path / "governance-policy.json"
        policy.write_text(json.dumps({"decision_id_pattern": "^(XYZ-[0-9]+)$"}), encoding="utf-8")
        monkeypatch.setattr(vzs, "_POLICY_PATH", policy)
        regex = vzs._decision_id_regex()
        assert regex.findall("see XYZ-12 and DEC-1") == ["XYZ-12"]


class TestScriptEntryPoint:
    def test_running_the_governance_module_as_a_script_dispatches_main(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
    ):
        """``python harness/shared/governance/verify_zero_skips.py ...`` must run the
        gate. The shim in harness/shared imports ``main`` and calls it itself, so
        this guard is only exercised by running the governance file directly."""
        log = tmp_path / "decision-log.md"
        log.write_text("Decision DEC-123\n", encoding="utf-8")
        waivers = tmp_path / "skip-waivers.json"
        waivers.write_text(json.dumps({"waivers": []}), encoding="utf-8")
        report = tmp_path / "vitest-results.json"
        report.write_text(json.dumps({"testResults": []}), encoding="utf-8")
        argv = ["--decision-log", str(log), "--waivers", str(waivers), "--vitest-json", str(report)]
        monkeypatch.setattr(sys, "argv", ["verify_zero_skips.py", *argv])
        runpy.run_path(str(GOVERNANCE_SCRIPT), run_name="__main__")
        assert capsys.readouterr().out.strip() == "zero-skip: passed"
