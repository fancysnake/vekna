from collections.abc import Iterator
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from vekna.trial import Trial


# The whole plugin: one fixture, handed out already installed. `Trial` is a
# context manager for everyone not running pytest, which is what keeps this a
# wrapper rather than the feature.
# It lives in the root `edges` — the framework edge, outside GLIMPSE proper —
# rather than in `vekna/trial/`, and imports inside the fixture body. pytest
# loads an entry-point plugin before pytest-cov starts measuring, and importing
# `vekna.trial._edges` would run `vekna/trial/__init__.py` on the way in: every
# module that pulls in, the whole lexicon among them, would then be reported as
# unexecuted by a suite measuring vekna itself. Verified, not guessed — it cost
# this repo 16 points of coverage before it moved here.
@pytest.fixture
def trial() -> Iterator["Trial"]:
    from vekna.trial import Trial as Running

    with Running() as running:
        yield running
