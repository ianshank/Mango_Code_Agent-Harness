import email.message
import io
import json
import os
import urllib.error
from unittest.mock import MagicMock, patch

import pytest

from harness.shared.nemotron_bridge import (
    complete_chat,
    main,
    mask_secret,
    resolve_api_key,
)


def test_resolve_api_key_from_env():
    with patch.dict(os.environ, {"NVIDIA_API_KEY": "test_env_key"}):
        assert resolve_api_key() == "test_env_key"


def test_resolve_api_key_from_dotenv(tmp_path):
    env_file = tmp_path / ".env"
    env_file.write_text("NVIDIA_API_KEY=test_dot_key\nOTHER=foo")

    # Mock Path(__file__) parent traversal
    with patch("harness.shared.nemotron_bridge.Path") as mock_path_class:
        mock_current = MagicMock()
        mock_current.parent = tmp_path
        mock_path_class.return_value.resolve.return_value = mock_current

        with patch.dict(os.environ, {}, clear=True):
            assert resolve_api_key() == "test_dot_key"


def test_resolve_api_key_missing(tmp_path):
    with patch("harness.shared.nemotron_bridge.Path") as mock_path_class:
        mock_current = MagicMock()
        mock_current.parent = tmp_path
        mock_path_class.return_value.resolve.return_value = mock_current

        with patch.dict(os.environ, {}, clear=True):
            assert resolve_api_key() == ""


@patch("urllib.request.urlopen")
def test_complete_chat_success(mock_urlopen):
    mock_resp = MagicMock()
    mock_resp.read.return_value = (
        b'{"choices": [{"message": {"content": "mock response"}}], "usage": {"total_tokens": 10}}'
    )
    mock_resp.__enter__.return_value = mock_resp
    mock_urlopen.return_value = mock_resp

    messages = [{"role": "user", "content": "hello"}]
    with patch.dict(os.environ, {"NEMOTRON_DEFAULT_MODEL": "dummy-model"}):
        res = complete_chat(messages, api_key="secret-key", timeout_sec=1)

    assert res["choices"][0]["message"]["content"] == "mock response"
    assert "latency_ms" in res
    mock_urlopen.assert_called_once()


@patch(
    "harness.shared.nemotron_bridge.resolve_environment",
    return_value={"api_key": "", "base_url": "", "default_model": ""},
)
@patch("urllib.request.urlopen")
def test_complete_chat_missing_key(mock_urlopen, mock_resolve):
    with pytest.raises(ValueError, match="NVIDIA_API_KEY is not configured"):
        complete_chat([], api_key="")


@patch("urllib.request.urlopen")
def test_complete_chat_http_error(mock_urlopen):
    err = urllib.error.HTTPError(
        "url", 401, "Unauthorized", email.message.Message(),
        io.BytesIO(b"Bad Key my_secret_key"),
    )
    mock_urlopen.side_effect = err

    with pytest.raises(RuntimeError) as exc:
        with patch.dict(os.environ, {"NEMOTRON_DEFAULT_MODEL": "dummy-model"}):
            complete_chat([], api_key="my_secret_key")

    # Assert secret is masked
    assert "my_secret_key" not in str(exc.value)
    assert mask_secret("my_secret_key") in str(exc.value)


@patch("urllib.request.urlopen")
def test_complete_chat_connection_error(mock_urlopen):
    mock_urlopen.side_effect = Exception("Connection failed due to token my_secret_key")

    with pytest.raises(RuntimeError) as exc:
        with patch.dict(os.environ, {"NEMOTRON_DEFAULT_MODEL": "dummy-model"}):
            complete_chat([], api_key="my_secret_key")

    assert "my_secret_key" not in str(exc.value)
    assert mask_secret("my_secret_key") in str(exc.value)


@patch("sys.argv", ["nemotron_bridge.py", "--prompt", "Hello", "--json"])
@patch("harness.shared.nemotron_bridge.complete_chat")
@patch("sys.stdout", new_callable=io.StringIO)
def test_main_json_output(mock_stdout, mock_complete):
    mock_complete.return_value = {"choices": []}
    main()
    output = mock_stdout.getvalue()
    assert json.loads(output) == {"choices": []}


@patch("sys.argv", ["nemotron_bridge.py", "--prompt", "Hello"])
@patch("harness.shared.nemotron_bridge.complete_chat")
@patch("sys.stdout", new_callable=io.StringIO)
def test_main_text_output(mock_stdout, mock_complete):
    mock_complete.return_value = {
        "model": "test-model",
        "latency_ms": 100,
        "choices": [{"message": {"content": "text response"}}],
        "usage": {"total_tokens": 10},
    }
    main()
    output = mock_stdout.getvalue()
    assert "Nemotron Response" in output
    assert "text response" in output
    assert "Tokens:" in output


@patch("sys.argv", ["nemotron_bridge.py", "--prompt", "Hello"])
@patch("harness.shared.nemotron_bridge.complete_chat")
@patch("sys.stdout", new_callable=io.StringIO)
def test_main_error_exit(mock_stdout, mock_complete):
    mock_complete.side_effect = Exception("mock error")
    with pytest.raises(SystemExit) as exc:
        main()
    assert exc.value.code == 1
    assert "mock error" in mock_stdout.getvalue()


# --- Retry / environment-knob behavior (spec: orchestrator-tool-registry) ---


