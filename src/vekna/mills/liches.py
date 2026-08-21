import secrets
from collections.abc import Callable, Collection, Sequence
from datetime import datetime

from vekna.pacts.lich import Phylactery
from vekna.specs.names import ADJECTIVES, NOUNS

# How many pairs are drawn before the name gets a number on the end. With 256
# pairs and a handful taken, a run this long means the draw is unlucky rather
# than the list exhausted — and counting up from 2 is what a project with three
# hundred liches would want anyway.
_DRAWS = 20

Choose = Callable[[Sequence[str]], str]


# Sticky once drawn, so this runs at a lich's first rising and never again. The
# check is against *every* row, live or dormant: the name is the key, and a
# dormant lich answering to the same one is how a revive would reach the wrong
# station.
def draw_name(*, taken: Collection[str], choose: Choose = secrets.choice) -> str:
    for _ in range(_DRAWS):
        if (drawn := f"{choose(ADJECTIVES)}-{choose(NOUNS)}") not in taken:
            return drawn
    return _numbered(f"{choose(ADJECTIVES)}-{choose(NOUNS)}", taken=taken)


# A name nobody holds, from one that somebody does. Bounded by the number of
# rows: `len(taken) + 2` suffixes cannot all be taken by `len(taken)` rows.
def _numbered(base: str, *, taken: Collection[str]) -> str:
    for suffix in range(2, len(taken) + 3):
        if (numbered := f"{base}-{suffix}") not in taken:
            return numbered
    raise AssertionError(base)  # pragma: no cover — more suffixes than rows


# What `vekna lich` offers where it is run, and nothing else. Filtered by root
# because the prompt is fifty entries deep by the second month otherwise, and a
# lich rooted somewhere else is not a thing this directory can carry on.
# Newest first: the one you were working in yesterday is the one you mean today.
def sleeping_here(rows: Sequence[Phylactery], *, root: str) -> list[Phylactery]:
    here = [row for row in rows if row.root == root]
    return sorted(here, key=_raised_at, reverse=True)


# A named function rather than a lambda or an `attrgetter`: both come back as
# `Any` to a type checker reading this at its strictest, and the repository
# counts every one of those.
def _raised_at(row: Phylactery) -> datetime:
    return row.created
