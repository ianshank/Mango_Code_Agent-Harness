"""Fixtures for the API server suite.

The server reads its credential from the environment. Tests must never depend
on an ambient ``API_SERVER_KEY`` (which would make them pass locally and fail
in CI, or worse, exercise a real key), so every test gets a generated one.
"""

from __future__ import annotations

import secrets
from collections.abc import Iterator

import pytest

pytest.importorskip("fastapi")


@pytest.fixture
def api_server_key(monkeypatch: pytest.MonkeyPatch) -> str:
    """A throwaway API_SERVER_KEY, generated rather than committed."""
    key = secrets.token_urlsafe(32)
    monkeypatch.setenv("API_SERVER_KEY", key)
    return key


@pytest.fixture
def no_server_key(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """The unconfigured-server path, which must fail closed with a 500."""
    monkeypatch.delenv("API_SERVER_KEY", raising=False)
    yield
