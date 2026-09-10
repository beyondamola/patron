import socket
import subprocess

import pytest


@pytest.fixture(autouse=True)
def unit_io_boundary(request, monkeypatch):
    if request.node.get_closest_marker("integration"):
        return

    def forbidden(*args, **kwargs):
        raise AssertionError("Unit tests must mock subprocess/network operations")

    monkeypatch.setattr(subprocess, "Popen", forbidden)
    monkeypatch.setattr(socket, "create_connection", forbidden)
    monkeypatch.setattr(socket.socket, "connect", forbidden)
