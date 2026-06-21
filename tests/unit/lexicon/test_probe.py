import asyncio

from vekna.lexicon import default_socket_path, probe_daemon


async def _accept(_reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
    await asyncio.sleep(0)
    writer.close()


class TestProbe:
    @staticmethod
    def test_absent_socket_is_false_and_does_not_hang(tmp_path):
        missing = str(tmp_path / "nobody-here.sock")

        result = asyncio.run(probe_daemon(socket_path=missing, timeout=0.2))

        assert result is False

    @staticmethod
    def test_reachable_socket_is_true(tmp_path):
        socket_path = str(tmp_path / "daemon.sock")

        async def run() -> bool:
            server = await asyncio.start_unix_server(_accept, path=socket_path)
            try:
                return await probe_daemon(socket_path=socket_path, timeout=0.5)
            finally:
                server.close()
                await server.wait_closed()

        assert asyncio.run(run()) is True


class TestDefaultSocketPath:
    @staticmethod
    def test_is_user_scoped_under_tempdir():
        path = default_socket_path()

        assert path.endswith(".sock")
        assert "vekna-" in path
