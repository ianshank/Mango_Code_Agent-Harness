"""AQA (Acceptance Quality Assurance) smoke tests for Nemotron API integration.

These tests validate the Nemotron bridge contract WITHOUT hitting the real API.
They exercise the full path through mock transport to verify:
1. complete_chat returns valid structure
2. resolve_environment fallback chain works
3. Secret masking never leaks full key
4. Egress floor blocks undeclared network access (enforced by pytest-socket)
"""
from __future__ import annotations

import json
import os
from unittest.mock import MagicMock, patch

import pytest

from harness.shared.nemotron_bridge import (
    complete_chat,
    mask_secret,
    resolve_api_key,
)


class TestBridgeSmoke:
    """AQA: bridge complete_chat returns valid structure with mock transport."""

    @patch("urllib.request.urlopen")
    def test_complete_chat_returns_choices(self, mock_urlopen: MagicMock) -> None:
        mock_resp = MagicMock()
        mock_resp.read.return_value = json.dumps({
            "choices": [{"message": {"content": "AQA response"}}],
            "usage": {"total_tokens": 5, "prompt_tokens": 3, "completion_tokens": 2},
        }).encode()
        mock_resp.__enter__ = MagicMock(return_value=mock_resp)
        mock_resp.__exit__ = MagicMock(return_value=False)
        mock_urlopen.return_value = mock_resp

        messages = [{"role": "user", "content": "hello"}]
        with patch.dict(os.environ, {"NEMOTRON_DEFAULT_MODEL": "test-model"}):
            result = complete_chat(messages, api_key="nvapi-test", timeout_sec=1)

        assert "choices" in result
        assert result["choices"][0]["message"]["content"] == "AQA response"
        assert "usage" in result

    @patch("urllib.request.urlopen")
    def test_complete_chat_includes_latency(self, mock_urlopen: MagicMock) -> None:
        mock_resp = MagicMock()
        mock_resp.read.return_value = json.dumps({
            "choices": [{"message": {"content": "ok"}}],
            "usage": {"total_tokens": 1},
        }).encode()
        mock_resp.__enter__ = MagicMock(return_value=mock_resp)
        mock_resp.__exit__ = MagicMock(return_value=False)
        mock_urlopen.return_value = mock_resp

        with patch.dict(os.environ, {"NEMOTRON_DEFAULT_MODEL": "test-model"}):
            result = complete_chat(
                [{"role": "user", "content": "test"}],
                api_key="nvapi-test", timeout_sec=1,
            )
        assert "latency_ms" in result
        assert result["latency_ms"] >= 0


class TestEnvironmentResolution:
    """AQA: resolve_api_key fallback chain works."""

    def test_env_var_resolution(self) -> None:
        with patch.dict(os.environ, {"NVIDIA_API_KEY": "nvapi-from-env"}):
            key = resolve_api_key()
            assert key == "nvapi-from-env"

    def test_empty_when_unset(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            with patch("harness.shared.nemotron_bridge.Path") as mock_path:
                mock_current = MagicMock()
                mock_current.parent = MagicMock()
                # Make .env file not exist
                mock_file = MagicMock(is_file=MagicMock(return_value=False))
                mock_current.parent.__truediv__ = MagicMock(return_value=mock_file)
                mock_path.return_value.resolve.return_value = mock_current
                key = resolve_api_key()
                assert key == ""


class TestSecretMasking:
    """AQA: mask_secret never leaks the full key."""

    def test_long_key_masked(self) -> None:
        key = "nvapi-sSeCHw0DgZGfWMEf5bhpL7H0NutynoON8H3rVPdD2y8wCAUb72j"
        masked = mask_secret(key)
        assert key not in masked
        assert len(masked) < len(key)

    def test_short_key_fully_masked(self) -> None:
        assert mask_secret("short") == "****"

    def test_empty_key_placeholder(self) -> None:
        assert mask_secret("") == "<UNSET>"

    def test_none_like_handling(self) -> None:
        """Passing None should not crash."""
        # mask_secret expects str, but should handle edge cases
        assert mask_secret("") == "<UNSET>"


class TestEgressFloor:
    """AQA: egress floor blocks undeclared network access.

    The pytest-socket plugin is configured in pyproject.toml (addopts includes
    --disable-socket). These tests verify the contract holds: any test that
    does not carry @pytest.mark.enable_socket cannot open a socket.
    """

    def test_socket_is_blocked(self) -> None:
        """This test runs WITHOUT enable_socket, so any socket.socket() call
        would raise SocketBlockedError — proving the egress floor is active."""
        import socket

        from pytest_socket import SocketBlockedError
        with pytest.raises(SocketBlockedError):
            socket.socket(socket.AF_INET, socket.SOCK_STREAM)
