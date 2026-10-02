"""Pure retry/backoff arithmetic for the Nemotron bridge.

Extracted from ``nemotron_bridge.complete_chat`` so that backoff behavior can be
asserted **by value** rather than by counting ``time.sleep`` calls, and so the
bridge does not grow branches for arithmetic that has nothing to do with HTTP.

No environment reads, no network, no logging, and no I/O of any kind.
``RetryPolicy.from_mapping`` takes an already-resolved mapping (the bridge
passes ``resolve_environment()``'s result) rather than reading ``os.environ``
itself, so the module can be exercised without monkeypatching global state.

Two impurities remain, and both are *injectable defaults* rather than hidden
state: ``parse_retry_after`` reads the clock via ``time.time()`` when no
``now`` is passed, and ``RetryPolicy.backoff`` draws from ``random.random()``
when no ``rand`` is passed. Supply either parameter and the function is
deterministic -- which is how the tests assert exact delays. They are defaults
rather than required arguments because forcing every caller to thread a clock
and an RNG through the bridge's retry loop would trade real ergonomics for
purity the callers do not need.
"""

from __future__ import annotations

import email.utils
import random
import socket
import time
import urllib.error
from collections.abc import Callable, Mapping
from dataclasses import dataclass

# Documented fallbacks, mirroring the bridge's existing constant style. Each is
# overridable through the mapping passed to ``from_mapping`` (NEMOTRON_* keys),
# so no caller is stuck with a literal.
DEFAULT_MAX_RETRIES = 0
DEFAULT_BASE_SEC = 1.0
DEFAULT_MAX_SEC = 30.0
# Proportional jitter: the delay is drawn from [delay * (1 - ratio), delay].
# 0.0 makes backoff fully deterministic, which is what the unit tests use.
DEFAULT_JITTER_RATIO = 0.25

# Connection-level failures worth retrying.
#
# ``socket.timeout`` became an alias of ``TimeoutError`` in Python 3.10, so on
# this repo's floor (docs/specs/python-floor-310.md) the two entries name one
# class and either alone would match. The pair is kept for the history it
# records: before the floor moved, a bare ``TimeoutError`` never matched the read
# timeouts ``urlopen`` raises on 3.9, so every one of them fell through unretried
# no matter how NEMOTRON_MAX_RETRIES was set. Listing both stays correct on every
# version.
#
# ``ConnectionError`` covers peer resets raised mid-read, which urllib does not
# wrap in ``URLError``.
RETRYABLE_CONNECTION_ERRORS = (
    urllib.error.URLError,
    TimeoutError,
    socket.timeout,
    ConnectionError,
)


def is_retryable_connection_error(exc: BaseException) -> bool:
    """True for transport-level failures that a retry could plausibly fix.

    ``HTTPError`` is deliberately excluded even though it subclasses
    ``URLError``: the server answered, so the status code decides retryability
    (see ``RETRYABLE_HTTP_STATUSES`` in the bridge), not the transport.
    """
    if isinstance(exc, urllib.error.HTTPError):
        return False
    return isinstance(exc, RETRYABLE_CONNECTION_ERRORS)


