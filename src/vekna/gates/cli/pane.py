from rich.text import Text
from textual.geometry import Size
from textual.widgets import Log
from typing_extensions import override


# The output of the line under the cursor. A line wider than the pane is drawn
# over as many rows as it needs, so `lines` holds rows, not what was said. The
# rows are cut for the width the pane has when they are shown. The pane keeps
# what it was told to show and draws it again when its width changes; cutting
# rows is slow for a long output, so what was drawn at that width stays. It
# follows its newest line unless the operator scrolled up off the line it was
# left on when it last followed; reaching the end starts it again. It keeps
# following when the page above it grows and pushes the end further down.
# `page` names what is shown: another page follows from its end again.
class Output(Log):
    DEFAULT_CSS = """
    Output { overflow-x: hidden; }
    """

    _said: tuple[str, ...] = ()
    _drawn: tuple[tuple[str, ...], int] | None = None
    _page: str | None = None
    _following: bool = True
    _left_at: float = 0

    def show(self, *, page: str | None, said: list[str]) -> None:
        if page != self._page:
            self._page, self._following = page, True
        else:
            self._follows()
        self._said = tuple(said)
        self._draw()
        if self._following:
            self.call_after_refresh(self._to_end, self.scroll_y)

    # A layout that lands after the last scroll to the end leaves the pane short
    # of its newest line.
    def keep_end(self) -> None:
        if self._follows():
            self._to_end(self.scroll_y)

    # The pane draws its rows in the layout that resized it, so it sees the page
    # once, after Textual has pulled the scroll up to the old rows' end and the
    # new rows are in. A pull is no scroll of the operator's: the follow is read
    # before it, while the scroll is still theirs, and kept after.
    @override
    def _size_updated(
        self, size: Size, virtual_size: Size, container_size: Size, layout: bool = True
    ) -> bool:
        if changed_size := size != self._size:
            self._follows()
        changed = super()._size_updated(size, virtual_size, container_size, layout)
        if changed_size:
            self._draw()
            if self._following:
                self._left_at = self.scroll_y
                self.call_after_refresh(self._to_end, self.scroll_y)
        return changed

    def _draw(self) -> None:
        # A pane with no room draws nothing; the resize that gives it room draws.
        if (width := self.scrollable_content_region.width) < 1:
            return
        if self._drawn == (self._said, width):
            return
        self._drawn = (self._said, width)
        # Log.write_lines drops an empty line, so a blank row is drawn as a space.
        rows = [
            row.plain or " "
            for line in self._said
            for row in Text(line).wrap(self.app.console, width)
        ]
        self.clear()
        self.write_lines(rows)

    def _follows(self) -> bool:
        # An upward scroll that has only begun still rounds to the end.
        leaving = self.scroll_target_y < self.scroll_y
        if self.is_vertical_scroll_end and not leaving:
            self._following = True
        elif leaving or self.scroll_y < self._left_at:
            self._following = False
        return self._following

    # A scroll the operator made while the refresh was pending stands, one that
    # has only begun included; Textual clamping it onto a shorter page's end is
    # no scroll of theirs.
    def _to_end(self, asked_at: float) -> None:
        if self.scroll_target_y < self.scroll_y:
            return
        if self.scroll_y != asked_at and not self.is_vertical_scroll_end:
            return
        self.scroll_end(animate=False, immediate=True, x_axis=False)
        self._left_at = self.max_scroll_y
