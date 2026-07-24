"""Test-suite safety fixtures."""

import socket

import pytest


@pytest.fixture(autouse=True)
def prevent_network_requests(monkeypatch: pytest.MonkeyPatch) -> None:
    """Fail every test that attempts to open a network connection."""

    def blocked_connection(*args: object, **kwargs: object) -> None:
        del args, kwargs
        raise RuntimeError("Network access is disabled during tests")

    monkeypatch.setattr(socket, "create_connection", blocked_connection)
    monkeypatch.setattr(socket.socket, "connect", blocked_connection)
