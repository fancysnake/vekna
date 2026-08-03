import sys

import pytest


# A ritual package is imported under its own name, and one process cannot hold
# two packages called `rituals`: without this, the first test to build one hands
# its modules to every test after it. sys.path goes back too — the loader
# prepends the package's parent, and pytest's own entries must not drift.
@pytest.fixture(autouse=True)
def _fresh_imports():
    modules = set(sys.modules)
    path = list(sys.path)

    yield

    for name in set(sys.modules) - modules:
        del sys.modules[name]
    sys.path[:] = path
