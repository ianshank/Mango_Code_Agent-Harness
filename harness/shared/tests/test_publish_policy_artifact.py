"""Tests for the policy-artifact publisher (harness/control-plane).

Requirement Citations: R-MMI-8..10, C-MMI-6
(docs/specs/mangomas-integration-core.md).

The module lives in a hyphenated directory, so it is loaded via importlib.
Loading must have no side effects (argparse stays inside main()) — pinned by
test_import_has_no_side_effects. CLI tests run through a real subprocess from
the repo root so the sys.path bootstrap is exercised as shipped, not masked
by pytest's pythonpath.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import logging
import os
import subprocess
import sys
from pathlib import Path

import pytest

_MODULE_PATH = Path(__file__).resolve().parent.parent.parent / "control-plane" / "publish_policy_artifact.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("publish_policy_artifact", _MODULE_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


ppa = _load_module()


@pytest.fixture(autouse=True)
def _restore_root_logging():
    """setup_json_logging() replaces all root handlers (killing pytest's log
    capture); snapshot and restore them around every test in this module."""
    root = logging.getLogger()
    handlers = list(root.handlers)
    level = root.level
    yield
    root.handlers[:] = handlers
    root.setLevel(level)


@pytest.fixture
def policy_repo(tmp_path: Path) -> Path:
    """A minimal repo root carrying both governed policy files."""
    for rel, content in (
        (ppa.POLICY_SOURCE, '{"policy_id": "test-policy", "coverage": {"lines": 90}}'),
        ("harness/shared/agent-policy.json", '{"schema_version": "2.0.0"}'),
    ):
        path = tmp_path / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    return tmp_path


# ---------------------------------------------------------------------------
# Import safety
# ---------------------------------------------------------------------------


def test_import_has_no_side_effects(capsys: pytest.CaptureFixture) -> None:
    _load_module()  # a second, fresh load
    out = capsys.readouterr()
    assert out.out == "" and out.err == ""


# ---------------------------------------------------------------------------
# build_artifact (R-MMI-8)
# ---------------------------------------------------------------------------


class TestBuild:
    def test_digests_and_identity(self, policy_repo: Path) -> None:
        artifact = ppa.build_artifact(policy_repo)
        assert artifact["schema_version"] == ppa.ARTIFACT_SCHEMA_VERSION
        assert artifact["artifact_id"] == ppa.ARTIFACT_ID
        assert artifact["policy_id"] == "test-policy"  # read from content, not a constant
        raw = (policy_repo / ppa.POLICY_SOURCE).read_bytes()
        assert artifact["policy_version"] == hashlib.sha256(raw).hexdigest()[: ppa.POLICY_VERSION_HEX_LEN]
        for rel in ppa.POLICY_FILES:
            file_raw = (policy_repo / rel).read_bytes()
            assert artifact["files"][rel]["sha256"] == hashlib.sha256(file_raw).hexdigest()
            assert artifact["files"][rel]["bytes"] == len(file_raw)
        assert artifact["attestation"] is None

    def test_schema_version_is_first_serialized_key(self, policy_repo: Path) -> None:
        assert json.dumps(ppa.build_artifact(policy_repo)).startswith('{"schema_version"')

    def test_missing_policy_file_denies(self, policy_repo: Path) -> None:
        (policy_repo / "harness/shared/agent-policy.json").unlink()
        with pytest.raises(SystemExit, match="DENY: missing policy file"):
            ppa.build_artifact(policy_repo)

    def test_unparseable_policy_source_denies(self, policy_repo: Path) -> None:
        (policy_repo / ppa.POLICY_SOURCE).write_text("not json", encoding="utf-8")
        with pytest.raises(SystemExit, match="DENY: unparseable policy source"):
            ppa.build_artifact(policy_repo)


# ---------------------------------------------------------------------------
# check_artifact tamper matrix (R-MMI-9)
# ---------------------------------------------------------------------------


@pytest.mark.governance
class TestCheck:
    def test_clean_round_trip_passes(self, policy_repo: Path) -> None:
        artifact = ppa.build_artifact(policy_repo)
        ppa.check_artifact(policy_repo, artifact)  # no exception

    def test_byte_flip_in_tree_denies(self, policy_repo: Path) -> None:
        artifact = ppa.build_artifact(policy_repo)
        target = policy_repo / ppa.POLICY_SOURCE
        target.write_bytes(target.read_bytes() + b" ")
        with pytest.raises(SystemExit, match="DENY: digest mismatch"):
            ppa.check_artifact(policy_repo, artifact)

    def test_missing_file_denies(self, policy_repo: Path) -> None:
        artifact = ppa.build_artifact(policy_repo)
        (policy_repo / ppa.POLICY_SOURCE).unlink()
        with pytest.raises(SystemExit, match="DENY: missing file"):
            ppa.check_artifact(policy_repo, artifact)

    def test_short_digest_denies(self, policy_repo: Path) -> None:
        artifact = ppa.build_artifact(policy_repo)
        artifact["files"][ppa.POLICY_SOURCE]["sha256"] = "abc123"
        with pytest.raises(SystemExit, match="DENY: malformed digest"):
            ppa.check_artifact(policy_repo, artifact)

    def test_unknown_schema_version_denies(self, policy_repo: Path) -> None:
        artifact = ppa.build_artifact(policy_repo)
        artifact["schema_version"] = "9.9.9"
        with pytest.raises(SystemExit, match="DENY: unknown artifact schema_version"):
            ppa.check_artifact(policy_repo, artifact)

    @pytest.mark.parametrize("files", [{}, None, "x"])
    def test_empty_or_malformed_manifest_denies(self, policy_repo: Path, files) -> None:
        artifact = ppa.build_artifact(policy_repo)
        artifact["files"] = files
        with pytest.raises(SystemExit, match="DENY: artifact carries no file manifest"):
            ppa.check_artifact(policy_repo, artifact)

    def test_non_object_artifact_denies(self, policy_repo: Path) -> None:
        with pytest.raises(SystemExit, match="DENY"):
            ppa.check_artifact(policy_repo, ["not", "an", "object"])


# ---------------------------------------------------------------------------
# Attestation (R-MMI-10, C-MMI-6)
# ---------------------------------------------------------------------------


@pytest.mark.governance
class TestAttestation:
    KEY = "test-signing-key"

    def _attested(self, policy_repo: Path):
        # ppa is importlib-loaded, so its functions type as Any; no return
        # annotation keeps mypy's no-any-return check satisfied.
        return ppa.build_artifact(policy_repo, attest=True, signing_key=self.KEY)

    def test_builder_produced_attestation_verifies(self, policy_repo: Path) -> None:
        artifact = self._attested(policy_repo)
        assert ppa.verify_attestation(artifact, signing_key=self.KEY) is True

    def test_wrong_key_fails(self, policy_repo: Path) -> None:
        artifact = self._attested(policy_repo)
        assert ppa.verify_attestation(artifact, signing_key="other") is False

    def test_files_digest_flip_with_intact_attestation_fails(self, policy_repo: Path) -> None:
        """Architect-blocker regression: the signature must cover the files
        map, so editing a pinned digest without re-signing must not verify."""
        artifact = self._attested(policy_repo)
        artifact["files"][ppa.POLICY_SOURCE]["sha256"] = "0" * 64
        assert ppa.verify_attestation(artifact, signing_key=self.KEY) is False

    def test_policy_version_flip_with_intact_attestation_fails(self, policy_repo: Path) -> None:
        artifact = self._attested(policy_repo)
        artifact["policy_version"] = "f" * ppa.POLICY_VERSION_HEX_LEN
        assert ppa.verify_attestation(artifact, signing_key=self.KEY) is False

    def test_tampered_snapshot_fails(self, policy_repo: Path) -> None:
        artifact = self._attested(policy_repo)
        artifact["attestation"]["policies"][0]["content_hash"] = "0" * 64
        assert ppa.verify_attestation(artifact, signing_key=self.KEY) is False

    def test_missing_or_null_attestation_fails(self, policy_repo: Path) -> None:
        artifact = ppa.build_artifact(policy_repo)
        assert ppa.verify_attestation(artifact, signing_key=self.KEY) is False

    def test_no_key_anywhere_fails_closed(
        self, policy_repo: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("AGENT_EVIDENCE_KEY", raising=False)
        artifact = self._attested(policy_repo)
        assert ppa.verify_attestation(artifact) is False

    def test_attest_without_key_denies(
        self, policy_repo: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("AGENT_EVIDENCE_KEY", raising=False)
        with pytest.raises(SystemExit, match="DENY"):
            ppa.build_artifact(policy_repo, attest=True)

    def test_env_key_resolution(self, policy_repo: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        import secrets

        key = secrets.token_urlsafe(16)
        monkeypatch.setenv("AGENT_EVIDENCE_KEY", key)
        artifact = ppa.build_artifact(policy_repo, attest=True)
        assert ppa.verify_attestation(artifact) is True


# ---------------------------------------------------------------------------
# CLI via subprocess (exercises the real sys.path bootstrap)
# ---------------------------------------------------------------------------


class TestCli:
    def _run(self, *args: str, env_extra: dict[str, str] | None = None) -> subprocess.CompletedProcess:
        env = {k: v for k, v in os.environ.items() if k != "PYTHONPATH"}
        env.update(env_extra or {})
        return subprocess.run(
            [sys.executable, str(_MODULE_PATH), *args],
            capture_output=True,
            text=True,
            cwd=str(_MODULE_PATH.parent.parent.parent),
            env=env,
            timeout=60,
        )

    def test_build_then_check_round_trip(self, policy_repo: Path, tmp_path: Path) -> None:
        out_file = tmp_path / "artifact.json"
        built = self._run("--repo-root", str(policy_repo), "build", "--output", str(out_file))
        assert built.returncode == 0, built.stderr
        assert "built" in built.stdout
        artifact = json.loads(out_file.read_text(encoding="utf-8"))
        assert artifact["policy_id"] == "test-policy"

        checked = self._run("--repo-root", str(policy_repo), "check", "--artifact", str(out_file))
        assert checked.returncode == 0, checked.stderr
        assert "publish_policy_artifact: passed" in checked.stdout

    def test_check_denies_after_tamper(self, policy_repo: Path, tmp_path: Path) -> None:
        out_file = tmp_path / "artifact.json"
        assert self._run("--repo-root", str(policy_repo), "build", "--output", str(out_file)).returncode == 0
        target = policy_repo / ppa.POLICY_SOURCE
        target.write_bytes(target.read_bytes() + b"!")
        result = self._run("--repo-root", str(policy_repo), "check", "--artifact", str(out_file))
        assert result.returncode != 0
        assert "DENY: digest mismatch" in result.stderr

    def test_check_unreadable_artifact_denies(self, policy_repo: Path, tmp_path: Path) -> None:
        result = self._run(
            "--repo-root", str(policy_repo), "check", "--artifact", str(tmp_path / "absent.json")
        )
        assert result.returncode != 0
        assert "DENY: unreadable artifact" in result.stderr

    def test_cli_attested_round_trip(self, policy_repo: Path, tmp_path: Path) -> None:
        import secrets

        key = secrets.token_urlsafe(16)
        out_file = tmp_path / "artifact.json"
        built = self._run(
            "--repo-root", str(policy_repo), "build", "--output", str(out_file), "--attest",
            env_extra={"AGENT_EVIDENCE_KEY": key},
        )
        assert built.returncode == 0, built.stderr
        checked = self._run(
            "--repo-root", str(policy_repo), "check", "--artifact", str(out_file), "--verify-attestation",
            env_extra={"AGENT_EVIDENCE_KEY": key},
        )
        assert checked.returncode == 0, checked.stderr

    def test_cli_attestation_verify_fails_with_wrong_key(
        self, policy_repo: Path, tmp_path: Path
    ) -> None:
        import secrets

        out_file = tmp_path / "artifact.json"
        assert (
            self._run(
                "--repo-root", str(policy_repo), "build", "--output", str(out_file), "--attest",
                env_extra={"AGENT_EVIDENCE_KEY": secrets.token_urlsafe(16)},
            ).returncode
            == 0
        )
        result = self._run(
            "--repo-root", str(policy_repo), "check", "--artifact", str(out_file), "--verify-attestation",
            env_extra={"AGENT_EVIDENCE_KEY": "a-different-key"},
        )
        assert result.returncode != 0
        assert "DENY: attestation verification failed" in result.stderr


# ---------------------------------------------------------------------------
# Real repository smoke: the shipped policies build and check cleanly
# ---------------------------------------------------------------------------


@pytest.mark.governance
def test_real_repo_build_check_round_trip(project_root: Path, tmp_path: Path) -> None:
    artifact = ppa.build_artifact(project_root)
    ppa.check_artifact(project_root, artifact)
    # policy_version is consistent with the shadow channel's policy identity.
    from harness.shared.shadow_planner import _policy_identity

    assert artifact["policy_version"] == _policy_identity(project_root)[1]
