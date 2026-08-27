"""Versioned CognitiveSignal envelope and JSONL sink.

Requirement Citations (docs/specs/mangomas-integration-core.md):
- R-MMI-1: immutable versioned envelope for cognitive-plane output
- R-MMI-2: fail-closed validation with logged rejections
- R-MMI-3: strict single-line JSONL persistence under a file lock
- R-MMI-4: workspace-scoped sink with MANGO_SIGNAL_DIR override
- C-MMI-1: `confidence` is untrusted metadata and never a control input
- C-MMI-2: producer identity fields carry no authority semantics

The frozen dataclass constructor is the deterministic escape hatch for tests
(pin `signal_id`/`timestamp` literals directly); do not monkeypatch module
globals to fake time or uuids.
"""

from __future__ import annotations

import dataclasses
import json
import logging
import math
import os
import re
import typing
import uuid
from datetime import datetime, timezone
from pathlib import Path

from harness.shared.meta_tools import DEFAULT_LOCK_POLL_S, DEFAULT_LOCK_TIMEOUT_S, file_lock

logger = logging.getLogger(__name__)

# Exact-pin versioning: any change to the envelope shape is a breaking change
# and requires a new accepted version (see spec Open questions).
ACCEPTED_SCHEMA_VERSION = "1.0.0"
SIGNAL_TYPE_PATTERN = re.compile(r"^[a-z][a-z0-9_-]*\.[a-z][a-z0-9_-]*$")
# Ceiling for one serialized signal line; oversized payloads are rejected, not
# truncated, so the sink can never be used to exhaust disk silently (R-MMI-3).
MAX_SIGNAL_BYTES = 262_144
# Ceiling for the whole append-only sink file. The sink is operator-pruned, so
# a full sink refuses further writes instead of filling the disk; the shadow
# channel contains the rejection, leaving the incumbent path unaffected.
MAX_SINK_BYTES = 64 * 1024 * 1024

SIGNAL_DIR_ENV = "MANGO_SIGNAL_DIR"
DEFAULT_SIGNAL_SUBDIR = Path(".mango") / "memory" / "signals"
SIGNAL_FILE_NAME = "cognitive-signals.jsonl"

_REQUIRED_STR_FIELDS = (
    "schema_version",
    "signal_id",
    "run_id",
    "task_id",
    "producer_id",
    "signal_type",
    "policy_id",
    "policy_version",
    "timestamp",
)


class SignalValidationError(ValueError):
    """Raised when a signal fails fail-closed validation (R-MMI-2)."""


@dataclasses.dataclass(frozen=True)
class CognitiveSignal:
    """One cognitive-plane observation. Identity metadata only — no field on
    this envelope grants, transfers, or modifies any authority (C-MMI-2)."""

    schema_version: str
    signal_id: str
    run_id: str
    task_id: str
    producer_id: str
    signal_type: str
    payload: dict[str, typing.Any]
    policy_id: str
    policy_version: str
    timestamp: str
    producer_version: str | None = None
    parent_signal_id: str | None = None
    evidence_refs: tuple[str, ...] = ()
    # Untrusted metadata (C-MMI-1): recorded verbatim for offline analysis,
    # never read by any control path in this repository.
    confidence: float | None = None

    def to_dict(self) -> dict[str, typing.Any]:
        return {
            "schema_version": self.schema_version,
            "signal_id": self.signal_id,
            "run_id": self.run_id,
            "task_id": self.task_id,
            "producer_id": self.producer_id,
            "signal_type": self.signal_type,
            "payload": self.payload,
            "policy_id": self.policy_id,
            "policy_version": self.policy_version,
            "timestamp": self.timestamp,
            "producer_version": self.producer_version,
            "parent_signal_id": self.parent_signal_id,
            "evidence_refs": list(self.evidence_refs),
            "confidence": self.confidence,
        }

    @classmethod
    def create(
        cls,
        *,
        run_id: str,
        task_id: str,
        producer_id: str,
        signal_type: str,
        payload: dict[str, typing.Any],
        policy_id: str,
        policy_version: str,
        producer_version: str | None = None,
        parent_signal_id: str | None = None,
        evidence_refs: typing.Sequence[str] = (),
        confidence: float | None = None,
    ) -> CognitiveSignal:
        """Factory stamping a fresh uuid4 id and a tz-aware UTC timestamp."""
        return cls(
            schema_version=ACCEPTED_SCHEMA_VERSION,
            signal_id=str(uuid.uuid4()),
            run_id=run_id,
            task_id=task_id,
            producer_id=producer_id,
            signal_type=signal_type,
            payload=payload,
            policy_id=policy_id,
            policy_version=policy_version,
            timestamp=datetime.now(timezone.utc).isoformat(),
            producer_version=producer_version,
            parent_signal_id=parent_signal_id,
            evidence_refs=tuple(evidence_refs),
            confidence=confidence,
        )


