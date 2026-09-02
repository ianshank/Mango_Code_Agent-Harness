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

_MODULE_PATH = Path(__file__).resolve().parents[1] / "publish_policy_artifact.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("publish_policy_artifact", _MODULE_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
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
        with pytest.raises(ppa.PolicyArtifactError, match="missing policy file"):
            ppa.build_artifact(policy_repo)

    def test_unparseable_policy_source_denies(self, policy_repo: Path) -> None:
        (policy_repo / ppa.POLICY_SOURCE).write_text("not json", encoding="utf-8")
        with pytest.raises(ppa.PolicyArtifactError, match="unparseable policy source"):
            ppa.build_artifact(policy_repo)


# ---------------------------------------------------------------------------
# check_artifact tamper matrix (R-MMI-9)
# ---------------------------------------------------------------------------


@pytest.mark.governance
class TestCheck:
    def test_clean_round_trip_passes(self, policy_repo: Path) -> None:
        artifact = ppa.build_artifact(policy_repo)
        ppa.check_artifact(policy_repo, artifact)
        # "did not raise" is the point, but on its own it would also pass
        # against an artifact builder that returned {}. Pin the shape the
        # tamper cases below rely on being present.
        assert isinstance(artifact, dict)
        assert artifact.get("files"), "a clean artifact must carry a file manifest"

    def test_byte_flip_in_non_identity_file_denies_on_digest(self, policy_repo: Path) -> None:
        """agent-policy.json does not feed policy_id/policy_version, so a
        tamper there is caught purely by the file-manifest digest check."""
        artifact = ppa.build_artifact(policy_repo)
        target = policy_repo / "harness/shared/agent-policy.json"
        target.write_bytes(target.read_bytes() + b" ")
        with pytest.raises(ppa.PolicyArtifactError, match="digest mismatch"):
            ppa.check_artifact(policy_repo, artifact)

    def test_byte_flip_in_policy_source_denies_on_identity_first(self, policy_repo: Path) -> None:
        """POLICY_SOURCE feeds policy_version, so tampering it is caught by
        the identity re-derivation before the file loop ever runs — a more
        specific DENY than a generic digest mismatch."""
        artifact = ppa.build_artifact(policy_repo)
        target = policy_repo / ppa.POLICY_SOURCE
        target.write_bytes(target.read_bytes() + b" ")
        with pytest.raises(ppa.PolicyArtifactError, match="policy_version mismatch"):
            ppa.check_artifact(policy_repo, artifact)

    def test_missing_non_identity_file_denies_on_missing_file(self, policy_repo: Path) -> None:
        artifact = ppa.build_artifact(policy_repo)
        (policy_repo / "harness/shared/agent-policy.json").unlink()
        with pytest.raises(ppa.PolicyArtifactError, match="missing file"):
            ppa.check_artifact(policy_repo, artifact)

    def test_missing_policy_source_denies_on_identity_first(self, policy_repo: Path) -> None:
        artifact = ppa.build_artifact(policy_repo)
        (policy_repo / ppa.POLICY_SOURCE).unlink()
        with pytest.raises(ppa.PolicyArtifactError, match="missing policy source"):
            ppa.check_artifact(policy_repo, artifact)

    def test_short_digest_denies(self, policy_repo: Path) -> None:
        artifact = ppa.build_artifact(policy_repo)
        artifact["files"]["harness/shared/agent-policy.json"]["sha256"] = "abc123"
        with pytest.raises(ppa.PolicyArtifactError, match="malformed digest"):
            ppa.check_artifact(policy_repo, artifact)

    def test_byte_size_mismatch_denies(self, policy_repo: Path) -> None:
        artifact = ppa.build_artifact(policy_repo)
        artifact["files"]["harness/shared/agent-policy.json"]["bytes"] += 1
        with pytest.raises(ppa.PolicyArtifactError, match="byte-size mismatch"):
            ppa.check_artifact(policy_repo, artifact)

    def test_unknown_schema_version_denies(self, policy_repo: Path) -> None:
        artifact = ppa.build_artifact(policy_repo)
        artifact["schema_version"] = "9.9.9"
        with pytest.raises(ppa.PolicyArtifactError, match="unknown artifact schema_version"):
            ppa.check_artifact(policy_repo, artifact)

    def test_artifact_id_mismatch_denies(self, policy_repo: Path) -> None:
        artifact = ppa.build_artifact(policy_repo)
        artifact["artifact_id"] = "something-else"
        with pytest.raises(ppa.PolicyArtifactError, match="unknown artifact_id"):
            ppa.check_artifact(policy_repo, artifact)

    def test_policy_id_mismatch_denies(self, policy_repo: Path) -> None:
        artifact = ppa.build_artifact(policy_repo)
        artifact["policy_id"] = "a-different-policy"
        with pytest.raises(ppa.PolicyArtifactError, match="policy_id mismatch"):
            ppa.check_artifact(policy_repo, artifact)

    @pytest.mark.parametrize("files", [{}, None, "x"])
    def test_empty_or_malformed_manifest_denies(self, policy_repo: Path, files) -> None:
        artifact = ppa.build_artifact(policy_repo)
        artifact["files"] = files
        with pytest.raises(ppa.PolicyArtifactError, match="artifact carries no file manifest"):
            ppa.check_artifact(policy_repo, artifact)

    def test_narrowed_manifest_denies(self, policy_repo: Path) -> None:
        """Architect-blocker regression: dropping a governed file from the
        manifest — rather than corrupting its digest — must not slip past a
        digest-only check. This is exactly what would defeat the drift gate."""
        artifact = ppa.build_artifact(policy_repo)
        del artifact["files"]["harness/shared/agent-policy.json"]
        with pytest.raises(ppa.PolicyArtifactError, match="does not match governed policy files"):
            ppa.check_artifact(policy_repo, artifact)

    def test_extra_manifest_entry_denies(self, policy_repo: Path) -> None:
        artifact = ppa.build_artifact(policy_repo)
        artifact["files"]["some/other/file.json"] = {"sha256": "0" * 64, "bytes": 1}
        with pytest.raises(ppa.PolicyArtifactError, match="does not match governed policy files"):
            ppa.check_artifact(policy_repo, artifact)

    @pytest.mark.parametrize(
        "malicious_key",
        [
            "/etc/passwd",
            "../../../../etc/passwd",
            "harness/shared/../../../etc/passwd",
        ],
    )
    def test_unsafe_relpath_key_never_reaches_the_filesystem(
        self, policy_repo: Path, tmp_path: Path, malicious_key: str
    ) -> None:
        """A files-map key with an unexpected name is already rejected by the
        manifest-scope check (test_extra_manifest_entry_denies) before any
        path is ever dereferenced, since POLICY_FILES is a fixed literal set
        no attacker-controlled key can equal. That check is the reason a
        traversal/absolute-path probe never reaches the filesystem today."""
        outside = tmp_path / "secret.txt"
        outside.write_text("outside the repo", encoding="utf-8")
        artifact = ppa.build_artifact(policy_repo)
        artifact["files"] = {
            malicious_key: {"sha256": hashlib.sha256(outside.read_bytes()).hexdigest(), "bytes": outside.stat().st_size}
        }
        with pytest.raises(ppa.PolicyArtifactError, match="does not match governed policy files"):
            ppa.check_artifact(policy_repo, artifact)

    @pytest.mark.parametrize(
        "malicious_key",
        ["/etc/passwd", "../../../../etc/passwd", "harness/shared/../../../etc/passwd"],
    )
    def test_reject_unsafe_relpath_guard_itself(self, malicious_key: str) -> None:
        """Direct unit test of the path-safety guard as defense-in-depth: if
        POLICY_FILES is ever made config-driven (a real follow-up — see
        NEXT_STEPS.md), this is the check that keeps a malicious manifest key
        from being dereferenced outside repo_root."""
        with pytest.raises(ppa.PolicyArtifactError, match="unsafe file path"):
            ppa._reject_unsafe_relpath(malicious_key)

    def test_reject_unsafe_relpath_guard_accepts_governed_files(self) -> None:
        # Without this the loop is vacuous: an empty POLICY_FILES would make
        # the test pass while proving nothing about the guard.
        assert ppa.POLICY_FILES, "POLICY_FILES is empty; the loop below checks nothing"
        for rel in ppa.POLICY_FILES:
            ppa._reject_unsafe_relpath(rel)  # must not raise

    def test_non_object_artifact_denies(self, policy_repo: Path) -> None:
        with pytest.raises(ppa.PolicyArtifactError):
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
        with pytest.raises(ppa.PolicyArtifactError):
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
        target = policy_repo / "harness/shared/agent-policy.json"
        target.write_bytes(target.read_bytes() + b"!")
        result = self._run("--repo-root", str(policy_repo), "check", "--artifact", str(out_file))
        assert result.returncode != 0
        assert "DENY: digest mismatch" in result.stderr

    def test_check_denies_after_narrowed_manifest(self, policy_repo: Path, tmp_path: Path) -> None:
        out_file = tmp_path / "artifact.json"
        assert self._run("--repo-root", str(policy_repo), "build", "--output", str(out_file)).returncode == 0
        artifact = json.loads(out_file.read_text(encoding="utf-8"))
        del artifact["files"]["harness/shared/agent-policy.json"]
        out_file.write_text(json.dumps(artifact), encoding="utf-8")
        result = self._run("--repo-root", str(policy_repo), "check", "--artifact", str(out_file))
        assert result.returncode != 0
        assert "DENY: artifact file manifest does not match governed policy files" in result.stderr

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
# Helpers and attestation edge legs (in-process, for coverage of the guards)
# ---------------------------------------------------------------------------


