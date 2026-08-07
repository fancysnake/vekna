import sys
from pathlib import Path

import pytest

# Only what a test itself brought in: a module imported from the interpreter,
# the venv or vekna's own src stays. Dropping those breaks any library that
# keeps global state keyed on a module — pydantic caches generic models by
# `__module__`, so re-importing one it had already specialised raises a KeyError
# out of its own internals.
_KEEP = (Path(sys.prefix), Path(sys.base_prefix), Path(__file__).parents[3] / "src")


def _from_a_test(name: str) -> bool:
    file = getattr(sys.modules[name], "__file__", None)
    return file is not None and not any(Path(file).is_relative_to(k) for k in _KEEP)


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
        if _from_a_test(name):
            del sys.modules[name]
    sys.path[:] = path