def _reject(reason: str) -> typing.NoReturn:
    logger.warning("cognitive_signal: rejected signal: %s", reason)
    raise SignalValidationError(reason)


def _parse_iso_timestamp(value: str) -> datetime:
    """`datetime.fromisoformat` accepts a trailing "Z" only from Python 3.11
    onward (verified: rejected on 3.10, accepted on 3.11/3.12); the CI matrix
    spans 3.9-3.12, and "Z" is the most common ISO-8601 UTC suffix an external
    producer would emit. Normalize it first so acceptance is interpreter-
    independent rather than a Python-version-dependent flake."""
    if value.endswith("Z"):
        value = value[:-1] + "+00:00"
    return datetime.fromisoformat(value)


def validate_signal_dict(data: typing.Mapping[str, typing.Any]) -> CognitiveSignal:
    """Fail-closed validation of a signal mapping (R-MMI-2).

    Accepts `evidence_refs` as a list or tuple of strings (JSON round-trips
    tuples as lists) and coerces to a tuple. Never coerces anything else.
    """
    if not isinstance(data, typing.Mapping):
        _reject(f"signal must be a mapping, got {type(data).__name__}")
    for field in _REQUIRED_STR_FIELDS:
        value = data.get(field)
        if not isinstance(value, str) or not value:
            _reject(f"field '{field}' must be a non-empty string")
    if data["schema_version"] != ACCEPTED_SCHEMA_VERSION:
        _reject(
            f"unsupported schema_version {data['schema_version']!r}; "
            f"accepted: {ACCEPTED_SCHEMA_VERSION}"
        )
    if not SIGNAL_TYPE_PATTERN.match(data["signal_type"]):
        _reject(f"malformed signal_type {data['signal_type']!r}")
    try:
        parsed = _parse_iso_timestamp(data["timestamp"])
    except ValueError:
        _reject(f"unparseable timestamp {data['timestamp']!r}")
    if parsed.tzinfo is None:
        _reject(f"timezone-naive timestamp {data['timestamp']!r}")
    payload = data.get("payload")
    if not isinstance(payload, dict):
        _reject("field 'payload' must be a dict")
    if not all(isinstance(k, str) for k in payload):
        _reject("field 'payload' keys must all be strings")
    for optional_str in ("producer_version", "parent_signal_id"):
        value = data.get(optional_str)
        if value is not None and not isinstance(value, str):
            _reject(f"field '{optional_str}' must be a string or null")
    refs = data.get("evidence_refs", ())
    if not isinstance(refs, (list, tuple)) or not all(isinstance(r, str) for r in refs):
        _reject("field 'evidence_refs' must be a list of strings")
    confidence = data.get("confidence")
    if confidence is not None:
        if isinstance(confidence, bool) or not isinstance(confidence, (int, float)):
            _reject("field 'confidence' must be a number or null")
        if math.isnan(float(confidence)) or not 0.0 <= float(confidence) <= 1.0:
            _reject(f"field 'confidence' out of range [0, 1]: {confidence!r}")
        confidence = float(confidence)
    unknown = set(data) - {f.name for f in dataclasses.fields(CognitiveSignal)}
    if unknown:
        _reject(f"unknown fields: {sorted(unknown)}")
    return CognitiveSignal(
        schema_version=data["schema_version"],
        signal_id=data["signal_id"],
        run_id=data["run_id"],
        task_id=data["task_id"],
        producer_id=data["producer_id"],
        signal_type=data["signal_type"],
        payload=payload,
        policy_id=data["policy_id"],
        policy_version=data["policy_version"],
        timestamp=data["timestamp"],
        producer_version=data.get("producer_version"),
        parent_signal_id=data.get("parent_signal_id"),
        evidence_refs=tuple(refs),
        confidence=confidence,
    )


