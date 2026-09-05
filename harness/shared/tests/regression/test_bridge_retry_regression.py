"""Regressions for Nemotron bridge retry handling.

Defects reproduced here (all present on ``main`` before this change):

1. Read timeouts were never retried on Python 3.9, and peer resets were never
   retried on any version.
2. The urllib Request was built once and replayed across attempts.
3. A server's ``Retry-After`` was ignored in favour of guessed backoff.
4. Backoff grew without a ceiling.
5. A non-JSON body on an HTTP 200 was reported as a connection error.
6. ``.env`` was consulted only when credentials were missing, making the
   retry/timeout knobs unreachable in the normal case.
7. ``test_complete_chat_no_retry_by_default`` leaked: it only set
   ``NEMOTRON_DEFAULT_MODEL`` and ``NEMOTRON_MAX_RETRIES=0``, leaving
   the other env vars absent, so ``resolve_environment()`` fell through to
   ``.env`` which contained ``NEMOTRON_MAX_RETRIES=3``. The test observed
   3 retry attempts instead of the expected 0. (**DEF-014**)
"""

from __future__ import annotations

import email.message
import io
import json
import os
import socket
import urllib.error
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from harness.shared import nemotron_bridge
from harness.shared.nemotron_bridge import complete_chat
from harness.shared.retry_policy import RETRYABLE_CONNECTION_ERRORS, RetryPolicy, is_retryable_connection_error

# The tier is selected by path (``make test-regression``), not by marker: the
# directory already is the selector, and a marker would additionally require
# registering it in the protected pyproject.toml for no extra selectivity.


def _ok_response(body: bytes = b'{"choices": [{"message": {"content": "ok"}}]}') -> MagicMock:
    resp = MagicMock()
    resp.read.return_value = body
    resp.__enter__.return_value = resp
    return resp


def _headers(**fields: str) -> email.message.Message:
    """HTTPError.headers is an email Message in production, not a dict; using
    the real type keeps header lookups (case-insensitive ``get``) faithful."""
    message = email.message.Message()
    for key, value in fields.items():
        message[key.replace("_", "-")] = value
    return message


def _env(**overrides: str) -> dict[str, str]:
    base = {"NEMOTRON_DEFAULT_MODEL": "dummy-model"}
    base.update(overrides)
    return base


class TestRetryPredicate:
    def test_socket_timeout_is_retryable_on_every_python(self) -> None:
        """``socket.timeout`` only became an alias of ``TimeoutError`` in 3.10.

        This assertion is a tuple-membership check rather than a behavioural
        one on purpose: on 3.10+ the alias makes the *old* code look correct,
        so a behavioural test would pass on this interpreter and hide the
        defect on the 3.9 leg of the CI matrix, which is where it bit.
        """
        assert socket.timeout in RETRYABLE_CONNECTION_ERRORS
        assert is_retryable_connection_error(socket.timeout())

    def test_http_error_is_not_a_connection_error(self) -> None:
        """HTTPError subclasses URLError; status codes, not transport, decide."""
        err = urllib.error.HTTPError("url", 500, "boom", _headers(), io.BytesIO(b""))
        assert not is_retryable_connection_error(err)

    @patch("harness.shared.nemotron_bridge.time.sleep")
    @patch("urllib.request.urlopen")
    def test_peer_reset_mid_read_is_retried(self, mock_urlopen: MagicMock, mock_sleep: MagicMock) -> None:
        """``ConnectionResetError`` is an OSError urllib does not wrap.

        The old predicate matched only URLError/TimeoutError, so a reset
        surfaced immediately no matter how NEMOTRON_MAX_RETRIES was set.
        """
        mock_urlopen.side_effect = [ConnectionResetError("peer reset"), _ok_response()]
        with patch.dict("os.environ", _env(NEMOTRON_MAX_RETRIES="2")):
            result = complete_chat([], api_key="secret-key")
        assert result["choices"][0]["message"]["content"] == "ok"
        assert mock_urlopen.call_count == 2
        mock_sleep.assert_called_once()


