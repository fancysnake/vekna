import asyncio
import codecs
from collections.abc import Callable

_CHUNK = 1 << 16


# A StreamReader iterates itself by *lines*, which is the very thing that
# breaks here: readline raises once a line passes its limit, and clears its
# buffer doing so — losing the output as well as crashing the cast. A
# single-line blob (minified bundle, base64, one-line JSON) is ordinary for a
# coding agent. read() has no such limit, so iterating chunks removes the
# failure mode rather than merely reporting it. The line cap was guarding
# nothing either way: `sink` keeps the whole output wherever the newlines fall.
class _Chunks:
    def __init__(self, stream: asyncio.StreamReader) -> None:
        self._stream = stream

    def __aiter__(self) -> "_Chunks":
        return self

    async def __anext__(self) -> bytes:
        if chunk := await self._stream.read(_CHUNK):
            return chunk
        raise StopAsyncIteration


async def _pump(
    *,
    stream: asyncio.StreamReader | None,
    sink: list[str],
    on_line: Callable[[str], None] | None,
) -> None:
    if stream is None:
        return  # pragma: no cover
    # Incremental, because a chunk boundary splits multi-byte UTF-8 — something
    # decoding whole lines never had to survive.
    decoder = codecs.getincrementaldecoder("utf-8")(errors="replace")
    pending = ""
    async for chunk in _Chunks(stream):
        *lines, pending = (pending + decoder.decode(chunk)).split("\n")
        for line in lines:
            sink.append(line + "\n")
            if on_line is not None:
                on_line(line)
    if pending:
        sink.append(pending)
        if on_line is not None:
            on_line(pending)


async def run_bash(
    command: str,
    *,
    cwd: str | None = None,
    on_line: Callable[[str], None] | None = None,
) -> tuple[str, str, int]:
    process = await asyncio.create_subprocess_exec(
        "bash",
        "-c",
        command,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        cwd=cwd,
    )
    out: list[str] = []
    err: list[str] = []
    # Both pipes are drained concurrently, so `on_line` sees them in arrival
    # order and neither can fill and block the other.
    await asyncio.gather(
        _pump(stream=process.stdout, sink=out, on_line=on_line),
        _pump(stream=process.stderr, sink=err, on_line=on_line),
    )
    return "".join(out), "".join(err), await process.wait()
