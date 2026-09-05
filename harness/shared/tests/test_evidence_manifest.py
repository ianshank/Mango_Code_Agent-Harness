"""Tests for harness/shared/governance/evidence_manifest.py."""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
from pathlib import Path

import pytest

from harness.shared.governance.evidence_manifest import (
    EVIDENCE_KEY_ENV,
    EvidenceBuilder,
)

_KEY = "test-signing-key-32-bytes-long!!"


@pytest.fixture
def builder(tmp_path: Path) -> EvidenceBuilder:
    """EvidenceBuilder with an injected key — no env mutation needed."""
    return EvidenceBuilder(project_root=tmp_path, signing_key=_KEY)


# ---------------------------------------------------------------------------
# Constructor / key resolution
# ---------------------------------------------------------------------------


def test_signing_key_from_constructor(tmp_path: Path) -> None:
    b = EvidenceBuilder(project_root=tmp_path, signing_key=_KEY)
    assert b._resolve_key() == _KEY.encode("utf-8")


def test_signing_key_from_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(EVIDENCE_KEY_ENV, "env-key")
    b = EvidenceBuilder(project_root=tmp_path)
    assert b._resolve_key() == b"env-key"


def test_constructor_key_takes_precedence_over_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(EVIDENCE_KEY_ENV, "env-key")
    b = EvidenceBuilder(project_root=tmp_path, signing_key="ctor-key")
    assert b._resolve_key() == b"ctor-key"


def test_missing_key_raises_value_error(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(EVIDENCE_KEY_ENV, raising=False)
    b = EvidenceBuilder(project_root=tmp_path)
    with pytest.raises(ValueError, match=EVIDENCE_KEY_ENV):
        b._resolve_key()


def test_export_raises_value_error_when_no_key(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(EVIDENCE_KEY_ENV, raising=False)
    b = EvidenceBuilder(project_root=tmp_path)
    with pytest.raises(ValueError):
        b.export()


# ---------------------------------------------------------------------------
# add_policy_snapshot
# ---------------------------------------------------------------------------


def test_add_policy_snapshot_records_fields(builder: EvidenceBuilder) -> None:
    builder.add_policy_snapshot("POL-1", "v2", "abc123")
    policies = builder._manifest["policies"]
    assert len(policies) == 1
    assert policies[0]["policy_id"] == "POL-1"
    assert policies[0]["version"] == "v2"
    assert policies[0]["content_hash"] == "abc123"
    assert isinstance(policies[0]["timestamp"], float)


def test_add_multiple_policy_snapshots(builder: EvidenceBuilder) -> None:
    builder.add_policy_snapshot("P1", "v1", "h1")
    builder.add_policy_snapshot("P2", "v2", "h2")
    assert len(builder._manifest["policies"]) == 2


# ---------------------------------------------------------------------------
# add_action
# ---------------------------------------------------------------------------


def test_add_action_records_fields(builder: EvidenceBuilder) -> None:
    builder.add_action("write_file", "sha256:abc", "success", 42)
    actions = builder._manifest["actions"]
    assert len(actions) == 1
    assert actions[0]["tool_name"] == "write_file"
    assert actions[0]["arguments_hash"] == "sha256:abc"
    assert actions[0]["outcome"] == "success"
    assert actions[0]["duration_ms"] == 42


def test_add_multiple_actions(builder: EvidenceBuilder) -> None:
    builder.add_action("tool_a", "h1", "ok", 10)
    builder.add_action("tool_b", "h2", "ok", 20)
    assert len(builder._manifest["actions"]) == 2


# ---------------------------------------------------------------------------
# add_synthesis_result
# ---------------------------------------------------------------------------


def test_add_synthesis_result_records_fields(builder: EvidenceBuilder) -> None:
    builder.add_synthesis_result("run-42", is_accepted=True, evaluation_score=0.95)
    results = builder._manifest["synthesis_results"]
    assert len(results) == 1
    assert results[0]["run_id"] == "run-42"
    assert results[0]["is_accepted"] is True
    assert results[0]["evaluation_score"] == pytest.approx(0.95)


def test_add_synthesis_result_rejected(builder: EvidenceBuilder) -> None:
    builder.add_synthesis_result("run-99", is_accepted=False, evaluation_score=0.1)
    assert builder._manifest["synthesis_results"][0]["is_accepted"] is False


# ---------------------------------------------------------------------------
# export
# ---------------------------------------------------------------------------


def test_export_returns_signature(builder: EvidenceBuilder) -> None:
    result = builder.export()
    assert "_signature" in result
    assert isinstance(result["_signature"], str)
    assert len(result["_signature"]) == 64  # SHA-256 hex = 64 chars


def test_export_signature_is_deterministic_for_same_content(builder: EvidenceBuilder) -> None:
    sig1 = builder.export()["_signature"]
    sig2 = builder.export()["_signature"]
    assert sig1 == sig2


def test_export_signature_verifiable(builder: EvidenceBuilder) -> None:
    """The signature must match an independently computed HMAC."""
    result = builder.export()
    sig = result.pop("_signature")
    content_bytes = json.dumps(result, sort_keys=True).encode("utf-8")
    expected = hmac.new(_KEY.encode("utf-8"), content_bytes, hashlib.sha256).hexdigest()
    assert sig == expected


def test_export_does_not_mutate_manifest(builder: EvidenceBuilder) -> None:
    builder.add_action("t", "h", "ok", 1)
    before = len(builder._manifest["actions"])
    builder.export()
    assert len(builder._manifest["actions"]) == before
    assert "_signature" not in builder._manifest


def test_export_includes_all_sections(builder: EvidenceBuilder) -> None:
    builder.add_policy_snapshot("P", "v1", "h")
    builder.add_action("tool", "ah", "ok", 5)
    builder.add_synthesis_result("r", True, 0.8)
    result = builder.export()
    assert len(result["policies"]) == 1
    assert len(result["actions"]) == 1
    assert len(result["synthesis_results"]) == 1


def test_export_logs_debug(builder: EvidenceBuilder, caplog: pytest.LogCaptureFixture) -> None:
    builder.add_action("t", "h", "ok", 1)
    with caplog.at_level(logging.DEBUG, logger="harness.shared.governance.evidence_manifest"):
        builder.export()
    assert "Evidence manifest exported" in caplog.text