def parse_retry_after(raw: str | None, now: float | None = None) -> float | None:
    """Parse an HTTP ``Retry-After`` header into seconds, or None if unusable.

    Both RFC 9110 forms are accepted: delta-seconds and an HTTP-date. A date in
    the past yields ``0.0`` (retry immediately) rather than a negative delay.
    Garbage returns None so the caller falls back to computed backoff — a
    malformed header must not disable retrying.
    """
    if raw is None:
        return None
    text = raw.strip()
    if not text:
        return None
    try:
        return max(0.0, float(int(text)))
    except ValueError:
        pass
    # ``parsedate_to_datetime`` signals an unparseable header by *raising*, never
    # by returning ``None``: on this repo's 3.10 floor (``requires-python =
    # ">=3.10"``, docs/specs/python-floor-310.md) it rejects whatever
    # ``_parsedate_tz`` could not read with ``ValueError``. This single ``except``
    # is therefore the whole guard, and no ``parsed is None`` test follows it --
    # that check was dead on every supported interpreter, which mypy's
    # ``--warn-unreachable`` flagged. ``TypeError`` stays in the tuple because a
    # ``bytes`` header from an untyped caller raises that instead; either way a
    # garbage ``Retry-After`` must fall back to computed backoff rather than
    # raise through the retry loop.
    try:
        parsed = email.utils.parsedate_to_datetime(text)
    except (TypeError, ValueError):
        return None
    try:
        target = parsed.timestamp()
    except (OverflowError, OSError, ValueError):
        return None
    reference = time.time() if now is None else now
    return max(0.0, target - reference)


def _coerce_int(mapping: Mapping[str, str], key: str, default: int) -> int:
    raw = mapping.get(key, "")
    if not raw:
        return default
    try:
        return int(raw)
    except (TypeError, ValueError):
        return default


def _coerce_float(mapping: Mapping[str, str], key: str, default: float) -> float:
    raw = mapping.get(key, "")
    if not raw:
        return default
    try:
        return float(raw)
    except (TypeError, ValueError):
        return default


@dataclass(frozen=True)
class RetryPolicy:
    """Immutable retry configuration plus the backoff arithmetic that uses it."""

    max_retries: int = DEFAULT_MAX_RETRIES
    base_sec: float = DEFAULT_BASE_SEC
    max_sec: float = DEFAULT_MAX_SEC
    jitter_ratio: float = DEFAULT_JITTER_RATIO

    def __post_init__(self) -> None:
        # Normalize rather than raise: a bad env value must not take down a
        # request path whose whole job is tolerating failure.
        object.__setattr__(self, "max_retries", max(0, self.max_retries))
        object.__setattr__(self, "base_sec", max(0.0, self.base_sec))
        object.__setattr__(self, "max_sec", max(0.0, self.max_sec))
        object.__setattr__(self, "jitter_ratio", min(1.0, max(0.0, self.jitter_ratio)))

    @classmethod
    def from_mapping(cls, env: Mapping[str, str]) -> RetryPolicy:
        """Build a policy from an already-resolved environment mapping.

        Keys are the ``resolve_environment()`` names, so an adopter setting only
        ``NEMOTRON_MAX_RETRIES`` keeps every other default.
        """
        return cls(
            max_retries=_coerce_int(env, "max_retries", DEFAULT_MAX_RETRIES),
            base_sec=_coerce_float(env, "retry_base_sec", DEFAULT_BASE_SEC),
            max_sec=_coerce_float(env, "retry_max_sec", DEFAULT_MAX_SEC),
            jitter_ratio=_coerce_float(env, "retry_jitter_ratio", DEFAULT_JITTER_RATIO),
        )

    def should_retry(self, attempt: int) -> bool:
        """True while ``attempt`` (0-based) still has a retry left."""
        return attempt < self.max_retries

    def backoff(
        self,
        attempt: int,
        retry_after: float | None = None,
        rand: Callable[[], float] | None = None,
    ) -> float:
        """Seconds to wait before the attempt following ``attempt`` (0-based).

        A server-supplied ``retry_after`` wins over computed backoff — it is the
        origin telling us when it will be ready — but is still capped by
        ``max_sec`` so a hostile or mistaken header cannot stall a build. Jitter
        is applied only to computed backoff, never to an explicit instruction.
        """
        if retry_after is not None:
            return min(max(0.0, retry_after), self.max_sec)
        raw: float = self.base_sec * float(2 ** max(0, attempt))
        capped: float = min(raw, self.max_sec)
        if self.jitter_ratio == 0.0:
            return capped
        draw: float = (rand or random.random)()
        return capped * (1.0 - self.jitter_ratio + self.jitter_ratio * draw)
