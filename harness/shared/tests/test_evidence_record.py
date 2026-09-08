"""INV-13 step 3: evidence entries on the broker path (R-AEI-4..7 / AC-5..AC-8)."""

from __future__ import annotations

import json
import logging
import subprocess
from pathlib import Path

import pytest

from harness.shared.governance.broker import ExecutionBroker
from harness.shared.governance.evidence_manifest import EVIDENCE_KEY_ENV, EvidenceBuilder, verify_manifest
from harness.shared.governance.evidence_record import evidence_max_entries, fold_enforcement_baseline
from harness.shared.governance.verdict import BROKER_BLOCKED, VERIFIED, derive_verdict
from harness.shared.governance.verification import VerificationRunner
from harness.shared.policy_loader import PolicyError
from harness.shared.tests.test_governance_broker import IMPLEMENTER, RecordingBackend

pytestmark = pytest.mark.governance

_KEY = "test-signing-key-32-bytes-long!!"
_POLICY_SENTINEL = "POLICY_SENTINEL"
_SOURCE_MAP = {"sentinel.py": "SOURCE_SENTINEL"}
_BACKEND_SENTINEL = "BACKEND_SENTINEL"
_VERSION_SENTINEL = "VERSION_SENTINEL"


def _sink(tmp_path: Path) -> Path:
    """A path outside the agent workspace and outside protected_paths (R-AEI-5)."""
    return tmp_path / "off-workspace" / "evidence.jsonl"


