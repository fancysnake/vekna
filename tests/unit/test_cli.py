import socket as _socket
import threading
import time

import pytest

from vekna.inits.cli import ensure_daemon_running


class TestEnsureDaemonRunning:
    @staticmethod
    def test_does_not_spawn_if_already_running(tmp_path, monkeypatch) -> None:
        socket_path = str(tmp_path / "vekna.sock")
        monkeypatch.setattr("vekna.inits.cli.daemon_socket_path", lambda: socket_path)

        server = _socket.socket(_socket.AF_UNIX, _socket.SOCK_STREAM)
        server.bind(socket_path)
        server.listen(1)

        spawned: list[bool] = []

        try:
            ensure_daemon_running(spawn=lambda: spawned.append(True))
        finally:
            server.close()

        assert not spawned

    @staticmethod
    def test_spawns_and_waits_until_socket_alive(tmp_path, monkeypatch) -> None:
        socket_path = str(tmp_path / "vekna.sock")
        monkeypatch.setattr("vekna.inits.cli.daemon_socket_path", lambda: socket_path)

        server = _socket.socket(_socket.AF_UNIX, _socket.SOCK_STREAM)

        def delayed_bind() -> None:
            time.sleep(0.05)
            server.bind(socket_path)
            server.listen(1)

        thread = threading.Thread(target=delayed_bind, daemon=True)
        thread.start()

        try:
            ensure_daemon_running(spawn=lambda: None)
        finally:
            server.close()
            thread.join()

    @staticmethod
    def test_raises_if_daemon_never_starts(monkeypatch) -> None:
        monkeypatch.setattr("vekna.inits.cli._DAEMON_START_TIMEOUT_SECONDS", 0.05)
        monkeypatch.setattr("vekna.inits.cli._DAEMON_POLL_INTERVAL_SECONDS", 0.01)
        monkeypatch.setattr(
            "vekna.inits.cli.daemon_socket_path", lambda: "/nonexistent/vekna.sock"
        )

        with pytest.raises(RuntimeError, match="daemon did not start"):
            ensure_daemon_running(spawn=lambda: None)
