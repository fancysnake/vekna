import asyncio
import os
import socket
import sys
import tempfile
from collections.abc import Sequence
from pathlib import Path
from typing import TextIO

from vekna.wire import RiteDelta, RiteFinished, RiteStarted, WireMessage

from ._pacts import StandalonePromptError

_PROBE_TIMEOUT_SECONDS = 0.5
_MAX_PROMPT_ATTEMPTS = 3


def default_socket_path() -> str:
    return str(Path(tempfile.gettempdir()) / f"vekna-{os.getuid()}.sock")


def _socket_alive(socket_path: str, timeout: float) -> bool:
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as sock:
            sock.settimeout(timeout)
            sock.connect(socket_path)
    except OSError:
        return False
    return True


async def probe_daemon(
    *, socket_path: str, timeout: float = _PROBE_TIMEOUT_SECONDS
) -> bool:
    return await asyncio.to_thread(_socket_alive, socket_path, timeout)


class StandaloneRenderer:
    def __init__(self, *, out: TextIO | None = None, inp: TextIO | None = None) -> None:
        self._out: TextIO = out if out is not None else sys.stdout
        self._inp: TextIO = inp if inp is not None else sys.stdin
        self._rites: dict[str, tuple[str, int]] = {}

    def _say(self, line: str) -> None:
        self._out.write(line)
        self._out.flush()

    async def _readline(self) -> str:
        return (await asyncio.to_thread(self._inp.readline)).strip()

    def _format(self, event: WireMessage) -> str:
        if isinstance(event, RiteStarted):
            depth = (
                0
                if event.parent_id is None
                else self._rites.get(event.parent_id, ("", 0))[1] + 1
            )
            self._rites[event.rite_id] = (event.name, depth)
            mark = "▶" if event.category == "step" else "↳"
            return f"{'  ' * depth}{mark} {event.name}"
        if isinstance(event, RiteDelta):
            _, depth = self._rites.get(event.rite_id, ("", 0))
            pad = "  " * (depth + 1)
            lines = event.delta.splitlines() or [""]
            return "\n".join(f"{pad}{line}" for line in lines)
        if isinstance(event, RiteFinished):
            name, depth = self._rites.get(event.rite_id, (event.rite_id, 0))
            mark = "✓" if event.status == "ok" else "✗"
            return f"{'  ' * depth}{mark} {name}"
        return f"· {event.kind}"

    def render(self, event: WireMessage) -> None:
        self._say(self._format(event) + "\n")

    async def emit(self, event: WireMessage) -> None:
        self.render(event)

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
