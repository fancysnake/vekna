import asyncio
import contextlib

from vekna.lexicon._links.standalone import default_socket_path, probe_daemon


# The probe connects from a worker thread and drops the socket, so the close
# handshake can fail. Awaiting it anyway keeps the accepted transport from
# outliving the loop and being finalised against a closed server.
async def _accept(_reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
    writer.close()
    with contextlib.suppress(ConnectionError):
        await writer.wait_closed()


class TestProbe:
    @staticmethod
    def test_absent_socket_is_false_and_does_not_hang(tmp_path):
        missing = str(tmp_path / "nobody-here.sock")

        result = asyncio.run(probe_daemon(socket_path=missing, connect_timeout=0.2))

        assert result is False

    @staticmethod
    def test_reachable_socket_is_true(tmp_path):
        socket_path = str(tmp_path / "daemon.sock")

        async def run() -> bool:
            server = await asyncio.start_unix_server(_accept, path=socket_path)
            try:
                return await probe_daemon(socket_path=socket_path, connect_timeout=0.5)
            finally:
                server.close()
                await server.wait_closed()

        assert asyncio.run(run()) is True


class TestDefaultSocketPath:
    @staticmethod
    def test_is_user_scoped_under_tempdir(monkeypatch):
        monkeypatch.delenv("VEKNA_SOCKET", raising=False)

        path = default_socket_path()

        assert path.endswith(".sock")
        assert "vekna-" in path

    # The daemon reads the same variable, and a cast that ignored it would
    # attach to the wrong socket or to none.
    @staticmethod
    def test_the_environment_names_it(monkeypatch):
        monkeypatch.setenv("VEKNA_SOCKET", "/tmp/mine.sock")

        assert default_socket_path() == "/tmp/mine.sock"
