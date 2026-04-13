import asyncio


class SocketClientLink:
    def __init__(self, socket_path: str) -> None:
        self._socket_path = socket_path

    async def send(self, message: str) -> str:
        reader, writer = await asyncio.open_unix_connection(self._socket_path)
        writer.write(f"{message}\n".encode())
        await writer.drain()
        response = await reader.readline()
        writer.close()
        await writer.wait_closed()
        return response.decode().strip()
