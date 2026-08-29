"""Tests for the CognitiveSignal envelope and JSONL sink.

Requirement Citations: R-MMI-1..4, C-MMI-1, C-MMI-2
(docs/specs/mangomas-integration-core.md).

Metamorphic/serialization tests construct signals directly with pinned
literals (never via ``create()``) so uuid/clock nondeterminism cannot make
field-diff assertions flaky.
"""

from __future__ import annotations

import dataclasses
import json
import logging
import typing
from pathlib import Path

import pytest

from harness.shared.cognitive_signal import (
    ACCEPTED_SCHEMA_VERSION,
    DEFAULT_SIGNAL_SUBDIR,
    MAX_SIGNAL_BYTES,
    SIGNAL_DIR_ENV,
    SIGNAL_FILE_NAME,
    CognitiveSignal,
    CognitiveSignalSink,
    SignalValidationError,
    validate_signal_dict,
)

PINNED = {
    "schema_version": ACCEPTED_SCHEMA_VERSION,
    "signal_id": "00000000-0000-4000-8000-000000000001",
    "run_id": "00000000-0000-4000-8000-00000000000a",
    "task_id": "deadbeefdeadbeef",
    "producer_id": "planner.incumbent",
    "signal_type": "plan.incumbent",
    "payload": {"plan_sha256": "abc", "elapsed_ms": 12},
    "policy_id": "agentic-ssd-governance",
    "policy_version": "0123456789abcdef",
    "timestamp": "2026-08-27T00:00:00+00:00",
}


def pinned_signal(**overrides) -> CognitiveSignal:
    return CognitiveSignal(**{**PINNED, **overrides})


# ---------------------------------------------------------------------------
# Envelope shape
# ---------------------------------------------------------------------------


class TestEnvelope:
    def test_round_trip_to_dict_validate(self) -> None:
        sig = pinned_signal(confidence=0.5, evidence_refs=("e1",), producer_version="v1")
        assert validate_signal_dict(sig.to_dict()) == sig

    def test_schema_version_is_first_serialized_key(self) -> None:
        serialized = json.dumps(pinned_signal().to_dict())
        assert serialized.startswith('{"schema_version"')

    def test_frozen(self) -> None:
        with pytest.raises(dataclasses.FrozenInstanceError):
            pinned_signal().producer_id = "other"  # type: ignore[misc]

    def test_create_populates_uuid_and_utc_timestamp(self) -> None:
        import uuid
        from datetime import datetime

        sig = CognitiveSignal.create(
            run_id="r",
            task_id="t",
            producer_id="planner.shadow",
            signal_type="plan.shadow",
            payload={},
            policy_id="p",
            policy_version="v",
        )
        assert sig.schema_version == ACCEPTED_SCHEMA_VERSION
        uuid.UUID(sig.signal_id)  # parses
        assert datetime.fromisoformat(sig.timestamp).tzinfo is not None
        assert validate_signal_dict(sig.to_dict()) == sig


# ---------------------------------------------------------------------------
# Fail-closed validation (R-MMI-2)
# ---------------------------------------------------------------------------


