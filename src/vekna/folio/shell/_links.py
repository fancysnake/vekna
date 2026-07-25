import asyncio
from collections.abc import Callable

# Lines longer than this raise rather than growing the buffer without bound.
_LINE_LIMIT = 1 << 20


async def _pump(
    stream: asyncio.StreamReader | None,
    sink: list[str],
    on_line: Callable[[str], None] | None,
) -> None:
    if stream is None:
        return  # pragma: no cover
    async for raw in stream:
        line = raw.decode()
        sink.append(line)
        if on_line is not None:
            on_line(line.rstrip("\n"))


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
        limit=_LINE_LIMIT,
    )
    out: list[str] = []
    err: list[str] = []
    # Both pipes are drained concurrently, so `on_line` sees them in arrival
    # order and neither can fill and block the other.
    await asyncio.gather(
        _pump(process.stdout, out, on_line), _pump(process.stderr, err, on_line)
    )
    return "".join(out), "".join(err), await process.wait()
