import asyncio
import codecs
from collections.abc import Callable

from pydantic import JsonValue, TypeAdapter, ValidationError
from typing_extensions import override

from vekna.lexicon import (
    SHELL_FOCUS,
    ShellCall,
    ShellFocusProtocol,
    ShellReply,
    emit_delta,
    medium,
    record_result,
    replayed,
)

from ._pacts import ShellOutputError, ShellResult

_CHUNK = 1 << 16
# Read through the model and written through it too, so a field added to
# `ShellResult` cannot land on one side of the round trip only. `model_dump()`
# hands back `dict[str, Any]`; this is what says the journal holds JSON.
_JOURNALLED: TypeAdapter[dict[str, JsonValue]] = TypeAdapter(dict[str, JsonValue])


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


# Closed stdin, not the cast's: a command inheriting the terminal reads the line
# the operator typed at a `decide` prompt running beside it, and the answer is
# gone. One that wants input hangs on a terminal nobody is watching anyway, so
# it gets EOF instead.
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
        stdin=asyncio.subprocess.DEVNULL,
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


# The Focus bash answers through, and the default every unregistered `shell()`
# resolves to. It exists so there is a supported way to stand somewhere else —
# monkeypatching `run_bash` was the only way in before — and it costs the folio
# one indirection.
class BashFocus(ShellFocusProtocol):
    @override
    async def run(
        self, call: ShellCall, *, on_line: Callable[[str], None] | None
    ) -> ShellReply:
        stdout, stderr, exit_code = await run_bash(
            call.command, cwd=call.cwd, on_line=on_line
        )
        return ShellReply(stdout=stdout, stderr=stderr, exit_code=exit_code)


# One instance, the way a registered Focus is one: it lives as long as its
# install, so a Focus that grew state would keep it. `resolve`'s `default=` is
# eager besides — building one per call pays for it even when a focus is
# installed and the default is thrown away.
_BASH = BashFocus()


# Lives beside run_bash rather than in a _mills of its own: no branches, and
# nothing here is business logic — it is the I/O call plus the shape it returns.
# A mills/inits pair injecting a run_bash that will never have a second
# implementation would be ceremony around a wrapper.
# `default=_BASH`, so a cast that loaded no folios still runs bash: the
# medium is importable on its own and answers on its own.
@medium
async def shell(
    command: str, *, cwd: str | None = None, stream: bool = True
) -> ShellResult:
    # A command this cast already ran comes back off the journal rather than
    # being run a second time — a resumed cast should not rebuild, re-push or
    # re-delete anything it had already finished doing.
    if (prior := replayed()) is not None:
        result = _recorded(prior)
    else:
        focus = SHELL_FOCUS.resolve(default=_BASH)
        reply = await focus.run(
            ShellCall(command=command, cwd=cwd), on_line=emit_delta if stream else None
        )
        result = ShellResult(
            stdout=reply.stdout, stderr=reply.stderr, exit_code=reply.exit_code
        )
    record_result(_JOURNALLED.validate_json(result.model_dump_json()))
    return result


def _recorded(prior: JsonValue) -> ShellResult:
    try:
        return ShellResult.model_validate(prior)
    except ValidationError as error:
        msg = f"a shell rite was journaled as something else: {error}"
        raise ShellOutputError(msg) from error
