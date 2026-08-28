"""Unit tests for the pure retry/backoff arithmetic.

The point of extracting this module was that backoff could be asserted by
*value* instead of by counting ``time.sleep`` calls, so these tests assert
exact numbers with jitter disabled, and bounds with it enabled.
"""

from __future__ import annotations

import datetime as dt
import email.message
import email.utils
import io
import socket
import urllib.error
from typing import Any

import pytest

from harness.shared.retry_policy import (
    DEFAULT_BASE_SEC,
    DEFAULT_MAX_SEC,
    RETRYABLE_CONNECTION_ERRORS,
    RetryPolicy,
    is_retryable_connection_error,
    parse_retry_after,
)


class TestParseRetryAfter:
    @pytest.mark.parametrize(("raw", "expected"), [("0", 0.0), ("1", 1.0), ("120", 120.0)])
    def test_delta_seconds(self, raw: str, expected: float) -> None:
        assert parse_retry_after(raw) == expected

    def test_surrounding_whitespace_is_tolerated(self) -> None:
        assert parse_retry_after("  7  ") == 7.0

    def test_negative_delta_clamps_to_zero(self) -> None:
        assert parse_retry_after("-5") == 0.0

    @pytest.mark.parametrize("raw", [None, "", "   ", "soon", "12.5", "Mon, 99 Xxx 9999"])
    def test_unusable_values_return_none(self, raw: str | None) -> None:
        """None means "fall back to computed backoff". A malformed header must
        never be able to switch retrying off."""
        assert parse_retry_after(raw) is None

    def test_http_date_in_the_future(self) -> None:
        when = dt.datetime.now(dt.timezone.utc) + dt.timedelta(seconds=45)
        assert parse_retry_after(email.utils.format_datetime(when)) == pytest.approx(45, abs=2)

    def test_http_date_in_the_past_clamps_to_zero(self) -> None:
        past = email.utils.format_datetime(dt.datetime(2001, 1, 1, tzinfo=dt.timezone.utc))
        assert parse_retry_after(past) == 0.0

    def test_explicit_reference_time_makes_the_result_deterministic(self) -> None:
        when = dt.datetime(2030, 1, 1, 0, 1, 0, tzinfo=dt.timezone.utc)
        reference = dt.datetime(2030, 1, 1, 0, 0, 0, tzinfo=dt.timezone.utc).timestamp()
        assert parse_retry_after(email.utils.format_datetime(when), now=reference) == 60.0

    def test_very_old_date_clamps_like_any_past_date(self) -> None:
        assert parse_retry_after("Mon, 01 Jan 2001 00:00:00 GMT") == 0.0

    def test_a_date_whose_timestamp_overflows_returns_none(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """``timestamp()`` raises OverflowError/OSError for dates outside the
        platform epoch range -- on some platforms, not all. Injected rather
        than provoked with a literal date, so the defensive branch is covered
        identically everywhere instead of only where the C library cooperates.
        """

        class Overflowing:
            def timestamp(self) -> float:
                raise OverflowError("out of range for this platform")

        monkeypatch.setattr(
            "harness.shared.retry_policy.email.utils.parsedate_to_datetime",
            lambda _text: Overflowing(),
        )
        assert parse_retry_after("Mon, 01 Jan 2030 00:00:00 GMT") is None

    def test_a_parser_returning_none_is_handled(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Python 3.9's parser returns None where 3.10+ raises."""
        monkeypatch.setattr(
            "harness.shared.retry_policy.email.utils.parsedate_to_datetime", lambda _text: None
        )
        assert parse_retry_after("whatever") is None


class TestRetryPredicate:
    # Explicit ids, and a real file object for HTTPError. Both are required on
    # Python 3.9, which is a live CI matrix leg: there `urllib.response.addbase`
    # still inherits from `tempfile._TemporaryFileWrapper`, whose `__getattr__`
    # raises KeyError('file') for an uninitialised wrapper instead of returning
    # None as 3.10+ does. pytest builds parameter ids by calling
    # `getattr(value, "__name__", None)`, so an HTTPError constructed with
    # `fp=None` makes *collection* fail on 3.9 and pass everywhere else.
    @pytest.mark.parametrize(
        "exc",
        [
            urllib.error.URLError("down"),
            TimeoutError("slow"),
            socket.timeout("slow"),
            ConnectionResetError("reset"),
            ConnectionAbortedError("aborted"),
        ],
        ids=["urlerror", "timeouterror", "socket-timeout", "conn-reset", "conn-aborted"],
    )
    def test_transport_failures_are_retryable(self, exc: BaseException) -> None:
        assert is_retryable_connection_error(exc)

    @pytest.mark.parametrize(
        "exc",
        [
            urllib.error.HTTPError("url", 500, "boom", email.message.Message(), io.BytesIO(b"")),
            ValueError("bad input"),
            KeyError("missing"),
            MemoryError(),
        ],
        ids=["http-error", "value-error", "key-error", "memory-error"],
    )
    def test_everything_else_is_not(self, exc: BaseException) -> None:
        assert not is_retryable_connection_error(exc)

    def test_socket_timeout_is_listed_explicitly(self) -> None:
        """Pins the 3.9 fix: the alias to TimeoutError only exists from 3.10."""
        assert socket.timeout in RETRYABLE_CONNECTION_ERRORS


class TestFromMapping:
    def test_defaults_when_the_mapping_is_empty(self) -> None:
        assert RetryPolicy.from_mapping({}) == RetryPolicy()

    def test_every_knob_is_readable(self) -> None:
        policy = RetryPolicy.from_mapping(
            {"max_retries": "5", "retry_base_sec": "0.5", "retry_max_sec": "8", "retry_jitter_ratio": "0.5"}
        )
        assert (policy.max_retries, policy.base_sec, policy.max_sec, policy.jitter_ratio) == (5, 0.5, 8.0, 0.5)

    @pytest.mark.parametrize("garbage", ["", "abc", "1.2.3", "None"])
    def test_unparseable_values_fall_back_to_defaults(self, garbage: str) -> None:
        """Normalising beats raising: a bad env value must not take down the
        request path whose entire job is tolerating failure."""
        policy = RetryPolicy.from_mapping({"max_retries": garbage, "retry_base_sec": garbage})
        assert policy.max_retries == RetryPolicy().max_retries
        assert policy.base_sec == DEFAULT_BASE_SEC

    def test_float_knob_accepts_an_integer_string(self) -> None:
        assert RetryPolicy.from_mapping({"retry_max_sec": "12"}).max_sec == 12.0

    def test_int_knob_rejects_a_float_string(self) -> None:
        assert RetryPolicy.from_mapping({"max_retries": "2.7"}).max_retries == 0


class TestNormalisation:
    @pytest.mark.parametrize(
        ("field", "given", "expected"),
        [
            ("max_retries", -3, 0),
            ("base_sec", -1.0, 0.0),
            ("max_sec", -5.0, 0.0),
            ("jitter_ratio", -0.5, 0.0),
            ("jitter_ratio", 4.0, 1.0),
        ],
    )
    def test_out_of_range_values_are_clamped(self, field: str, given: float, expected: float) -> None:
        kwargs: dict[str, Any] = {field: given}
        assert getattr(RetryPolicy(**kwargs), field) == expected

    def test_the_policy_is_immutable(self) -> None:
        with pytest.raises(Exception):
            RetryPolicy().max_retries = 9  # type: ignore[misc]


class TestBackoff:
    def test_doubles_without_jitter(self) -> None:
        policy = RetryPolicy(base_sec=1.0, max_sec=1000.0, jitter_ratio=0.0)
        assert [policy.backoff(i) for i in range(5)] == [1.0, 2.0, 4.0, 8.0, 16.0]

    def test_is_capped(self) -> None:
        policy = RetryPolicy(base_sec=1.0, max_sec=10.0, jitter_ratio=0.0)
        assert policy.backoff(20) == 10.0

    def test_negative_attempt_is_treated_as_the_first(self) -> None:
        assert RetryPolicy(jitter_ratio=0.0).backoff(-1) == DEFAULT_BASE_SEC

    def test_retry_after_overrides_and_skips_jitter(self) -> None:
        policy = RetryPolicy(jitter_ratio=1.0)
        assert policy.backoff(3, retry_after=2.0) == 2.0

    def test_retry_after_is_capped(self) -> None:
        assert RetryPolicy().backoff(0, retry_after=10_000) == DEFAULT_MAX_SEC

    def test_negative_retry_after_clamps_to_zero(self) -> None:
        assert RetryPolicy().backoff(0, retry_after=-9) == 0.0

    @pytest.mark.parametrize("draw", [0.0, 0.5, 1.0])
    def test_jitter_stays_inside_its_band(self, draw: float) -> None:
        policy = RetryPolicy(base_sec=4.0, max_sec=100.0, jitter_ratio=0.25)
        assert 3.0 <= policy.backoff(0, rand=lambda: draw) <= 4.0

    def test_full_jitter_can_reach_zero(self) -> None:
        policy = RetryPolicy(base_sec=4.0, jitter_ratio=1.0)
        assert policy.backoff(0, rand=lambda: 0.0) == 0.0

    def test_default_rand_is_used_when_none_is_given(self) -> None:
        policy = RetryPolicy(base_sec=2.0, max_sec=100.0, jitter_ratio=0.5)
        assert all(1.0 <= policy.backoff(0) <= 2.0 for _ in range(50))


class TestShouldRetry:
    def test_budget_is_exclusive_of_the_final_attempt(self) -> None:
        policy = RetryPolicy(max_retries=2)
        assert [policy.should_retry(i) for i in range(4)] == [True, True, False, False]

    def test_zero_budget_never_retries(self) -> None:
        assert RetryPolicy(max_retries=0).should_retry(0) is False
