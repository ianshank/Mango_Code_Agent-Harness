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
    res = complete_chat(messages, api_key="secret-key", timeout_sec=1)

    assert res["choices"][0]["message"]["content"] == "mock response"
    assert "latency_ms" in res
    mock_urlopen.assert_called_once()


@patch("harness.shared.nemotron_bridge.resolve_api_key", return_value="")
@patch("urllib.request.urlopen")
def test_complete_chat_missing_key(mock_urlopen, mock_resolve):
    with pytest.raises(ValueError, match="NVIDIA_API_KEY is not configured"):
        complete_chat([], api_key="")


@patch("urllib.request.urlopen")
def test_complete_chat_http_error(mock_urlopen):
    err = urllib.error.HTTPError("url", 401, "Unauthorized", {}, io.BytesIO(b"Bad Key my_secret_key"))
    mock_urlopen.side_effect = err

    with pytest.raises(RuntimeError) as exc:
        complete_chat([], api_key="my_secret_key")

    # Assert secret is masked
    assert "my_secret_key" not in str(exc.value)
    assert mask_secret("my_secret_key") in str(exc.value)


@patch("urllib.request.urlopen")
def test_complete_chat_connection_error(mock_urlopen):
    mock_urlopen.side_effect = Exception("Connection failed due to token my_secret_key")

    with pytest.raises(RuntimeError) as exc:
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
@patch("sys.stderr", new_callable=io.StringIO)
def test_main_error_exit(mock_stderr, mock_complete):
    mock_complete.side_effect = Exception("mock error")
    with pytest.raises(SystemExit) as exc:
        main()
    assert exc.value.code == 1
    assert "mock error" in mock_stderr.getvalue()
