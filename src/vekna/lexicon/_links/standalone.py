import asyncio
import os
import socket
import sys
import tempfile
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import TextIO

from vekna.lexicon._pacts import (
    RiteBegan,
    RiteEnded,
    RiteEvent,
    RiteStreamed,
    StandalonePromptError,
)

_PROBE_TIMEOUT_SECONDS = 0.5
_MAX_PROMPT_ATTEMPTS = 3


def default_socket_path() -> str:
    return str(Path(tempfile.gettempdir()) / f"vekna-{os.getuid()}.sock")


def _socket_alive(socket_path: str, connect_timeout: float) -> bool:
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as sock:
            sock.settimeout(connect_timeout)
            sock.connect(socket_path)
    except OSError:
        return False
    return True


# `connect_timeout` is the socket's own blocking timeout, not a deadline on this
# coroutine — `asyncio.to_thread` cannot be cancelled, so `asyncio.timeout()`
# around it would return early and leave the thread connecting.
async def probe_daemon(
    *, socket_path: str, connect_timeout: float = _PROBE_TIMEOUT_SECONDS
) -> bool:
    return await asyncio.to_thread(_socket_alive, socket_path, connect_timeout)


@dataclass
class _Rite:
    name: str
    depth: int
    parent_id: str | None
    # Where this rite's lines go: None to print live, otherwise the rite whose
    # buffer collects them until it ends.
    sink: str | None = None
    buffer: list[str] = field(default_factory=list)


# A step may hold two mediums at once, and this sink is a plain stream — no
# cursor, no re-render. Interleaving two rites' output into it would leave no way
# to tell which said what, since indentation is all a line carries. So a rite
# with a live sibling keeps its output until it finishes, and then emits it in
# one block just before its own ✓. A rite running alone streams as it always
# did, which is every rite in a ritual that holds nothing concurrently. A
# surface that *can* re-render — the TUI — wants the opposite and will say so
# itself; that decision belongs to the sink, not here.
class StandaloneRenderer:
    def __init__(self, *, out: TextIO | None = None, inp: TextIO | None = None) -> None:
        self._out: TextIO = out if out is not None else sys.stdout
        self._inp: TextIO = inp if inp is not None else sys.stdin
        self._rites: dict[str, _Rite] = {}
        self._open: set[str] = set()

    def _say(self, line: str) -> None:
        self._out.write(line)
        self._out.flush()

    async def _readline(self) -> str:
        return (await asyncio.to_thread(self._inp.readline)).strip()

    def _emit(self, sink: str | None, block: str) -> None:
        if sink is None:
            self._say(block + "\n")
        else:
            self._rites[sink].buffer.append(block)

    def _depth(self, parent_id: str | None) -> int:
        if parent_id is None:
            return 0
        parent = self._rites.get(parent_id)
        return 1 if parent is None else parent.depth + 1

    def _open_siblings(self, rite_id: str, parent_id: str | None) -> list[str]:
        return [
            other
            for other in self._open
            if other != rite_id and self._rites[other].parent_id == parent_id
        ]

    # A subtree under a buffering rite buffers with it, so the whole thing stays
    # contiguous; a rite that is itself the top of one still announces live, so
    # both gates are visibly under way.
    def _began(self, event: RiteBegan) -> None:
        depth = self._depth(event.parent_id)
        rite = _Rite(name=event.name, depth=depth, parent_id=event.parent_id)
        self._rites[event.rite_id] = rite
        self._open.add(event.rite_id)
        mark = "▶" if event.category == "step" else "↳"
        line = f"{'  ' * depth}{mark} {event.name}"
        parent = self._rites.get(event.parent_id) if event.parent_id else None
        if parent is not None and parent.sink is not None:
            rite.sink = parent.sink
            self._emit(rite.sink, line)
            return
        # Retroactive, because the first sibling had no company when it began.
        for sibling in self._open_siblings(event.rite_id, event.parent_id):
            self._rites[sibling].sink = sibling
            rite.sink = event.rite_id
        self._say(line + "\n")

    def _streamed(self, event: RiteStreamed) -> None:
        rite = self._rites.get(event.rite_id)
        pad = "  " * ((0 if rite is None else rite.depth) + 1)
        lines = event.delta.splitlines() or [""]
        block = "\n".join(f"{pad}{line}" for line in lines)
        self._emit(None if rite is None else rite.sink, block)

    def _ended(self, event: RiteEnded) -> None:
        self._open.discard(event.rite_id)
        mark = "✓" if event.status == "ok" else "✗"
        if (rite := self._rites.get(event.rite_id)) is None:
            self._say(f"{mark} {event.rite_id}\n")
            return
        line = f"{'  ' * rite.depth}{mark} {rite.name}"
        if rite.sink != event.rite_id:
            self._emit(rite.sink, line)
            return
        for block in rite.buffer:
            self._say(block + "\n")
        rite.buffer.clear()
        self._say(line + "\n")

    # RiteEvent is closed, so the three branches are exhaustive — there is no
    # unknown-event fallback to write.
    def render(self, event: RiteEvent) -> None:
        if isinstance(event, RiteBegan):
            self._began(event)
        elif isinstance(event, RiteStreamed):
            self._streamed(event)
        else:
            self._ended(event)

    async def decide(
        self, *, prompt: str, options: Sequence[str] | None = None, free: bool = False
    ) -> str:
        if free:
            return await self._free_text(prompt)
        if options is None:
            return await self._confirm(prompt)
        return await self._choose(prompt, options)

    async def _choose(self, prompt: str, options: Sequence[str]) -> str:
        lines = [prompt, *(f"  {i}) {opt}" for i, opt in enumerate(options, start=1))]
        self._say("\n".join(lines) + "\n")
        for _ in range(_MAX_PROMPT_ATTEMPTS):
            if (answer := await self._readline()) in options:
                return answer
            if answer.isdigit() and 1 <= int(answer) <= len(options):
                return options[int(answer) - 1]
            self._say("invalid choice; try again\n")
        msg = "no valid choice provided"
        raise StandalonePromptError(msg)

    async def _confirm(self, prompt: str) -> str:
        self._say(f"{prompt} [y/n] ")
        for _ in range(_MAX_PROMPT_ATTEMPTS):
            answer = (await self._readline()).lower()
            if answer in {"y", "yes"}:
                return "yes"
            if answer in {"n", "no"}:
                return "no"
            self._say("please answer y or n\n")
        msg = "no yes/no answer provided"
        raise StandalonePromptError(msg)

    async def _free_text(self, prompt: str) -> str:
        self._say(prompt + "\n")
        return await self._readline()
