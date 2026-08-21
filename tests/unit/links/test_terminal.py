import asyncio
import io

from vekna.links.terminal import Terminal


class TestTerminal:
    @staticmethod
    def test_it_paints_what_it_is_given():
        out = io.StringIO()

        Terminal(out=out).show("a screen")

        assert out.getvalue() == "a screen"

    @staticmethod
    def test_a_line_comes_back_without_its_newline():
        terminal = Terminal(out=io.StringIO(), inp=io.StringIO("1\n"))

        assert asyncio.run(terminal.read_line()) == "1"

    # Nobody at the keyboard is not the same as an empty line: the daemon stops
    # asking rather than spinning on a read that returns instantly forever.
    @staticmethod
    def test_the_end_of_input_is_nothing_at_all():
        terminal = Terminal(out=io.StringIO(), inp=io.StringIO(""))

        assert asyncio.run(terminal.read_line()) is None