class TestRequestReuse:
    @patch("harness.shared.nemotron_bridge.time.sleep")
    @patch("urllib.request.urlopen")
    def test_each_attempt_gets_a_fresh_request(self, mock_urlopen: MagicMock, mock_sleep: MagicMock) -> None:
        """A Request accumulates opener/redirect state; replaying one resends
        something other than what was composed."""
        mock_urlopen.side_effect = [urllib.error.URLError("down"), _ok_response()]
        with patch.dict("os.environ", _env(NEMOTRON_MAX_RETRIES="2")):
            complete_chat([], api_key="secret-key")

        sent = [call.args[0] for call in mock_urlopen.call_args_list]
        assert len(sent) == 2
        assert sent[0] is not sent[1], "the same Request object was replayed across attempts"
        # Distinct objects still have to carry identical intent.
        assert sent[0].full_url == sent[1].full_url
        assert sent[0].data == sent[1].data


class TestRetryAfter:
    @patch("harness.shared.nemotron_bridge.time.sleep")
    @patch("urllib.request.urlopen")
    def test_retry_after_header_overrides_computed_backoff(
        self, mock_urlopen: MagicMock, mock_sleep: MagicMock
    ) -> None:
        """A 429 carrying Retry-After is the origin telling us when to return."""
        err = urllib.error.HTTPError("url", 429, "Too Many", _headers(Retry_After="5"), io.BytesIO(b"slow down"))
        mock_urlopen.side_effect = [err, _ok_response()]
        with patch.dict("os.environ", _env(NEMOTRON_MAX_RETRIES="2")):
            complete_chat([], api_key="secret-key")

        # Computed backoff for attempt 0 is 1s (jittered); the header says 5.
        assert mock_sleep.call_args.args[0] == pytest.approx(5.0)

    @patch("harness.shared.nemotron_bridge.time.sleep")
    @patch("urllib.request.urlopen")
    def test_garbage_retry_after_falls_back_instead_of_disabling_retry(
        self, mock_urlopen: MagicMock, mock_sleep: MagicMock
    ) -> None:
        err = urllib.error.HTTPError("url", 503, "Nope", _headers(Retry_After="whenever"), io.BytesIO(b"x"))
        mock_urlopen.side_effect = [err, _ok_response()]
        with patch.dict("os.environ", _env(NEMOTRON_MAX_RETRIES="2")):
            complete_chat([], api_key="secret-key")

        assert mock_urlopen.call_count == 2
        assert mock_sleep.call_args.args[0] > 0

    @patch("harness.shared.nemotron_bridge.time.sleep")
    @patch("urllib.request.urlopen")
    def test_bridge_backoff_never_exceeds_the_cap(self, mock_urlopen: MagicMock, mock_sleep: MagicMock) -> None:
        """Unbounded doubling reached ~34 minutes on the 11th retry, so a
        transient outage turned a build into a hang rather than a failure."""
        mock_urlopen.side_effect = urllib.error.URLError("down")
        with patch.dict("os.environ", _env(NEMOTRON_MAX_RETRIES="12")):
            with pytest.raises(RuntimeError):
                complete_chat([], api_key="secret-key")

        delays = [call.args[0] for call in mock_sleep.call_args_list]
        assert len(delays) == 12
        assert max(delays) <= RetryPolicy().max_sec

    def test_explicit_retry_after_is_also_capped(self) -> None:
        """A hostile or mistaken header must not be able to stall a build."""
        policy = RetryPolicy(jitter_ratio=0.0)
        assert policy.backoff(0, retry_after=86_400) == policy.max_sec