@pytest.mark.governance
class TestValidation:
    @pytest.mark.parametrize("field", list(PINNED.keys() - {"payload"}))
    def test_missing_required_string_field_rejected(self, field: str) -> None:
        data = pinned_signal().to_dict()
        del data[field]
        with pytest.raises(SignalValidationError):
            validate_signal_dict(data)

    @pytest.mark.parametrize("field", list(PINNED.keys() - {"payload"}))
    def test_empty_or_nonstring_field_rejected(self, field: str) -> None:
        for bad in ("", 7, None):
            data = pinned_signal().to_dict()
            data[field] = bad
            with pytest.raises(SignalValidationError):
                validate_signal_dict(data)

    def test_unknown_schema_version_rejected(self) -> None:
        data = pinned_signal().to_dict()
        data["schema_version"] = "9.9.9"
        with pytest.raises(SignalValidationError, match="unsupported schema_version"):
            validate_signal_dict(data)

    @pytest.mark.parametrize("bad", ["plan", "Plan.shadow", "plan..x", ".plan", "plan.Shadow"])
    def test_malformed_signal_type_rejected(self, bad: str) -> None:
        data = pinned_signal().to_dict()
        data["signal_type"] = bad
        with pytest.raises(SignalValidationError, match="malformed signal_type"):
            validate_signal_dict(data)

    @pytest.mark.parametrize("bad", ["2026-08-27T00:00:00", "not-a-time"])
    def test_naive_or_unparseable_timestamp_rejected(self, bad: str) -> None:
        data = pinned_signal().to_dict()
        data["timestamp"] = bad
        with pytest.raises(SignalValidationError):
            validate_signal_dict(data)

    def test_non_dict_payload_rejected(self) -> None:
        data = pinned_signal().to_dict()
        data["payload"] = "text"
        with pytest.raises(SignalValidationError, match="payload"):
            validate_signal_dict(data)

    @pytest.mark.parametrize("bad", [-0.1, 1.1, float("nan"), "high", True])
    def test_bad_confidence_rejected(self, bad) -> None:
        data = pinned_signal().to_dict()
        data["confidence"] = bad
        with pytest.raises(SignalValidationError, match="confidence"):
            validate_signal_dict(data)

    def test_none_confidence_accepted(self) -> None:
        data = pinned_signal().to_dict()
        data["confidence"] = None
        assert validate_signal_dict(data).confidence is None

    def test_unknown_fields_rejected(self) -> None:
        data = pinned_signal().to_dict()
        data["grants"] = ["write_file"]
        with pytest.raises(SignalValidationError, match="unknown fields"):
            validate_signal_dict(data)

    def test_evidence_refs_list_coerced_to_tuple(self) -> None:
        data = pinned_signal().to_dict()
        data["evidence_refs"] = ["a", "b"]
        assert validate_signal_dict(data).evidence_refs == ("a", "b")

    @pytest.mark.parametrize("bad", ["nope", [1], {"a": 1}])
    def test_bad_evidence_refs_rejected(self, bad) -> None:
        data = pinned_signal().to_dict()
        data["evidence_refs"] = bad
        with pytest.raises(SignalValidationError, match="evidence_refs"):
            validate_signal_dict(data)

    def test_rejections_are_logged(self, caplog: pytest.LogCaptureFixture) -> None:
        data = pinned_signal().to_dict()
        data["schema_version"] = "9.9.9"
        with caplog.at_level(logging.WARNING, logger="harness.shared.cognitive_signal"):
            with pytest.raises(SignalValidationError):
                validate_signal_dict(data)
        assert any("rejected signal" in r.message for r in caplog.records)


# ---------------------------------------------------------------------------
# Metamorphic: identity metadata carries no authority (C-MMI-1, C-MMI-2)
# ---------------------------------------------------------------------------


@pytest.mark.governance
class TestIdentityNeutrality:
    def test_producer_id_only_key_differs_in_serialization(self) -> None:
        a = pinned_signal(producer_id="planner.incumbent").to_dict()
        b = pinned_signal(producer_id="attacker.shadow").to_dict()
        differing = {k for k in a if a[k] != b[k]}
        assert differing == {"producer_id"}
        # Both validate identically — identity change grants nothing and
        # changes no validation outcome.
        validate_signal_dict(a)
        validate_signal_dict(b)

    def test_confidence_round_trips_verbatim(self, tmp_path: Path) -> None:
        sink = CognitiveSignalSink(tmp_path)
        for value in (None, 0.0, 1.0, 0.123456789):
            sink.append(pinned_signal(signal_id=f"id-{value}", confidence=value))
        lines = sink.path.read_text(encoding="utf-8").splitlines()
        stored = [json.loads(line)["confidence"] for line in lines]
        assert stored == [None, 0.0, 1.0, 0.123456789]

    def test_confidence_never_alters_sink_behavior(self, tmp_path: Path) -> None:
        low = CognitiveSignalSink(tmp_path / "low")
        high = CognitiveSignalSink(tmp_path / "high")
        low.append(pinned_signal(confidence=0.0))
        high.append(pinned_signal(confidence=1.0))
        a = json.loads(low.path.read_text(encoding="utf-8"))
        b = json.loads(high.path.read_text(encoding="utf-8"))
        differing = {k for k in a if a[k] != b[k]}
        assert differing == {"confidence"}


# ---------------------------------------------------------------------------
# Sink (R-MMI-3, R-MMI-4)
# ---------------------------------------------------------------------------