def _mock_success_response():
    mock_resp = MagicMock()
    mock_resp.read.return_value = b'{"choices": [{"message": {"content": "ok"}}]}'
    mock_resp.__enter__.return_value = mock_resp
    return mock_resp


@patch("harness.shared.nemotron_bridge.time.sleep")
@patch("urllib.request.urlopen")
def test_complete_chat_retries_transient_http_error(mock_urlopen, mock_sleep):
    """With NEMOTRON_MAX_RETRIES set, a transient 503 is retried to success."""
    err = urllib.error.HTTPError("url", 503, "Service Unavailable", email.message.Message(), io.BytesIO(b"busy"))
    mock_urlopen.side_effect = [err, _mock_success_response()]

    with patch.dict(os.environ, {"NEMOTRON_DEFAULT_MODEL": "dummy-model", "NEMOTRON_MAX_RETRIES": "2"}):
        res = complete_chat([], api_key="secret-key")

    assert res["choices"][0]["message"]["content"] == "ok"
    assert mock_urlopen.call_count == 2
    mock_sleep.assert_called_once()


@patch("harness.shared.nemotron_bridge.time.sleep")
@patch("urllib.request.urlopen")
def test_complete_chat_no_retry_by_default(mock_urlopen, mock_sleep):
    """Retries default to 0: a transient failure surfaces immediately."""
    err = urllib.error.HTTPError("url", 503, "Service Unavailable", email.message.Message(), io.BytesIO(b"busy"))
    mock_urlopen.side_effect = err

    # Supply every env key so resolve_environment()'s short-circuit fires
    # before it reads .env (which may set NEMOTRON_MAX_RETRIES=3).
    with patch.dict(os.environ, {
        "NEMOTRON_DEFAULT_MODEL": "dummy-model",
        "NEMOTRON_MAX_RETRIES": "0",
        "NVIDIA_API_KEY": "test-key",
        "NVIDIA_BASE_URL": "https://example.com/v1",
        "NEMOTRON_TIMEOUT_MS": "30000",
    }, clear=False):
        with pytest.raises(RuntimeError, match="HTTP 503"):
            complete_chat([], api_key="secret-key")

    assert mock_urlopen.call_count == 1
    mock_sleep.assert_not_called()


@patch("harness.shared.nemotron_bridge.time.sleep")
@patch("urllib.request.urlopen")
def test_complete_chat_non_transient_http_error_never_retried(mock_urlopen, mock_sleep):
    """A 401 is not transient: no retry even with the knob set."""
    err = urllib.error.HTTPError("url", 401, "Unauthorized", email.message.Message(), io.BytesIO(b"bad key"))
    mock_urlopen.side_effect = err

    with patch.dict(os.environ, {"NEMOTRON_DEFAULT_MODEL": "dummy-model", "NEMOTRON_MAX_RETRIES": "3"}):
        with pytest.raises(RuntimeError, match="HTTP 401"):
            complete_chat([], api_key="secret-key")

    assert mock_urlopen.call_count == 1
    mock_sleep.assert_not_called()


@patch("harness.shared.nemotron_bridge.time.sleep")
@patch("urllib.request.urlopen")
def test_complete_chat_retries_connection_error_then_exhausts(mock_urlopen, mock_sleep):
    """URLErrors are retried up to the configured budget, then surface sanitized."""
    mock_urlopen.side_effect = urllib.error.URLError("refused by my_secret_key")

    with patch.dict(os.environ, {"NEMOTRON_DEFAULT_MODEL": "dummy-model", "NEMOTRON_MAX_RETRIES": "2"}):
        with pytest.raises(RuntimeError, match="Nemotron Connection Error"):
            complete_chat([], api_key="my_secret_key")

    assert mock_urlopen.call_count == 3
    assert mock_sleep.call_count == 2


@patch("urllib.request.urlopen")
def test_complete_chat_timeout_from_env(mock_urlopen):
    """NEMOTRON_TIMEOUT_MS is honored when the caller omits timeout_sec."""
    mock_urlopen.return_value = _mock_success_response()

    with patch.dict(os.environ, {"NEMOTRON_DEFAULT_MODEL": "dummy-model", "NEMOTRON_TIMEOUT_MS": "5000"}):
        complete_chat([], api_key="secret-key")

    assert mock_urlopen.call_args.kwargs["timeout"] == 5

    # An explicit caller value always wins over the environment.
    with patch.dict(os.environ, {"NEMOTRON_DEFAULT_MODEL": "dummy-model", "NEMOTRON_TIMEOUT_MS": "5000"}):
        complete_chat([], api_key="secret-key", timeout_sec=7)

    assert mock_urlopen.call_args.kwargs["timeout"] == 7


@patch("urllib.request.urlopen")
def test_complete_chat_garbage_env_ints_fall_back(mock_urlopen):
    """Non-integer knob values are ignored with a warning, not raised."""
    mock_urlopen.return_value = _mock_success_response()

    env = {
        "NEMOTRON_DEFAULT_MODEL": "dummy-model",
        "NEMOTRON_TIMEOUT_MS": "not-a-number",
        "NEMOTRON_MAX_RETRIES": "also-bad",
    }
    with patch.dict(os.environ, env):
        res = complete_chat([], api_key="secret-key")

    assert res["choices"][0]["message"]["content"] == "ok"
    assert mock_urlopen.call_args.kwargs["timeout"] == 30