class TestResponseBodyErrors:
    @patch("urllib.request.urlopen")
    def test_non_json_200_body_is_not_reported_as_a_connection_error(self, mock_urlopen: MagicMock) -> None:
        """A proxy's HTML error page on a 200 is a protocol failure. Reporting
        it as "Connection Error" sent operators to the wrong subsystem."""
        mock_urlopen.return_value = _ok_response(b"<html>gateway</html>")
        with patch.dict("os.environ", _env()):
            with pytest.raises(RuntimeError, match="non-JSON body"):
                complete_chat([], api_key="secret-key")

    @patch("urllib.request.urlopen")
    def test_json_scalar_body_is_rejected(self, mock_urlopen: MagicMock) -> None:
        """Valid JSON that is not an object would fail later on ``data[...]``."""
        mock_urlopen.return_value = _ok_response(b'"just a string"')
        with patch.dict("os.environ", _env()):
            with pytest.raises(RuntimeError, match="expected a JSON object"):
                complete_chat([], api_key="secret-key")

    @patch("urllib.request.urlopen")
    def test_secret_never_appears_in_a_surfaced_error(self, mock_urlopen: MagicMock) -> None:
        secret = "nvapi-super-secret-token-value"
        mock_urlopen.side_effect = urllib.error.URLError(f"refused for {secret}")
        with patch.dict("os.environ", _env()):
            with pytest.raises(RuntimeError) as excinfo:
                complete_chat([], api_key=secret)
        assert secret not in str(excinfo.value)