class CognitiveSignalSink:
    """Append-only JSONL sink for validated signals (R-MMI-3, R-MMI-4)."""

    def __init__(
        self,
        base_dir: Path,
        file_name: str = SIGNAL_FILE_NAME,
        lock_timeout_s: float = DEFAULT_LOCK_TIMEOUT_S,
        lock_poll_s: float = DEFAULT_LOCK_POLL_S,
        max_sink_bytes: int = MAX_SINK_BYTES,
    ) -> None:
        self._base_dir = base_dir
        self._file_name = file_name
        self._lock_timeout_s = lock_timeout_s
        self._lock_poll_s = lock_poll_s
        self._max_sink_bytes = max_sink_bytes

    @classmethod
    def for_workspace(
        cls,
        workspace_dir: Path,
        environ: typing.Mapping[str, str] | None = None,
        **kwargs: typing.Any,
    ) -> CognitiveSignalSink:
        """Workspace-scoped sink; MANGO_SIGNAL_DIR overrides (operator trust)."""
        env = os.environ if environ is None else environ
        override = env.get(SIGNAL_DIR_ENV)
        base = (
            Path(override).resolve()
            if override
            else (Path(workspace_dir) / DEFAULT_SIGNAL_SUBDIR).resolve()
        )
        return cls(base, **kwargs)

    @property
    def path(self) -> Path:
        return self._base_dir / self._file_name

    def append(self, signal: CognitiveSignal) -> Path:
        """Validate and append one signal as a single strict-JSON line.

        Every rejection path raises ``SignalValidationError`` so callers have
        one exception type to contain: a payload carrying a non-JSON-serializable
        value is a malformed signal, not a caller bug, and must not leak a raw
        ``TypeError``/``ValueError``/``RecursionError`` from the serializer
        (R-MMI-2). ``ensure_ascii=True`` is deliberate, not the json.dumps
        default: it guarantees the line contains no character a Unicode-aware
        line splitter (e.g. ``str.splitlines()``) would treat as a break — a
        payload holding U+2028/U+2029/U+0085 would otherwise split into
        multiple "lines" for exactly the readers docs/specs and the
        shadow-channel-analysis skill describe — and it sidesteps
        ``UnicodeEncodeError`` on a lone surrogate entirely, since the
        serializer never needs to UTF-8-encode it directly.
        """
        as_dict = signal.to_dict()
        validate_signal_dict(as_dict)
        try:
            line = json.dumps(as_dict, allow_nan=False, ensure_ascii=True)
        except (TypeError, ValueError, RecursionError) as exc:
            _reject(f"payload is not JSON-serializable: {exc}")
        encoded = line.encode("utf-8")
        if len(encoded) > MAX_SIGNAL_BYTES:
            _reject(f"serialized signal is {len(encoded)} bytes; limit {MAX_SIGNAL_BYTES}")

        try:
            self._base_dir.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            # Covers FileExistsError (base_dir itself is a file) and
            # NotADirectoryError (a parent segment is a file) alike.
            _reject(f"cannot create sink directory {self._base_dir}: {exc}")
        target = self.path
        with file_lock(target, timeout_s=self._lock_timeout_s, poll_s=self._lock_poll_s):
            # Sink-level ceiling: the file is append-only and operator-pruned,
            # so refuse to grow it past the budget rather than filling the disk.
            # Checked under the lock so concurrent writers see the same size.
            current = target.stat().st_size if target.exists() else 0
            if current + len(encoded) + 1 > self._max_sink_bytes:
                _reject(
                    f"sink {target} would exceed {self._max_sink_bytes} bytes "
                    f"(currently {current}); export and prune before continuing"
                )
            with target.open("a", encoding="utf-8", newline="") as fh:
                fh.write(line + "\n")
        logger.info("cognitive_signal: appended %s signal %s", signal.signal_type, signal.signal_id)
        logger.debug(
            "cognitive_signal: sink %s now %d bytes (limit %d)",
            target,
            current + len(encoded) + 1,
            self._max_sink_bytes,
        )
        return target
