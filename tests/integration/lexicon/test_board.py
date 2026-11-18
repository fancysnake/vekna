import asyncio
import io
import os
import pty
import shutil
import termios
from collections.abc import Callable, Iterator
from datetime import UTC, datetime
from functools import partial
from pathlib import Path
from typing import TextIO

import pytest
from typing_extensions import override

from vekna.lexicon._links.board import Board
from vekna.lexicon._links.follow import Follower
from vekna.lexicon._links.standalone import StandaloneRenderer, Tail
from vekna.lexicon._mills.follow import Lineage
from vekna.lexicon._pacts import (
    RiteBegan,
    RiteEnded,
    RiteStreamed,
    StandalonePromptError,
)
from vekna.links.socket_server import serve
from vekna.mills.hub import Hub
from vekna.pacts.routing import Surface
from vekna.wire import (
    CastGoodbye,
    CastHello,
    DecideRequested,
    DecideResolved,
    RiteDelta,
    RiteStarted,
    WireMessage,
)

_WHEN = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
_PATIENCE = 300
_TICK = 0.01
_ALTERNATE = "\x1b[?1049h"
_PLAIN = "\x1b[?1049l"
_HOME = "\x1b[H\x1b[2J"
# Longer than the board waits before it repaints after a change.
_REPAINTED = 0.3
_TWICE = 2
_END_OF_INPUT = "\x04"
_ROWS = 24
_ATTEMPTS = 3
_LOG_LINES = 40


class _Terminal(io.StringIO):
    @override
    def isatty(self) -> bool:
        return True

    @property
    def frame(self) -> str:
        return self.getvalue().rpartition(_HOME)[2]


class _Typist:
    def __init__(self, keys: TextIO) -> None:
        self._keys = keys

    def enter(self, line: str) -> None:
        self.type(f"{line}\n")

    def type(self, text: str) -> None:
        self._keys.write(text)
        self._keys.flush()


class _Broken(io.StringIO):
    @override
    def isatty(self) -> bool:
        return True

    @override
    def readline(self, size: int | None = -1, /) -> str:
        msg = "keys gone"
        raise OSError(msg)


class _Peer(Surface):
    def __init__(self) -> None:
        self.sent: list[WireMessage] = []

    def send(self, message: WireMessage) -> None:
        self.sent.append(message)


async def _eventually(ready: Callable[[], bool]) -> None:
    for _ in range(_PATIENCE):
        if ready():
            return
        await asyncio.sleep(_TICK)
    msg = f"gave up after {_PATIENCE * _TICK:.1f}s"
    raise AssertionError(msg)


def _said(terminal: _Terminal, text: str, times: int) -> bool:
    return terminal.getvalue().count(text) == times


def _hello(cast_id: str) -> CastHello:
    return CastHello(
        cast_id=cast_id,
        project_root="/proj",
        project="/proj/.git",
        ritual="heal",
        components={},
        started_at=_WHEN,
        wired=True,
        enqueued_by="root",
    )


def _began(rite_id: str = "r1") -> RiteBegan:
    return RiteBegan(
        rite_id=rite_id,
        parent_id=None,
        name="repair",
        category="step",
        started_at=_WHEN,
    )