class TestDotEnvReachability:
    def test_env_file_supplies_knobs_when_credentials_are_already_set(
        self, tmp_path: Any, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The old guard returned as soon as api_key and default_model were in
        the process environment, so NEMOTRON_MAX_RETRIES / NEMOTRON_TIMEOUT_MS
        in a ``.env`` were unreachable in exactly the normal configuration.

        Uses a real directory tree rather than patching the module's ``Path``,
        so the three-level parent walk is genuinely exercised.
        """
        pkg = tmp_path / "repo" / "harness" / "shared"
        pkg.mkdir(parents=True)
        (tmp_path / "repo" / ".env").write_text("NEMOTRON_MAX_RETRIES=4\nNEMOTRON_TIMEOUT_MS=7000\n", encoding="utf-8")
        monkeypatch.setattr(nemotron_bridge, "__file__", str(pkg / "nemotron_bridge.py"))
        monkeypatch.setenv("NVIDIA_API_KEY", "process-key")
        monkeypatch.setenv("NEMOTRON_DEFAULT_MODEL", "process-model")
        monkeypatch.delenv("NEMOTRON_MAX_RETRIES", raising=False)
        monkeypatch.delenv("NEMOTRON_TIMEOUT_MS", raising=False)
        monkeypatch.delenv("NVIDIA_BASE_URL", raising=False)

        resolved = nemotron_bridge.resolve_environment()
        assert resolved["max_retries"] == "4"
        assert resolved["timeout_ms"] == "7000"
        # The process environment still wins for keys it supplies.
        assert resolved["api_key"] == "process-key"

    def test_process_environment_still_wins_over_env_file(self, tmp_path: Any, monkeypatch: pytest.MonkeyPatch) -> None:
        pkg = tmp_path / "repo" / "harness" / "shared"
        pkg.mkdir(parents=True)
        (tmp_path / "repo" / ".env").write_text("NVIDIA_API_KEY=file-key\n", encoding="utf-8")
        monkeypatch.setattr(nemotron_bridge, "__file__", str(pkg / "nemotron_bridge.py"))
        monkeypatch.setenv("NVIDIA_API_KEY", "process-key")

        assert nemotron_bridge.resolve_environment()["api_key"] == "process-key"


class TestUrlSchemeGuard:
    def test_non_http_endpoint_is_rejected(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """The scheme guard is what stops NVIDIA_BASE_URL from turning the
        bridge into a ``file://`` reader. It had no test before this one."""
        monkeypatch.setenv("NEMOTRON_DEFAULT_MODEL", "dummy-model")
        with pytest.raises(ValueError, match="Invalid URL scheme"):
            complete_chat([], api_key="secret-key", base_url="file:///etc")

    @patch("urllib.request.urlopen")
    def test_payload_is_still_well_formed_json(self, mock_urlopen: MagicMock) -> None:
        mock_urlopen.return_value = _ok_response()
        with patch.dict("os.environ", _env()):
            complete_chat([{"role": "user", "content": "hi"}], api_key="secret-key")
        body = json.loads(mock_urlopen.call_args.args[0].data.decode("utf-8"))
        assert body["model"] == "dummy-model"
        assert body["messages"] == [{"role": "user", "content": "hi"}]
        assert body["stream"] is False


class TestEnvFileDoesNotOverrideRetryKnob:
    """Defect 7.  A ``.env`` file in the workspace with ``NEMOTRON_MAX_RETRIES=3``
    overwrote the test's explicit ``0``, making a no-retry test observe 3 retries.

    Root cause: ``resolve_environment()`` short-circuits only when *every*
    mapped env var is present.  A test that sets only ``NEMOTRON_DEFAULT_MODEL``
    and ``NEMOTRON_MAX_RETRIES=0`` leaves ``NVIDIA_API_KEY``, ``NVIDIA_BASE_URL``,
    and ``NEMOTRON_TIMEOUT_MS`` absent — so it falls through to the ``.env``
    parse path, and ``.env`` wins because the "process env takes precedence"
    guard (``if not env_vars[key_name]``) only fires for keys already set.

    After the fix, the test now supplies every env var so the short-circuit fires.
    """

    @patch("harness.shared.nemotron_bridge.time.sleep")
    @patch("urllib.request.urlopen")
    def test_no_retry_with_all_env_vars_populated(
        self,
        mock_urlopen: MagicMock,
        mock_sleep: MagicMock,
    ) -> None:
        """With ``NEMOTRON_MAX_RETRIES=0`` AND all other env vars populated,
        a 503 must surface immediately — zero retries, zero sleeps."""
        err = urllib.error.HTTPError(
            "url",
            503,
            "Service Unavailable",
            _headers(),
            io.BytesIO(b"busy"),
        )
        mock_urlopen.side_effect = err

        # Supply *every* env key so resolve_environment() short-circuits
        # before consulting any .env file.
        full_env = {
            "NEMOTRON_DEFAULT_MODEL": "dummy-model",
            "NEMOTRON_MAX_RETRIES": "0",
            "NVIDIA_API_KEY": "test-key",
            "NVIDIA_BASE_URL": "https://example.com/v1",
            "NEMOTRON_TIMEOUT_MS": "30000",
        }
        with patch.dict(os.environ, full_env, clear=False):
            with pytest.raises(RuntimeError, match="HTTP 503"):
                complete_chat([], api_key="secret-key")

        assert mock_urlopen.call_count == 1, (
            f"Expected 1 call (no retries) but got {mock_urlopen.call_count}; "
            "the .env file likely leaked NEMOTRON_MAX_RETRIES"
        )
        mock_sleep.assert_not_called()

    def test_resolve_environment_returns_zero_retries_when_fully_populated(self) -> None:
        """Directly verify the short-circuit: all 5 keys present → returned
        verbatim, no filesystem I/O."""
        full_env = {
            "NVIDIA_API_KEY": "test-key",
            "NVIDIA_BASE_URL": "https://example.com/v1",
            "NEMOTRON_DEFAULT_MODEL": "dummy-model",
            "NEMOTRON_TIMEOUT_MS": "30000",
            "NEMOTRON_MAX_RETRIES": "0",
        }
        with patch.dict(os.environ, full_env, clear=False):
            result = nemotron_bridge.resolve_environment()

        assert result["max_retries"] == "0", f"Expected max_retries='0' but got {result['max_retries']!r}"
