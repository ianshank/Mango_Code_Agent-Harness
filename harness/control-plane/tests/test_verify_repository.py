"""Tests for the control-plane repository verifier CLI (verify_repository.py).

Same contract as its sibling tool_broker_reference test: importing is
side-effect free and the ``__main__`` dispatch keeps the flags, output and exit
codes it had when argparse ran at module scope. Loaded via importlib / runpy
because the directory is hyphenated. Colocated here by
tech-debt-hardening-plan R-TDH-26 (was test_control_plane_clis.py).
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import runpy
import sys
from pathlib import Path

import pytest

CONTROL_PLANE = Path(__file__).resolve().parents[1]
VERIFIER = CONTROL_PLANE / "verify_repository.py"
SCRIPT = VERIFIER

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


class TestVerifyRepository:
    @pytest.fixture
    def repo(self, tmp_path: Path) -> Path:
        """A repo whose .governance files and one protected file all match the bundle."""
        repo = tmp_path / "repo"
        gov = repo / ".governance"
        gov.mkdir(parents=True)
        (gov / "policy.json").write_text('{"policy": true}', encoding="utf-8")
        (gov / "agent-policy.json").write_text('{"agents": []}', encoding="utf-8")
        (repo / "pyproject.toml").write_text("[tool]\n", encoding="utf-8")
        (repo / "guarded.py").write_text("x = 1\n", encoding="utf-8")
        policy_digest = hashlib.sha256((gov / "policy.json").read_bytes()).hexdigest()
        (gov / "root-of-trust.json").write_text(
            json.dumps({"external_policy_ref": "https://example.com/policy", "policy_sha256": policy_digest}),
            encoding="utf-8",
        )
        return repo

    def _bundle(self, repo: Path, **overrides) -> dict:
        gov = repo / ".governance"
        bundle = {
            "governance_policy_sha256": hashlib.sha256((gov / "policy.json").read_bytes()).hexdigest(),
            "agent_policy_sha256": hashlib.sha256((gov / "agent-policy.json").read_bytes()).hexdigest(),
            "profiles": {
                "python": {
                    "marker": "pyproject.toml",
                    "protected_files": {
                        "guarded.py": hashlib.sha256((repo / "guarded.py").read_bytes()).hexdigest()
                    },
                }
            },
        }
        bundle.update(overrides)
        return bundle

    def _write_bundle(self, tmp_path: Path, bundle: dict) -> Path:
        path = tmp_path / "bundle.json"
        path.write_text(json.dumps(bundle), encoding="utf-8")
        return path

    def test_matching_digests_pass(self, monkeypatch, capsys, tmp_path: Path, repo: Path):
        bundle = self._write_bundle(tmp_path, self._bundle(repo))
        _run_main(monkeypatch, VERIFIER, ["--repo", repo, "--bundle", bundle])
        assert "external-governance: protected digests match (python)" in capsys.readouterr().out

    def test_missing_protected_file_denies(self, monkeypatch, tmp_path: Path, repo: Path):
        bundle = self._write_bundle(tmp_path, self._bundle(repo, agent_policy_sha256="0" * 64))
        (repo / ".governance" / "agent-policy.json").unlink()
        with pytest.raises(SystemExit, match="DENY: required protected file missing"):
            _run_main(monkeypatch, VERIFIER, ["--repo", repo, "--bundle", bundle])

    def test_invalid_digest_length_denies(self, monkeypatch, tmp_path: Path, repo: Path):
        bundle = self._write_bundle(tmp_path, self._bundle(repo, governance_policy_sha256="abc"))
        with pytest.raises(SystemExit, match="DENY: protected bundle has invalid digest"):
            _run_main(monkeypatch, VERIFIER, ["--repo", repo, "--bundle", bundle])

    def test_digest_mismatch_denies(self, monkeypatch, tmp_path: Path, repo: Path):
        stale = self._bundle(repo)
        stale["profiles"]["python"]["protected_files"]["guarded.py"] = "f" * 64
        bundle = self._write_bundle(tmp_path, stale)
        with pytest.raises(SystemExit, match="DENY: digest mismatch for guarded.py"):
            _run_main(monkeypatch, VERIFIER, ["--repo", repo, "--bundle", bundle])

    def test_no_matching_profile_denies(self, monkeypatch, tmp_path: Path, repo: Path):
        stale = self._bundle(repo)
        stale["profiles"]["python"]["marker"] = "does-not-exist.toml"
        bundle = self._write_bundle(tmp_path, stale)
        with pytest.raises(
            SystemExit, match=r"DENY: cannot identify exactly one protected stack profile \(matched 0\)",
        ):
            _run_main(monkeypatch, VERIFIER, ["--repo", repo, "--bundle", bundle])

    def test_two_matching_profiles_denies(self, monkeypatch, tmp_path: Path, repo: Path):
        stale = self._bundle(repo)
        stale["profiles"]["duplicate"] = dict(stale["profiles"]["python"])
        bundle = self._write_bundle(tmp_path, stale)
        with pytest.raises(SystemExit, match=r"matched 2"):
            _run_main(monkeypatch, VERIFIER, ["--repo", repo, "--bundle", bundle])

    def test_empty_protected_file_manifest_denies(self, monkeypatch, tmp_path: Path, repo: Path):
        stale = self._bundle(repo)
        stale["profiles"]["python"]["protected_files"] = {}
        bundle = self._write_bundle(tmp_path, stale)
        with pytest.raises(SystemExit, match="DENY: protected profile has no file manifest"):
            _run_main(monkeypatch, VERIFIER, ["--repo", repo, "--bundle", bundle])

    def test_missing_root_of_trust_denies(self, monkeypatch, tmp_path: Path, repo: Path):
        (repo / ".governance" / "root-of-trust.json").unlink()
        bundle = self._write_bundle(tmp_path, self._bundle(repo))
        with pytest.raises(SystemExit, match="DENY: project root-of-trust declaration is missing"):
            _run_main(monkeypatch, VERIFIER, ["--repo", repo, "--bundle", bundle])

    def test_root_of_trust_digest_mismatch_denies(self, monkeypatch, tmp_path: Path, repo: Path):
        rot = repo / ".governance" / "root-of-trust.json"
        rot.write_text(
            json.dumps({"external_policy_ref": "https://example.com/policy", "policy_sha256": "e" * 64}),
            encoding="utf-8",
        )
        bundle = self._write_bundle(tmp_path, self._bundle(repo))
        with pytest.raises(SystemExit, match="DENY: project root-of-trust digest does not match"):
            _run_main(monkeypatch, VERIFIER, ["--repo", repo, "--bundle", bundle])

    def test_root_of_trust_without_external_ref_denies(self, monkeypatch, tmp_path: Path, repo: Path):
        gov = repo / ".governance"
        policy_digest = hashlib.sha256((gov / "policy.json").read_bytes()).hexdigest()
        (gov / "root-of-trust.json").write_text(
            json.dumps({"policy_sha256": policy_digest}), encoding="utf-8"
        )
        bundle = self._write_bundle(tmp_path, self._bundle(repo))
        with pytest.raises(SystemExit, match="DENY: project root-of-trust declaration has no external_policy_ref"):
            _run_main(monkeypatch, VERIFIER, ["--repo", repo, "--bundle", bundle])

    def test_digest_helper_matches_hashlib(self, tmp_path: Path):
        module = _load(VERIFIER)
        target = tmp_path / "f.txt"
        target.write_bytes(b"payload")
        assert module.digest(target) == hashlib.sha256(b"payload").hexdigest()
