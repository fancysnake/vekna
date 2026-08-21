from typing import Protocol


# What a surface needs of a terminal: painted over, and read a line at a time.
# `None` from a read is end of input — a daemon whose stdin is closed still has
# casts to serve, it just has nobody typing at it.
class Screen(Protocol):
    def show(self, screen: str) -> None: ...

    async def read_line(self) -> str | None: ...
