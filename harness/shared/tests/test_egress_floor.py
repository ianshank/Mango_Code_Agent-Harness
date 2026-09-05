"""The Python half of the egress floor, proven rather than configured (EGF).

Requirement citations:
- R-EGF-1: absence of egress is proven by an assertion that FAILS when a
  connection is attempted -- not by dependency absence or lazy imports.
- R-EGF-2: the guard is shown capable of failing, using a LOOPBACK listener so
  the negative control needs no outbound reachability and stays runnable in the
  very CI job whose egress is blocked (DEC-EGF-001).
- R-EGF-3: this covers the Python runtime only. The Node reasoning path is
  guarded independently in ``tests/ai/unit/nemotron-egress-floor.test.ts``; a
  socket guard in this process cannot observe a ``fetch`` in that one.
- R-EGF-6: exemptions are declared per test, never globally.
"""

from __future__ import annotations

import socket

import pytest

pytest_socket = pytest.importorskip(
    "pytest_socket",
    reason="pytest-socket is declared in requirements-dev.txt; the floor is inert without it",
)


def test_the_socket_guard_is_actually_active() -> None:
    """R-EGF-1: sockets are off by default, so a connection raises.

    If this ever passes by *connecting*, the floor has been silently disabled --
    which is precisely the failure mode ``--disable-socket`` exists to prevent.
    """
    with pytest.raises(pytest_socket.SocketBlockedError):
        socket.socket(socket.AF_INET, socket.SOCK_STREAM)


def test_the_guard_blocks_a_loopback_connection(unused_tcp_port: int = 9) -> None:
    """R-EGF-2: the mutation check -- a deliberate connect is refused.

    Loopback on a closed port: no outbound reachability required, so this is
    valid under a deny-all egress policy. Without the guard this would raise
    ConnectionRefusedError; with it, SocketBlockedError arrives first.
    """
    with pytest.raises(pytest_socket.SocketBlockedError):
        socket.create_connection(("127.0.0.1", unused_tcp_port), timeout=0.01)


@pytest.mark.skipif(
    not hasattr(socket, "AF_UNIX"),
    reason="AF_UNIX not available on this Windows Python build; the proof runs on Linux CI [DEC-057]",
)
def test_a_unix_socketpair_is_permitted_while_tcp_still_raises() -> None:
    """`--allow-unix-socket` is not a hole in the floor; this is the proof.

    AF_UNIX cannot leave the host, and it is what asyncio's self-pipe and
    anyio's BlockingPortal (under FastAPI's TestClient) are made of. Before the
    allowance, 35 tests carried `enable_socket` for that need and the marks
    re-opened TCP as well (audit M12). Both halves are asserted in one test so
    neither can be satisfied by the other: the socketpair is created, and in the
    same guard state a TCP socket is still refused.

    Skip on Windows Python builds where AF_UNIX is absent (DEC-057): the
    egress floor's proof is meaningful on Linux CI where AF_UNIX is always
    present. A skip here does NOT weaken the floor -- the socket guard still
    blocks TCP (test_the_socket_guard_is_actually_active) on every platform.
    """
    _AF_UNIX = socket.AF_UNIX  # type: ignore[attr-defined]  # guarded by skipif above
    left, right = socket.socketpair(_AF_UNIX, socket.SOCK_STREAM)
    try:
        assert left.fileno() >= 0 and right.fileno() >= 0
        left.sendall(b"ping")
        assert right.recv(4) == b"ping"
    finally:
        left.close()
        right.close()
    with pytest.raises(pytest_socket.SocketBlockedError):
        socket.socket(socket.AF_INET, socket.SOCK_STREAM)


# A real TCP need (R-EGF-6): this test exists to open an AF_INET socket, which
# the unix-socket allowance does not cover, so the exemption has to be declared.
@pytest.mark.enable_socket
def test_the_guard_can_be_declared_off_per_test() -> None:
    """R-EGF-6: an exemption is visible at the test that needs it.

    This is also the counter-proof for the two tests above: with the marker the
    socket object is created, so their failures come from the guard rather than
    from sockets being broken in the environment.
    """
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        assert sock.fileno() >= 0
    finally:
        sock.close()


