import asyncio
import os
import socket
import sys
import tempfile
from collections.abc import Sequence
from pathlib import Path
from typing import TextIO

from vekna.wire import RiteFinished, RiteStarted, WireMessage

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


def _render(event: WireMessage) -> str:
    if isinstance(event, RiteStarted):
        return f"▶ {event.name}"
    if isinstance(event, RiteFinished):
        return f"{'✓' if event.status == 'ok' else '✗'} {event.rite_id}"
    return f"· {event.kind}"


class StandaloneRenderer:
    def __init__(self, *, out: TextIO = sys.stdout, inp: TextIO = sys.stdin) -> None:
        self._out = out
        self._inp = inp

    def _say(self, line: str) -> None:
        self._out.write(line)
        self._out.flush()

    async def _readline(self) -> str:
        return (await asyncio.to_thread(self._inp.readline)).strip()

    async def emit(self, event: WireMessage) -> None:
        self._say(_render(event) + "\n")

    async def decide(self, *, prompt: str, options: Sequence[str]) -> str:
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

    async def approve(self, *, prompt: str) -> bool:
        self._say(f"{prompt} [y/n] ")
        for _ in range(_MAX_PROMPT_ATTEMPTS):
            answer = (await self._readline()).lower()
            if answer in {"y", "yes"}:
                return True
            if answer in {"n", "no"}:
                return False
            self._say("please answer y or n\n")
        msg = "no yes/no answer provided"
        raise StandalonePromptError(msg)

    async def ask(self, *, prompt: str, choices: Sequence[str] | None = None) -> str:
        self._say(prompt + "\n")
        for _ in range(_MAX_PROMPT_ATTEMPTS):
            answer = await self._readline()
            if choices is None or answer in choices:
                return answer
            self._say("invalid choice; try again\n")
        msg = "no valid answer provided"
        raise StandalonePromptError(msg)
