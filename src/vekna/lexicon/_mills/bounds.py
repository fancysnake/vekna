import asyncio
import types
from collections.abc import Awaitable
from typing import TypeVar

from vekna.lexicon._pacts import MediumBoundaryError, RiteTimeoutError, RitualError

_ResultT = TypeVar("_ResultT")


# No `seconds` is no deadline, as it is to `asyncio.timeout`.
async def bounded(
    work: Awaitable[_ResultT], *, seconds: float | None, named: str
) -> _ResultT:
    deadline = asyncio.timeout(seconds)
    try:
        async with deadline:
            return await work
    # Only the deadline's own: a `TimeoutError` the work raised for itself is
    # the work failing, and passes through as it came.
    except TimeoutError as error:
        if not deadline.expired():
            raise
        msg = f"{named} timed out after {seconds:g}s"
        raise RiteTimeoutError(msg) from error


# The work is cancelled, not abandoned: each medium under it reaps what it
# started before this raises. A medium's coroutine carries the medium's name.
async def timeout(work: Awaitable[_ResultT], *, seconds: float) -> _ResultT:
    coroutine = work if isinstance(work, types.CoroutineType) else None
    if seconds <= 0:
        # Closed, or the refused work is a coroutine never awaited.
        if coroutine is not None:
            coroutine.close()
        msg = f"timeout takes a positive number of seconds, got {seconds}"
        raise MediumBoundaryError(msg)
    named = "the work" if coroutine is None else coroutine.__name__
    return await bounded(work, seconds=seconds, named=named)


# First to return wins; the rest are cancelled and awaited, so each loser's
# medium has reaped what it started — and its rite reads cancelled — before
# this returns. An entrant that raises is out of the race, not the end of it.
async def race(*work: Awaitable[_ResultT]) -> _ResultT:
    if not work:
        msg = "race needs at least one entrant"
        raise MediumBoundaryError(msg)
    entrants = [asyncio.ensure_future(w) for w in work]
    running: set[asyncio.Future[_ResultT]] = set(entrants)
    failed: list[str] = []
    try:
        # Each round ends at least one entrant, so there are at most this many.
        for _ in work:
            if not running:
                break
            finished, running = await asyncio.wait(
                running, return_when=asyncio.FIRST_COMPLETED
            )
            # Those that ended in one round are tied, and a tie goes to the one
            # passed first: a set's order would settle it differently each run.
            for entrant in (each for each in entrants if each in finished):
                if entrant.cancelled():
                    failed.append("cancelled")
                elif (error := entrant.exception()) is not None:
                    failed.append(f"{type(error).__name__}: {error}")
                else:
                    return entrant.result()
    finally:
        for loser in running:
            loser.cancel()
        await asyncio.gather(*running, return_exceptions=True)
    msg = f"every entrant in the race failed — {'; '.join(failed)}"
    raise RitualError(msg)
