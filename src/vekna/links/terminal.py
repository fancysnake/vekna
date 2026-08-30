import asyncio
import sys
from typing import TextIO

from vekna.pacts.screen import Screen


# The daemon's own terminal: painted over on every change, and read a line at a
# time. No raw mode, no cursor arithmetic — a keystroke needs Enter behind it,
# which is the price of a surface that is one `print` and one `input`.
# ponytail: a blocking read on a worker thread. It cannot be cancelled, so the
# daemon stops when the reader says stop rather than the other way round; a
# `loop.add_reader` on the tty is the upgrade, and it is what a takeover would
# need anyway. Takeover — answering a prompt from `vekna` itself — is deferred.
class Terminal(Screen):
    def __init__(self, *, out: TextIO | None = None, inp: TextIO | None = None) -> None:
        self._out: TextIO = out if out is not None else sys.stdout
        self._inp: TextIO = inp if inp is not None else sys.stdin

    def show(self, screen: str) -> None:
        self._out.write(screen)
        self._out.flush()

    # None at end of input — a daemon whose stdin is closed renders and never
    # asks, rather than spinning on an empty read.
    async def read_line(self) -> str | None:
        if not (line := await asyncio.to_thread(self._inp.readline)):
            return None
        return line.strip()