def test_evidence_entry_digests(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """AC-5: monkeypatched digest sources appear verbatim; a recompute cannot satisfy."""
    monkeypatch.setattr(
        "harness.shared.governance.evidence_record.policy_digest",
        lambda _raw: _POLICY_SENTINEL,
    )
    monkeypatch.setattr(
        "harness.shared.governance.evidence_record.backend_capability_record",
        lambda _backend: {"name": _BACKEND_SENTINEL, "version": _VERSION_SENTINEL},
    )
    monkeypatch.setattr(
        "harness.shared.governance.enforcement_digest.enforcement_digests",
        lambda *_a, **_k: dict(_SOURCE_MAP),
    )
    backend = RecordingBackend()
    broker = ExecutionBroker(backend=backend, signing_key=_KEY, evidence_sink=_sink(tmp_path))
    broker.set_enforcement_baseline(dict(_SOURCE_MAP))
    result = broker.execute_command("echo hi", IMPLEMENTER)
    assert result.status == "SUCCESS"
    assert broker.evidence_entries, "governed execution produced no evidence entry"
    entry = broker.evidence_entries[0]
    assert entry["policy_digest"] == _POLICY_SENTINEL
    assert entry["backend_name"] == _BACKEND_SENTINEL
    assert entry["backend_version"] == _VERSION_SENTINEL
    assert entry["source_digest"] == fold_enforcement_baseline(_SOURCE_MAP)


def test_baseline_cited_not_recomputed(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """AC-6: execute_command cites the cached baseline and does not walk again."""
    walks: list[Path] = []

    def counting_digests(workspace: Path, policy_path: Path | None = None) -> dict[str, str]:
        walks.append(workspace)
        return dict(_SOURCE_MAP)

    monkeypatch.setattr("harness.shared.governance.enforcement_digest.enforcement_digests", counting_digests)
    monkeypatch.setattr("harness.shared.governance.verification.enforcement_digests", counting_digests)
    backend = RecordingBackend()
    broker = ExecutionBroker(backend=backend, signing_key=_KEY, evidence_sink=_sink(tmp_path))
    broker.set_enforcement_baseline(dict(_SOURCE_MAP))
    before = len(walks)
    broker.execute_command("echo hi", IMPLEMENTER)
    broker.execute_command("echo hi", IMPLEMENTER)
    assert len(walks) == before
    assert len(broker.evidence_entries) == 2
    expected = fold_enforcement_baseline(_SOURCE_MAP)
    assert broker.evidence_entries[0]["source_digest"] == expected
    assert broker.evidence_entries[1]["source_digest"] == expected


def test_keyless_broker_blocks(monkeypatch: pytest.MonkeyPatch) -> None:
    """AC-7: keyless evidence-enabled broker blocks before spawn, naming the env var."""
    monkeypatch.delenv(EVIDENCE_KEY_ENV, raising=False)
    backend = RecordingBackend()
    broker = ExecutionBroker(backend=backend, evidence_enabled=True)
    result = broker.execute_command("echo hi", IMPLEMENTER)
    assert result.status == BROKER_BLOCKED
    assert EVIDENCE_KEY_ENV in (result.reason or "")
    assert backend.calls == [], "keyless refusal must happen before spawn, not at export()"


def test_evidence_manifest_verifies(tmp_path: Path) -> None:
    """AC-7: an exported digest-bearing manifest verifies under HMAC."""
    builder = EvidenceBuilder(project_root=tmp_path, signing_key=_KEY)
    builder.add_execution_evidence(
        {
            "policy_digest": "abc",
            "source_digest": "def",
            "backend_name": "process",
            "backend_version": "1.0.0",
            "test_digest": "ghi",
        }
    )
    manifest = builder.export()
    assert verify_manifest(manifest, _KEY)
    assert not verify_manifest(manifest, "wrong-key")


def test_verification_with_evidence_verified(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """AC-8: real broker, evidence on, sink outside workspace → VERIFIED, bounded entries."""
    from harness.shared.governance import verification as verification_mod

    monkeypatch.setattr(
        verification_mod.shutil,
        "which",
        lambda name: "/usr/bin/make" if name == "make" else None,
    )

    class SilentDryRun(RecordingBackend):
        """Empty make -n stdout: a recipe name would census `command -v`, which is unmodelled."""

        def _spawn(self, command: str, cwd: Path | None, timeout: int) -> subprocess.CompletedProcess[str]:
            self.calls.append((command, cwd, timeout))
            stdout = "" if "-n" in command else "ok\n"
            return subprocess.CompletedProcess(args=command, returncode=0, stdout=stdout, stderr="")

    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "Makefile").write_text("test-python:\n\techo ok\n", encoding="utf-8")
    sink = tmp_path / "evidence.jsonl"
    backend = SilentDryRun()
    broker = ExecutionBroker(backend=backend, signing_key=_KEY, evidence_sink=sink)
    runner = VerificationRunner(broker, "test-eval", timeout=5)
    runner.snapshot_enforcement(workspace)
    broker.set_enforcement_baseline(runner.baseline or {})
    check = runner.run(workspace)
    verdict = derive_verdict(check)
    assert verdict.status == VERIFIED, check.reason
    assert broker.evidence_entries, "evidence write must not trip enforcement_tampered"
    from harness.shared.governance.evidence_record import evidence_max_entries

    cap = evidence_max_entries()
    assert cap is not None
    assert 1 <= len(broker.evidence_entries) <= cap
    assert sink.is_file()
    line = sink.read_text(encoding="utf-8").splitlines()[0]
    assert verify_manifest(json.loads(line), _KEY)
    rel = sink.relative_to(tmp_path).as_posix()
    assert not rel.startswith("workspace/"), "sink must lie outside the agent workspace"


def test_evidence_max_entries_missing_file_is_adopter_path(tmp_path: Path) -> None:
    """Absent policy is the pre-block adopter path, not a hard error (DEC-043)."""
    assert evidence_max_entries(tmp_path / "no-such-policy.json") is None


def test_evidence_max_entries_absent_block_is_adopter_path(tmp_path: Path) -> None:
    path = tmp_path / "policy.json"
    path.write_text("{}", encoding="utf-8")
    assert evidence_max_entries(path) is None


def test_evidence_max_entries_unreadable_path_fails_closed(tmp_path: Path) -> None:
    """A directory forces a non-file PolicyError without chmod (root CI ignores bits)."""
    with pytest.raises(PolicyError, match="regular file"):
        evidence_max_entries(tmp_path)


@pytest.mark.parametrize(
    "payload, match",
    [
        ("{", "unreadable"),
        ("[]", "not a JSON object"),
        ('{"evidence": []}', "is not an object"),
        ('{"evidence": {}}', "max_entries"),
        ('{"evidence": {"max_entries": 0}}', "positive integer"),
        ('{"evidence": {"max_entries": true}}', "must be an integer"),
        ('{"evidence": {"max_entries": "256"}}', "must be an integer"),
    ],
)
def test_evidence_max_entries_malformed_policy_fails_closed(tmp_path: Path, payload: str, match: str) -> None:
    path = tmp_path / "policy.json"
    path.write_text(payload, encoding="utf-8")
    with pytest.raises(PolicyError, match=match):
        evidence_max_entries(path)


def test_evidence_cap_drops_further_records(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """A reached cap keeps the command result and logs; it does not grow the list."""
    monkeypatch.setattr("harness.shared.governance.broker.evidence_max_entries", lambda: 1)
    backend = RecordingBackend()
    broker = ExecutionBroker(backend=backend, signing_key=_KEY, evidence_sink=_sink(tmp_path))
    broker.set_enforcement_baseline(dict(_SOURCE_MAP))
    with caplog.at_level(logging.WARNING, logger="harness.shared.governance.broker"):
        first = broker.execute_command("echo hi", IMPLEMENTER)
        second = broker.execute_command("echo hi", IMPLEMENTER)
    assert first.status == "SUCCESS"
    assert second.status == "SUCCESS"
    assert len(broker.evidence_entries) == 1
    assert "cap reached" in caplog.text


def test_sink_write_failure_keeps_the_command_result(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """Sink I/O must not rewrite a SUCCESS after spawn (best-effort JSONL)."""

    def boom(_sink: Path, _builder: object) -> None:
        raise OSError("disk full")

    monkeypatch.setattr("harness.shared.governance.broker.append_signed_jsonl", boom)
    backend = RecordingBackend()
    broker = ExecutionBroker(backend=backend, signing_key=_KEY, evidence_sink=_sink(tmp_path))
    broker.set_enforcement_baseline(dict(_SOURCE_MAP))
    with caplog.at_level(logging.WARNING, logger="harness.shared.governance.broker"):
        result = broker.execute_command("echo hi", IMPLEMENTER)
    assert result.status == "SUCCESS"
    assert broker.evidence_entries, "in-memory entry must survive a sink failure"
    assert "sink write failed" in caplog.text


def test_keyless_broker_blocks_is_logged(monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture) -> None:
    monkeypatch.delenv(EVIDENCE_KEY_ENV, raising=False)
    backend = RecordingBackend()
    broker = ExecutionBroker(backend=backend, evidence_enabled=True)
    with caplog.at_level(logging.WARNING, logger="harness.shared.governance.broker"):
        result = broker.execute_command("echo hi", IMPLEMENTER)
    assert result.status == BROKER_BLOCKED
    assert EVIDENCE_KEY_ENV in caplog.text
    assert backend.calls == []