# `shutil.get_terminal_size` reads these first, so the frame does not depend on
# the terminal the suite runs in.
@pytest.fixture(autouse=True)
def _terminal_size(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("COLUMNS", "80")
    monkeypatch.setenv("LINES", str(_ROWS))


def _board(inp: TextIO) -> tuple[Board, _Terminal]:
    terminal = _Terminal()
    screen = Tail(terminal)
    return _board_on(screen=screen, inp=inp), terminal


def _board_on(*, screen: Tail, inp: TextIO) -> Board:
    return Board(
        screen=screen,
        asker=StandaloneRenderer(out=screen, inp=inp),
        cast_id="root",
        label="sweep root",
        started_at=_WHEN,
    )


# Keys come from a terminal, as they do when somebody is typing.
@pytest.fixture(name="desk")
def _desk() -> Iterator[tuple[Board, _Terminal, _Typist]]:
    master_fd, slave_fd = pty.openpty()
    with os.fdopen(slave_fd) as inp, os.fdopen(master_fd, "w") as keys:
        board, terminal = _board(inp)
        yield board, terminal, _Typist(keys)
        # The read a board leaves behind ends with its input.
        keys.close()


# Answers come down a pipe, as a script or another program gives them.
@pytest.fixture(name="piped")
def _piped() -> Iterator[tuple[Board, _Terminal, _Typist]]:
    read_fd, write_fd = os.pipe()
    with os.fdopen(read_fd) as inp, os.fdopen(write_fd, "w") as keys:
        board, terminal = _board(inp)
        yield board, terminal, _Typist(keys)
        keys.close()


@pytest.mark.asyncio
class TestBoard:
    @staticmethod
    async def test_while_a_question_is_open_no_other_cast_changes_the_screen(
        desk: tuple[Board, _Terminal, _Typist], tmp_path: Path
    ):
        board, terminal, typist = desk
        hub = Hub()
        server = await serve(path=tmp_path / "vekna.sock", routes=hub)
        follower = Follower(
            socket_path=tmp_path / "vekna.sock",
            lineage=Lineage("root"),
            display=board,
            ask=board.asker,
        )
        await follower.attach()
        peer = _Peer()
        hub.open_cast("bbbb0000", peer)
        for cast_id in ("aaaa0000", "bbbb0000", "cccc0000"):
            hub.apply(_hello(cast_id))
        await _eventually(lambda: "heal cccc0000" in terminal.frame)

        hub.apply(DecideRequested(cast_id="bbbb0000", request_id="q1", prompt="push?"))
        await _eventually(lambda: "push? [y/n]" in terminal.frame)
        asked = terminal.getvalue()
        hub.apply(
            RiteStarted(
                cast_id="aaaa0000",
                rite_id="r1",
                parent_id=None,
                name="repair",
                category="step",
                started_at=_WHEN,
            )
        )
        hub.apply(RiteDelta(cast_id="aaaa0000", rite_id="r1", delta="checks red"))
        hub.apply(CastGoodbye(cast_id="cccc0000", status="error", detail="boom"))
        await asyncio.sleep(_REPAINTED)
        held = terminal.getvalue()
        typist.enter("y")
        await _eventually(lambda: bool(peer.sent))
        await _eventually(lambda: "✗ failed: boom" in terminal.frame)

        assert held == asked
        assert "── heal bbbb0000 ──" in asked.rpartition(_HOME)[2]
        assert peer.sent == [
            DecideResolved(cast_id="bbbb0000", request_id="q1", answer="yes")
        ]
        assert "── heal bbbb0000 ──" in terminal.frame
        assert "checks red" not in terminal.frame
        await follower.close()
        await server.close()

    @staticmethod
    async def test_the_typed_cast_s_lines_go_to_its_place_and_come_back_at_the_end(
        desk: tuple[Board, _Terminal, _Typist],
    ):
        board, terminal, _ = desk
        board.out.write("before the board\n")

        board.entered(cast_id="a", label="heal aaaa", started_at=_WHEN)
        board.out.write("while the board is up\n")
        board.asker.notify("done", "sweep")
        board.render("a", _began())
        board.render(
            "a",
            RiteBegan(
                rite_id="r2",
                parent_id="r1",
                name="shell",
                category="medium",
                started_at=_WHEN,
            ),
        )
        board.render("a", RiteStreamed(rite_id="r2", delta="no remote"))
        board.ended(cast_id="root", status="ok", detail=None)
        board.ended(cast_id="a", status="error", detail="push refused\nTraceback")
        await _eventually(lambda: "✗ failed: push refused" in terminal.frame)
        shown = terminal.frame
        await board.close()

        assert terminal.getvalue().startswith(f"before the board\n{_ALTERNATE}")
        assert "\x1b]777;notify;vekna finished;sweep\x07" in terminal.getvalue()
        assert "notify" not in "".join(board.out.log.lines)
        assert "sweep root" not in shown
        assert terminal.getvalue().rpartition(_PLAIN)[2].splitlines() == [
            "while the board is up",
            "  1  heal aaaa  ✗ failed: push refused",
            "── heal aaaa ──",
            "▶ repair",
            "  ↳ shell",
            "    no remote",
            "push refused",
            "Traceback",
        ]
        board.out.write("after\n")
        assert terminal.getvalue().endswith("Traceback\nafter\n")

    @staticmethod
    async def test_when_the_cast_in_view_ends_the_next_running_one_comes_into_view(
        desk: tuple[Board, _Terminal, _Typist],
    ):
        board, terminal, _ = desk
        board.ended(cast_id="root", status="ok", detail=None)
        board.entered(cast_id="a", label="heal aaaa", started_at=_WHEN)
        board.entered(cast_id="b", label="heal bbbb", started_at=_WHEN)
        await _eventually(lambda: "── heal aaaa ──" in terminal.frame)

        board.ended(cast_id="a", status="ok", detail=None)
        await _eventually(lambda: "── heal bbbb ──" in terminal.frame)
        board.ended(cast_id="b", status="ok", detail=None)
        await asyncio.sleep(_REPAINTED)

        assert "── heal bbbb ──" in terminal.frame
        await board.close()

    @staticmethod
    async def test_a_number_moves_the_view_and_l_opens_the_whole_log(
        desk: tuple[Board, _Terminal, _Typist],
    ):
        board, terminal, typist = desk
        board.entered(cast_id="a", label="heal aaaa", started_at=_WHEN)
        board.entered(cast_id="b", label="heal bbbb", started_at=_WHEN)
        board.say(cast_id="b", label="heal bbbb", line="⏸ push? — answer it in `vekna`")
        board.say(cast_id="stranger", label="stranger", line="nobody's line")
        await _eventually(lambda: "nobody's line" in terminal.frame)
        noticed = terminal.frame

        typist.enter("3")
        await _eventually(lambda: "── heal bbbb ──" in terminal.frame)
        typist.enter("9")
        await _eventually(lambda: "there is no cast 9" in terminal.frame)
        typist.enter("what")
        await _eventually(lambda: "'what' is not a key" in terminal.frame)
        typist.enter("")
        typist.enter("l")
        await _eventually(lambda: "Enter returns" in terminal.getvalue())
        opened = terminal.getvalue()
        board.render("a", _began())
        await asyncio.sleep(_REPAINTED)
        paused = terminal.getvalue()
        typist.enter("")
        await _eventually(lambda: terminal.getvalue().count(_ALTERNATE) == _TWICE)

        assert opened.rpartition(_PLAIN)[2].splitlines() == [
            "── heal bbbb ──",
            "⏸ push? — answer it in `vekna`",
            "— Enter returns to the board —",
        ]
        assert paused == opened
        assert "heal bbbb  ▶" in noticed.splitlines()[2]
        assert noticed.splitlines()[2].endswith("⏸ push? — answer it in `vekna`")
        await _eventually(lambda: "repair" in terminal.frame.splitlines()[1])
        assert "⏸" in terminal.frame.splitlines()[2]
        board.render("b", _began())
        await _eventually(lambda: "⏸" not in terminal.frame.splitlines()[2])
        await board.close()

    @staticmethod
    async def test_a_key_typed_but_not_entered_is_not_the_start_of_an_answer(
        desk: tuple[Board, _Terminal, _Typist],
    ):
        board, terminal, typist = desk
        board.entered(cast_id="a", label="heal aaaa", started_at=_WHEN)
        await _eventually(lambda: "── heal aaaa ──" in terminal.frame)
        typist.type("2")
        await asyncio.sleep(_REPAINTED)

        asking = asyncio.create_task(board.decide(prompt="push?"))
        await _eventually(lambda: "push? [y/n]" in terminal.frame)
        typist.enter("y")

        assert await asyncio.wait_for(asking, timeout=2) == "yes"
        await board.close()

    @staticmethod
    async def test_a_question_that_fails_to_take_the_screen_leaves_the_board_usable(
        desk: tuple[Board, _Terminal, _Typist], monkeypatch: pytest.MonkeyPatch
    ):
        board, terminal, typist = desk
        board.entered(cast_id="a", label="heal aaaa", started_at=_WHEN)
        board.entered(cast_id="b", label="heal bbbb", started_at=_WHEN)
        await _eventually(lambda: "── heal aaaa ──" in terminal.frame)
        size = shutil.get_terminal_size
        failures = iter([True])

        def size_once_broken() -> os.terminal_size:
            if next(failures, False):
                msg = "no terminal"
                raise OSError(msg)
            return size()

        monkeypatch.setattr(shutil, "get_terminal_size", size_once_broken)
        with pytest.raises(OSError, match="no terminal"):
            await board.decide(prompt="push?")
        asking = asyncio.create_task(board.decide(prompt="again?"))
        await _eventually(lambda: "again? [y/n]" in terminal.frame)
        typist.enter("y")
        assert await asyncio.wait_for(asking, timeout=2) == "yes"
        typist.enter("3")

        await _eventually(lambda: "── heal bbbb ──" in terminal.frame)
        await board.close()

    @staticmethod
    async def test_a_question_that_cannot_drop_what_was_typed_leaves_the_keys_read(
        desk: tuple[Board, _Terminal, _Typist], monkeypatch: pytest.MonkeyPatch
    ):
        board, terminal, typist = desk
        board.entered(cast_id="a", label="heal aaaa", started_at=_WHEN)
        board.entered(cast_id="b", label="heal bbbb", started_at=_WHEN)
        await _eventually(lambda: "── heal aaaa ──" in terminal.frame)
        flush = termios.tcflush
        failures = iter([True])

        def flush_once_broken(fd: int, queue: int) -> None:
            if next(failures, False):
                msg = "no terminal"
                raise termios.error(msg)
            flush(fd, queue)

        monkeypatch.setattr(termios, "tcflush", flush_once_broken)
        with pytest.raises(termios.error, match="no terminal"):
            await board.decide(prompt="push?")
        typist.enter("3")

        await _eventually(lambda: "── heal bbbb ──" in terminal.frame)
        await board.close()

    @staticmethod
    async def test_a_question_opening_as_the_board_closes_is_asked_on_the_terminal(
        desk: tuple[Board, _Terminal, _Typist],
    ):
        board, terminal, typist = desk
        board.entered(cast_id="a", label="heal aaaa", started_at=_WHEN)
        await _eventually(lambda: "── heal aaaa ──" in terminal.frame)

        asking = asyncio.create_task(board.decide(prompt="push?"))
        # The question has stopped the command read and waits for it to end.
        await asyncio.sleep(0)
        await board.close()
        await _eventually(lambda: terminal.getvalue().endswith("push? [y/n] "))
        typist.enter("y")

        assert await asyncio.wait_for(asking, timeout=2) == "yes"
        assert terminal.getvalue().count(_ALTERNATE) == 1
        assert "push? [y/n]" in terminal.getvalue().rpartition(_PLAIN)[2]

    @staticmethod
    async def test_once_input_ends_no_key_is_read_and_the_board_is_still_painted(
        desk: tuple[Board, _Terminal, _Typist],
    ):
        board, terminal, typist = desk
        board.entered(cast_id="a", label="heal aaaa", started_at=_WHEN)
        board.entered(cast_id="b", label="heal bbbb", started_at=_WHEN)
        await _eventually(lambda: "── heal aaaa ──" in terminal.frame)

        typist.type(_END_OF_INPUT)
        await asyncio.sleep(_REPAINTED)
        typist.enter("3")
        await asyncio.sleep(_REPAINTED)
        board.ended(cast_id="b", status="ok", detail=None)
        await _eventually(lambda: "heal bbbb  ✓ done" in terminal.frame)

        assert "── heal aaaa ──" in terminal.frame
        await board.close()

    @staticmethod
    async def test_a_failed_cast_keeps_all_its_detail_in_its_log(
        desk: tuple[Board, _Terminal, _Typist],
    ):
        board, terminal, _ = desk
        board.entered(cast_id="a", label="heal aaaa", started_at=_WHEN)
        await _eventually(lambda: "── heal aaaa ──" in terminal.frame)

        board.ended(cast_id="a", status="error", detail="first\nsecond")
        await board.close()

        left = terminal.getvalue().rpartition(_PLAIN)[2]
        assert "  2  heal aaaa  ✗ failed: first\n" in left
        assert "── heal aaaa ──\nfirst\nsecond\n" in left

    @staticmethod
    async def test_answers_from_a_pipe_are_answers_and_not_keys(
        piped: tuple[Board, _Terminal, _Typist],
    ):
        board, terminal, typist = piped
        board.entered(cast_id="a", label="heal aaaa", started_at=_WHEN)
        await _eventually(lambda: "── heal aaaa ──" in terminal.frame)

        typist.enter("y")
        await asyncio.sleep(_REPAINTED)
        asking = asyncio.create_task(board.decide(prompt="push?"))

        assert await asyncio.wait_for(asking, timeout=2) == "yes"
        board.ended(cast_id="a", status="ok", detail=None)
        await _eventually(lambda: "heal aaaa  ✓ done" in terminal.frame)
        await board.close()

    @staticmethod
    async def test_before_any_cast_arrives_the_typed_cast_asks_on_the_plain_terminal(
        desk: tuple[Board, _Terminal, _Typist],
    ):
        board, terminal, typist = desk
        asking = asyncio.create_task(board.decide(prompt="push?"))
        await _eventually(lambda: "push? [y/n]" in terminal.getvalue())

        board.entered(cast_id="a", label="heal aaaa", started_at=_WHEN)
        await asyncio.sleep(_REPAINTED)
        waited = terminal.getvalue()
        typist.enter("y")

        assert await asyncio.wait_for(asking, timeout=2) == "yes"
        assert _ALTERNATE not in waited
        await _eventually(lambda: "── heal aaaa ──" in terminal.frame)
        await board.close()

    @staticmethod
    async def test_the_typed_cast_s_question_takes_the_view_and_a_second_one_waits(
        desk: tuple[Board, _Terminal, _Typist],
    ):
        board, terminal, typist = desk
        board.entered(cast_id="a", label="heal aaaa", started_at=_WHEN)
        board.entered(cast_id="b", label="heal bbbb", started_at=_WHEN)
        await _eventually(lambda: "── heal aaaa ──" in terminal.frame)

        async def asked_by_b() -> str:
            async with board.asking("b", 4):
                return await board.asker.decide(prompt="merge?")

        first = asyncio.create_task(board.decide(prompt="push?"))
        await _eventually(lambda: "push? [y/n]" in terminal.frame)
        second = asyncio.create_task(asked_by_b())
        await asyncio.sleep(_REPAINTED)
        one_open = terminal.frame
        typist.enter("y")
        await _eventually(lambda: "merge? [y/n]" in terminal.frame)
        typist.enter("n")

        assert await asyncio.wait_for(first, timeout=2) == "yes"
        assert await asyncio.wait_for(second, timeout=2) == "no"
        assert "── sweep root ──" in one_open
        assert "merge?" not in one_open
        await board.close()

    @staticmethod
    async def test_when_the_typed_cast_ends_well_and_nothing_runs_the_view_leaves_it(
        desk: tuple[Board, _Terminal, _Typist],
    ):
        board, terminal, typist = desk
        board.entered(cast_id="a", label="heal aaaa", started_at=_WHEN)
        asking = asyncio.create_task(board.decide(prompt="push?"))
        await _eventually(lambda: "push? [y/n]" in terminal.frame)
        typist.enter("y")
        assert await asyncio.wait_for(asking, timeout=2) == "yes"
        board.ended(cast_id="a", status="ok", detail=None)

        board.ended(cast_id="root", status="ok", detail=None)

        await _eventually(lambda: "── heal aaaa ──" in terminal.frame)
        assert "── sweep root ──" not in terminal.frame
        await board.close()

    @staticmethod
    async def test_a_question_takes_the_screen_back_from_a_whole_log(
        desk: tuple[Board, _Terminal, _Typist],
    ):
        board, terminal, typist = desk
        board.entered(cast_id="a", label="heal aaaa", started_at=_WHEN)
        typist.enter("l")
        await _eventually(lambda: "Enter returns" in terminal.getvalue())

        async def asked_by_a_stranger() -> str:
            async with board.asking("stranger", 4):
                return await board.asker.decide(prompt="push?")

        asking = asyncio.create_task(asked_by_a_stranger())
        await _eventually(lambda: "push? [y/n]" in terminal.frame)
        typist.enter("y")

        assert await asyncio.wait_for(asking, timeout=2) == "yes"
        assert terminal.getvalue().count(_ALTERNATE) == _TWICE
        assert "── heal aaaa ──" in terminal.frame
        await board.close()

    @staticmethod
    async def test_closing_under_a_question_leaves_the_plain_terminal(
        desk: tuple[Board, _Terminal, _Typist],
    ):
        board, terminal, _ = desk
        board.entered(cast_id="a", label="heal aaaa", started_at=_WHEN)
        asking = asyncio.create_task(board.decide(prompt="push?"))
        await _eventually(lambda: "push? [y/n]" in terminal.frame)

        asking.cancel()
        await board.close()
        await asyncio.gather(asking, return_exceptions=True)

        assert terminal.getvalue().count(_ALTERNATE) == 1
        assert terminal.getvalue().count(_PLAIN) == 1

    @staticmethod
    async def test_a_board_that_never_opened_closes_to_nothing(
        desk: tuple[Board, _Terminal, _Typist],
    ):
        board, terminal, _ = desk
        board.render("root", _began())
        board.render(
            "root", RiteEnded(rite_id="r1", status="ok", result=None, finished_at=_WHEN)
        )
        asking = asyncio.create_task(board.decide(prompt="push?"))
        await _eventually(lambda: "push? [y/n]" in terminal.getvalue())
        desk[2].enter("n")
        answer = await asyncio.wait_for(asking, timeout=2)

        await board.close()

        assert answer == "no"
        assert terminal.getvalue().endswith("push? [y/n] ")
        assert _ALTERNATE not in terminal.getvalue()

    @staticmethod
    async def test_with_nobody_typing_the_board_is_still_painted(tmp_path: Path):
        terminal = _Terminal()
        screen = Tail(terminal)
        with (tmp_path / "empty").open("w+") as inp:
            board = _board_on(screen=screen, inp=inp)
            board.entered(cast_id="a", label="heal aaaa", started_at=_WHEN)
            await asyncio.sleep(_REPAINTED)

            board.ended(cast_id="a", status="ok", detail=None)
            await _eventually(lambda: "heal aaaa  ✓ done" in terminal.frame)

            await board.close()

    @staticmethod
    async def test_a_board_that_cannot_paint_leaves_the_terminal_and_says_why(
        desk: tuple[Board, _Terminal, _Typist], monkeypatch: pytest.MonkeyPatch
    ):
        board, terminal, typist = desk
        board.entered(cast_id="a", label="heal aaaa", started_at=_WHEN)
        await _eventually(lambda: "── heal aaaa ──" in terminal.frame)

        def no_size() -> os.terminal_size:
            msg = "no terminal"
            raise OSError(msg)

        monkeypatch.setattr(shutil, "get_terminal_size", no_size)
        board.ended(cast_id="a", status="ok", detail=None)
        await _eventually(lambda: _PLAIN in terminal.getvalue())
        asking = asyncio.create_task(board.decide(prompt="push?"))
        await _eventually(lambda: "push? [y/n]" in terminal.getvalue())
        typist.enter("y")

        assert await asyncio.wait_for(asking, timeout=2) == "yes"
        left = terminal.getvalue().rpartition(_PLAIN)[2]
        assert (
            "  2  heal aaaa  ✓ done\nthe board stopped: OSError('no terminal')\n"
            in left
        )
        assert left.endswith("push? [y/n] ")
        await board.close()

    @staticmethod
    async def test_a_read_that_fails_leaves_the_terminal_and_says_why():
        terminal = _Terminal()
        screen = Tail(terminal)
        board = _board_on(screen=screen, inp=_Broken())

        board.entered(cast_id="a", label="heal aaaa", started_at=_WHEN)
        await _eventually(lambda: _PLAIN in terminal.getvalue())

        left = terminal.getvalue().rpartition(_PLAIN)[2]
        assert left.endswith("the board stopped: OSError('keys gone')\n")
        await board.close()


@pytest.mark.asyncio
class TestQuestionRows:
    @staticmethod
    @pytest.mark.parametrize(
        ("options", "retry"),
        [
            (None, "please answer y or n"),
            (["a", "b", "c"], "invalid choice; try again"),
        ],
    )
    async def test_every_bad_answer_a_question_allows_fits_the_rows_it_kept(
        desk: tuple[Board, _Terminal, _Typist], options: list[str] | None, retry: str
    ):
        board, terminal, typist = desk
        board.entered(cast_id="a", label="heal aaaa", started_at=_WHEN)
        for number in range(_LOG_LINES):
            board.out.write(f"line {number}\n")
        asking = asyncio.create_task(board.decide(prompt="pick?", options=options))
        await _eventually(lambda: "pick?" in terminal.frame)
        for tried in range(1, _ATTEMPTS + 1):
            typist.enter("x")
            await _eventually(partial(_said, terminal, retry, tried))
        asked = terminal.frame

        with pytest.raises(StandalonePromptError):
            await asyncio.wait_for(asking, timeout=2)
        # Each answer typed ends in a newline the terminal echoes, which the
        # output stream never sees.
        assert asked.count("\n") + _ATTEMPTS + 1 <= _ROWS
        await board.close()