def _hand_sign(unsigned: dict, key: str) -> dict:
    """Sign an attestation body the way EvidenceBuilder does, so tests can
    craft signature-valid attestations whose *contents* are inconsistent."""
    import hmac as hmac_mod

    signed = dict(unsigned)
    signed["_signature"] = hmac_mod.new(
        key.encode("utf-8"),
        json.dumps(unsigned, sort_keys=True).encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    return signed


class TestHelpersAndAttestationEdges:
    KEY = "edge-case-key"

    def test_digest_helper_matches_hashlib(self, tmp_path: Path) -> None:
        target = tmp_path / "f.bin"
        target.write_bytes(b"payload")
        assert ppa.digest(target) == hashlib.sha256(b"payload").hexdigest()

    def test_bootstrap_imports_inserts_repo_root_when_absent(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """The sys.path insert leg fires when the repo root is not importable —
        the direct `python harness/control-plane/...` environment."""
        repo_root = ppa._repo_root_default()
        stripped = [p for p in sys.path if Path(p or ".").resolve() != repo_root]
        monkeypatch.setattr(sys, "path", stripped)
        evidence_builder_cls = ppa._bootstrap_imports()
        assert evidence_builder_cls is not None
        assert str(repo_root) in sys.path

    def test_signature_valid_but_files_not_a_dict_fails(self, policy_repo: Path) -> None:
        """A hand-signed artifact whose core snapshot matches but whose files
        entry is not a mapping must fail the structural cross-check."""
        artifact = ppa.build_artifact(policy_repo)
        artifact["files"] = "not-a-dict"
        core = ppa._canonical_core_digest(artifact)
        artifact["attestation"] = _hand_sign(
            {"policies": [{"policy_id": ppa.ARTIFACT_ID, "content_hash": core}]}, self.KEY
        )
        assert ppa.verify_attestation(artifact, signing_key=self.KEY) is False

    def test_signature_valid_but_file_snapshot_missing_fails(self, policy_repo: Path) -> None:
        """A signed attestation carrying the core snapshot but no per-file
        snapshots must fail: every manifest entry needs its own cross-check."""
        artifact = ppa.build_artifact(policy_repo)
        core = ppa._canonical_core_digest(artifact)
        artifact["attestation"] = _hand_sign(
            {"policies": [{"policy_id": ppa.ARTIFACT_ID, "content_hash": core}]}, self.KEY
        )
        assert ppa.verify_attestation(artifact, signing_key=self.KEY) is False


# ---------------------------------------------------------------------------
# main() in-process (the CLI wiring itself, visible to coverage)
# ---------------------------------------------------------------------------


class TestMainInProcess:
    def test_build_then_check_round_trip(
        self, policy_repo: Path, tmp_path: Path, capsys: pytest.CaptureFixture
    ) -> None:
        out_file = tmp_path / "artifact.json"
        ppa.main(["--repo-root", str(policy_repo), "build", "--output", str(out_file)])
        assert "built" in capsys.readouterr().out
        artifact = json.loads(out_file.read_text(encoding="utf-8"))
        assert artifact["policy_id"] == "test-policy"

        ppa.main(["--repo-root", str(policy_repo), "check", "--artifact", str(out_file)])
        assert "publish_policy_artifact: passed" in capsys.readouterr().out

    def test_check_deny_becomes_systemexit(self, policy_repo: Path, tmp_path: Path) -> None:
        out_file = tmp_path / "artifact.json"
        ppa.main(["--repo-root", str(policy_repo), "build", "--output", str(out_file)])
        target = policy_repo / "harness/shared/agent-policy.json"
        target.write_bytes(target.read_bytes() + b"!")
        with pytest.raises(SystemExit, match="DENY: digest mismatch"):
            ppa.main(["--repo-root", str(policy_repo), "check", "--artifact", str(out_file)])

    def test_check_unreadable_artifact_denies(self, policy_repo: Path, tmp_path: Path) -> None:
        with pytest.raises(SystemExit, match="DENY: unreadable artifact"):
            ppa.main(["--repo-root", str(policy_repo), "check", "--artifact", str(tmp_path / "absent.json")])

    def test_check_verify_attestation_fails_without_attestation(
        self, policy_repo: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("AGENT_EVIDENCE_KEY", raising=False)
        out_file = tmp_path / "artifact.json"
        ppa.main(["--repo-root", str(policy_repo), "build", "--output", str(out_file)])
        with pytest.raises(SystemExit, match="DENY: attestation verification failed"):
            ppa.main(
                ["--repo-root", str(policy_repo), "check", "--artifact", str(out_file), "--verify-attestation"]
            )

    def test_attested_round_trip(
        self, policy_repo: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
    ) -> None:
        import secrets

        monkeypatch.setenv("AGENT_EVIDENCE_KEY", secrets.token_urlsafe(16))
        out_file = tmp_path / "artifact.json"
        ppa.main(["--repo-root", str(policy_repo), "build", "--output", str(out_file), "--attest"])
        ppa.main(
            ["--repo-root", str(policy_repo), "check", "--artifact", str(out_file), "--verify-attestation"]
        )
        assert "publish_policy_artifact: passed" in capsys.readouterr().out

    def test_main_dispatch_leg(
        self, policy_repo: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
    ) -> None:
        """The `if __name__ == "__main__"` leg via runpy, as the real CLI runs."""
        import runpy

        out_file = tmp_path / "artifact.json"
        monkeypatch.setattr(
            sys,
            "argv",
            ["publish_policy_artifact.py", "--repo-root", str(policy_repo), "build", "--output", str(out_file)],
        )
        runpy.run_path(str(_MODULE_PATH), run_name="__main__")
        assert out_file.is_file()
        assert "built" in capsys.readouterr().out


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


# ---------------------------------------------------------------------------
# Drift gate: the committed artifact must match the working tree
# ---------------------------------------------------------------------------


@pytest.mark.governance
def test_committed_artifact_matches_working_tree(project_root: Path) -> None:
    """Drift gate for the authoritative policy files.

    `make digest-regen` pins the per-stack mirrors, but nothing gated drift on
    `harness/shared/governance-policy.json` / `agent-policy.json` themselves.
    Editing either without regenerating this artifact fails here — which puts
    the gate inside `make ci` through the existing pytest stage, with no
    protected-path change.

    Regenerate with:
        python harness/control-plane/publish_policy_artifact.py \
            build --output harness/control-plane/policy-artifact.json
    """
    committed = project_root / "harness" / "control-plane" / "policy-artifact.json"
    assert committed.is_file(), f"missing committed policy artifact: {committed}"
    artifact = json.loads(committed.read_text(encoding="utf-8"))
    ppa.check_artifact(project_root, artifact)  # PolicyArtifactError(DENY) on any drift
    assert artifact["policy_version"] == ppa.build_artifact(project_root)["policy_version"]