def test_no_global_socket_exemption_exists() -> None:
    """AC-EGF-7: the floor must not be quietly re-opened in configuration."""
    from pathlib import Path

    try:  # tomllib entered the stdlib in 3.11; tomli is its backport (see requirements-dev.txt)
        import tomllib
    except ModuleNotFoundError:  # pragma: no cover - exercised on the 3.9/3.10 matrix legs
        import tomli as tomllib  # type: ignore[no-redef]

    root = Path(__file__).resolve().parents[3]
    cfg = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))
    addopts = cfg["tool"]["pytest"]["ini_options"]["addopts"]
    assert "--disable-socket" in addopts, "the egress floor was removed from addopts"
    assert "--allow-hosts" not in addopts, "a global host allow-list re-opens the floor"
    assert "--enable-socket" not in addopts, "a global enable re-opens the floor"
    # The one global allowance, and it is not egress: AF_UNIX stays on the host.
    # Pinned so a drop of it does not silently bring the 35 per-test marks back.
    assert "--allow-unix-socket" in addopts, (
        "the unix-socket allowance left addopts; asyncio's self-pipe and TestClient's "
        "portal would need per-test enable_socket marks again, which re-open TCP too"
    )


# --- the Python reasoning path (R-EGF-3) -----------------------------------
#
# The code-generation path runs through nemotron_bridge, NOT the TypeScript
# client. Guarding only the TS side would have left the actual product path
# open, which is the gap these tests close.


def test_the_python_bridge_refuses_when_no_mode_is_declared(monkeypatch: pytest.MonkeyPatch) -> None:
    """R-EGF-5: an unset mode must not resolve to the vendor endpoint."""
    from harness.shared import nemotron_bridge as nb

    monkeypatch.delenv("NEMOTRON_MODE", raising=False)
    with pytest.raises(nb.NemotronEgressRefused, match="no transport mode declared"):
        nb._assert_egress_permitted("https://integrate.api.nvidia.com/v1/chat/completions")


def test_the_python_bridge_refuses_under_offline_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    from harness.shared import nemotron_bridge as nb

    monkeypatch.setenv("NEMOTRON_MODE", "offline")
    with pytest.raises(nb.NemotronEgressRefused, match="offline"):
        nb._assert_egress_permitted("https://example.invalid/v1")


def test_the_python_bridge_permits_declared_online(monkeypatch: pytest.MonkeyPatch) -> None:
    """The guard is conditional, not vacuous -- online reaches the transport."""
    from harness.shared import nemotron_bridge as nb

    monkeypatch.setenv("NEMOTRON_MODE", "online")
    assert nb.resolve_nemotron_mode() == "online"
    # The guard returns None by contract, so there is no return value to assert
    # on (mypy: func-returns-value). What is being verified is that it does not
    # raise -- any refusal here fails the test, which is the whole point.
    nb._assert_egress_permitted("https://example.invalid/v1")


def test_an_injected_transport_is_a_declaration(monkeypatch: pytest.MonkeyPatch) -> None:
    """A monkeypatched urlopen is a declared transport and passes through.

    This is what keeps the offline suite working: its doubles are honoured
    without anyone needing to set a mode.
    """
    import urllib.request

    from harness.shared import nemotron_bridge as nb

    monkeypatch.delenv("NEMOTRON_MODE", raising=False)
    monkeypatch.setattr(urllib.request, "urlopen", lambda *a, **k: None)
    assert nb.resolve_nemotron_mode() is None, "no mode declared, yet the double must pass"
    # Must not raise: the injected double is honoured despite no declared mode.
    nb._assert_egress_permitted("https://integrate.api.nvidia.com/v1")


def test_a_typo_in_the_mode_is_not_a_declaration(monkeypatch: pytest.MonkeyPatch) -> None:
    """R-EGF-5: only the exact literals count; anything else fails closed."""
    from harness.shared import nemotron_bridge as nb

    monkeypatch.setenv("NEMOTRON_MODE", "ONLINE")
    assert nb.resolve_nemotron_mode() is None
    with pytest.raises(nb.NemotronEgressRefused):
        nb._assert_egress_permitted("https://integrate.api.nvidia.com/v1")