class TestSink:
    def test_for_workspace_default_path(self, tmp_path: Path) -> None:
        sink = CognitiveSignalSink.for_workspace(tmp_path, environ={})
        assert sink.path == (tmp_path / DEFAULT_SIGNAL_SUBDIR / SIGNAL_FILE_NAME).resolve()

    def test_for_workspace_env_override_wins(self, tmp_path: Path) -> None:
        override = tmp_path / "elsewhere"
        sink = CognitiveSignalSink.for_workspace(
            tmp_path / "ws", environ={SIGNAL_DIR_ENV: str(override)}
        )
        assert sink.path == override.resolve() / SIGNAL_FILE_NAME

    def test_for_workspace_relative_override_resolved(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.chdir(tmp_path)
        sink = CognitiveSignalSink.for_workspace(tmp_path / "ws", environ={SIGNAL_DIR_ENV: "rel"})
        assert sink.path.is_absolute()
        assert sink.path == (tmp_path / "rel").resolve() / SIGNAL_FILE_NAME

    def test_for_workspace_reads_process_env_by_default(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv(SIGNAL_DIR_ENV, str(tmp_path / "proc-env"))
        sink = CognitiveSignalSink.for_workspace(tmp_path / "ws")
        assert sink.path == (tmp_path / "proc-env").resolve() / SIGNAL_FILE_NAME

    def test_append_creates_parents_and_two_lines(self, tmp_path: Path) -> None:
        sink = CognitiveSignalSink(tmp_path / "deep" / "dir")
        sink.append(pinned_signal(signal_id="one"))
        sink.append(pinned_signal(signal_id="two"))
        lines = sink.path.read_text(encoding="utf-8").splitlines()
        assert [json.loads(line)["signal_id"] for line in lines] == ["one", "two"]

    def test_jsonl_round_trip_revalidates_to_equal_signal(self, tmp_path: Path) -> None:
        sink = CognitiveSignalSink(tmp_path)
        original = pinned_signal(evidence_refs=("e1", "e2"), producer_version="digest")
        sink.append(original)
        stored = json.loads(sink.path.read_text(encoding="utf-8"))
        assert validate_signal_dict(stored) == original

    def test_multiline_unicode_payload_is_single_jsonl_line(self, tmp_path: Path) -> None:
        sink = CognitiveSignalSink(tmp_path)
        sink.append(pinned_signal(payload={"plan": "line1\nline2\r\n🍋 計画"}))
        raw = sink.path.read_bytes()
        assert raw.count(b"\n") == 1 and raw.endswith(b"\n")
        assert b"\r" not in raw

    def test_oversize_signal_rejected_file_unchanged(self, tmp_path: Path) -> None:
        sink = CognitiveSignalSink(tmp_path)
        big = pinned_signal(payload={"blob": "x" * (MAX_SIGNAL_BYTES + 1)})
        with pytest.raises(SignalValidationError, match="limit"):
            sink.append(big)
        assert not sink.path.exists()

    def test_invalid_signal_rejected_file_unchanged(self, tmp_path: Path) -> None:
        sink = CognitiveSignalSink(tmp_path)
        bad = pinned_signal(schema_version="9.9.9")  # bypasses factory on purpose
        with pytest.raises(SignalValidationError):
            sink.append(bad)
        assert not sink.path.exists()

    def test_nonfinite_payload_rejected_strict_json(self, tmp_path: Path) -> None:
        sink = CognitiveSignalSink(tmp_path)
        # SignalValidationError is a ValueError subclass; asserted here as the
        # exact type raised (not just the base class) to pin the sink's "one
        # exception type at the boundary" contract precisely.
        with pytest.raises(SignalValidationError, match="not JSON-serializable"):
            sink.append(pinned_signal(payload={"v": float("inf")}))
        assert not sink.path.exists()

    def test_append_lock_timeout_raises_timeouterror(self, tmp_path: Path) -> None:
        sink = CognitiveSignalSink(tmp_path, lock_timeout_s=0.2, lock_poll_s=0.01)
        tmp_path.mkdir(exist_ok=True)
        sink.path.with_suffix(".lock").parent.mkdir(parents=True, exist_ok=True)
        sink.path.with_suffix(".lock").touch()  # stranded lock
        with pytest.raises(TimeoutError):
            sink.append(pinned_signal())
        assert not sink.path.exists()

    def test_lock_released_after_success_and_after_write_error(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        sink = CognitiveSignalSink(tmp_path)
        sink.append(pinned_signal())
        assert not sink.path.with_suffix(".lock").exists()

        real_open = Path.open

        def _fail_open(self: Path, *args, **kwargs):
            if self == sink.path:
                raise OSError("disk full")
            return real_open(self, *args, **kwargs)

        monkeypatch.setattr(Path, "open", _fail_open)
        with pytest.raises(OSError, match="disk full"):
            sink.append(pinned_signal())
        assert not sink.path.with_suffix(".lock").exists()


# ---------------------------------------------------------------------------
# Schema drift guard: JSON schema doc <-> validator <-> dataclass
# ---------------------------------------------------------------------------


@pytest.mark.governance
def test_schema_document_matches_validator_and_dataclass(shared_dir: Path) -> None:
    schema = json.loads(
        (shared_dir / "schemas" / "cognitive-signal.schema.json").read_text(encoding="utf-8")
    )
    field_names = {f.name for f in dataclasses.fields(CognitiveSignal)}
    assert set(schema["properties"]) == field_names
    from harness.shared.cognitive_signal import _REQUIRED_STR_FIELDS

    assert set(schema["required"]) == set(_REQUIRED_STR_FIELDS) | {"payload"}
    assert schema["additionalProperties"] is False
    assert schema["properties"]["schema_version"]["const"] == ACCEPTED_SCHEMA_VERSION


@pytest.mark.governance
class TestValidationEdges:
    def test_non_mapping_rejected(self) -> None:
        with pytest.raises(SignalValidationError, match="must be a mapping"):
            validate_signal_dict(["not", "a", "mapping"])  # type: ignore[arg-type]

    @pytest.mark.parametrize("field", ["producer_version", "parent_signal_id"])
    def test_nonstring_optional_field_rejected(self, field: str) -> None:
        data = pinned_signal().to_dict()
        data[field] = 42
        with pytest.raises(SignalValidationError, match=field):
            validate_signal_dict(data)


@pytest.mark.governance
class TestSinkLimits:
    """Sink-level containment: unserializable payloads and file growth are both
    rejected as SignalValidationError so a caller has one type to contain."""

    def test_unserializable_payload_raises_signal_validation_error(self, tmp_path: Path) -> None:
        sink = CognitiveSignalSink(tmp_path)
        for value in (Path("/tmp"), {1, 2}, b"bytes", object()):
            with pytest.raises(SignalValidationError, match="not JSON-serializable"):
                sink.append(pinned_signal(payload={"v": value}))
        assert not sink.path.exists()

    def test_sink_size_ceiling_rejects_and_leaves_file_intact(self, tmp_path: Path) -> None:
        from harness.shared.cognitive_signal import MAX_SINK_BYTES

        # Budget derived from a real serialized line so the test does not depend
        # on the envelope's byte size staying constant.
        one_line = len(json.dumps(pinned_signal().to_dict(), ensure_ascii=False).encode()) + 1
        sink = CognitiveSignalSink(tmp_path, max_sink_bytes=one_line * 3)
        sink.append(pinned_signal(signal_id="first"))
        first_size = sink.path.stat().st_size
        with pytest.raises(SignalValidationError, match="would exceed"):
            for i in range(50):
                sink.append(pinned_signal(signal_id=f"fill-{i}"))
        assert sink.path.stat().st_size >= first_size
        # Every persisted line is still individually valid — no partial write.
        for line in sink.path.read_text(encoding="utf-8").splitlines():
            validate_signal_dict(json.loads(line))
        assert MAX_SINK_BYTES > 0  # default ceiling is a positive budget

    def test_default_ceiling_allows_normal_use(self, tmp_path: Path) -> None:
        sink = CognitiveSignalSink(tmp_path)
        for i in range(25):
            sink.append(pinned_signal(signal_id=f"s{i}"))
        assert len(sink.path.read_text(encoding="utf-8").splitlines()) == 25


# ---------------------------------------------------------------------------
# Cross-version timestamp acceptance (fromisoformat's "Z" support is a 3.11+
# feature; the CI matrix spans 3.9-3.12) and payload key/serialization
# hardening surfaced by adversarial review.
# ---------------------------------------------------------------------------


@pytest.mark.governance
class TestTimestampCrossVersion:
    @pytest.mark.parametrize(
        "value",
        [
            "2026-08-27T00:00:00Z",
            "2026-08-27T00:00:00+00:00",
            "2026-08-27T00:00:00.123456Z",
        ],
    )
    def test_z_suffix_and_offset_forms_both_accepted(self, value: str) -> None:
        data = pinned_signal().to_dict()
        data["timestamp"] = value
        assert validate_signal_dict(data).timestamp == value

    def test_z_suffix_produces_a_timezone_aware_parse(self) -> None:
        from harness.shared.cognitive_signal import _parse_iso_timestamp

        parsed = _parse_iso_timestamp("2026-08-27T00:00:00Z")
        offset = parsed.utcoffset()
        assert offset is not None
        assert offset.total_seconds() == 0

    def test_lowercase_z_is_not_silently_accepted(self) -> None:
        # ISO-8601 defines the UTC designator as uppercase "Z"; lowercase is
        # not normalized and should fail the same as any other malformed
        # string, not be silently treated as UTC.
        data = pinned_signal().to_dict()
        data["timestamp"] = "2026-08-27T00:00:00z"
        with pytest.raises(SignalValidationError):
            validate_signal_dict(data)


class TestPayloadHardening:
    def test_non_string_payload_keys_rejected(self) -> None:
        data = pinned_signal().to_dict()
        data["payload"] = {1: "from-int", "1": "from-str"}
        with pytest.raises(SignalValidationError, match="payload' keys must all be strings"):
            validate_signal_dict(data)

    def test_string_keys_that_look_like_other_types_are_fine(self) -> None:
        data = pinned_signal().to_dict()
        data["payload"] = {"1": "a", "true": "b", "null": "c"}
        assert validate_signal_dict(data).payload == {"1": "a", "true": "b", "null": "c"}

    def test_lone_surrogate_in_payload_does_not_raise_unicode_error(self, tmp_path: Path) -> None:
        sink = CognitiveSignalSink(tmp_path)
        sig = pinned_signal(payload={"v": "x" + chr(0xD800) + "y"})
        sink.append(sig)  # must not raise UnicodeEncodeError
        stored = json.loads(sink.path.read_text(encoding="utf-8"))
        assert validate_signal_dict(stored).payload["v"] == sig.payload["v"]

    def test_line_and_paragraph_separators_do_not_split_the_jsonl_line(self, tmp_path: Path) -> None:
        sink = CognitiveSignalSink(tmp_path)
        payload_value = "before" + chr(0x2028) + "after" + chr(0x2029) + chr(0x0085) + "end"
        sink.append(pinned_signal(payload={"v": payload_value}))
        raw_text = sink.path.read_text(encoding="utf-8")
        # A naive Unicode-aware reader (str.splitlines) must see exactly one
        # line, matching the byte-level `\n`-count guarantee already tested.
        assert len(raw_text.splitlines()) == 1
        stored = json.loads(raw_text)
        assert stored["payload"]["v"] == payload_value

    def test_deeply_nested_payload_raises_signal_validation_error_not_recursion_error(
        self, tmp_path: Path
    ) -> None:
        nested: typing.Any = "leaf"
        for _ in range(20_000):
            nested = {"n": nested}
        sink = CognitiveSignalSink(tmp_path)
        with pytest.raises(SignalValidationError, match="not JSON-serializable"):
            sink.append(pinned_signal(payload={"v": nested}))
        assert not sink.path.exists()

    def test_sink_dir_blocked_by_existing_file_raises_signal_validation_error(
        self, tmp_path: Path
    ) -> None:
        blocker = tmp_path / "blocker"
        blocker.write_text("not a directory", encoding="utf-8")
        sink = CognitiveSignalSink(blocker / "nested" / "signals")
        with pytest.raises(SignalValidationError, match="cannot create sink directory"):
            sink.append(pinned_signal())

    def test_sink_path_itself_blocked_by_existing_file(self, tmp_path: Path) -> None:
        blocker = tmp_path / "iamafile"
        blocker.write_text("x", encoding="utf-8")
        sink = CognitiveSignalSink(blocker)
        with pytest.raises(SignalValidationError, match="cannot create sink directory"):
            sink.append(pinned_signal())
