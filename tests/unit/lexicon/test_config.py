import importlib.util
import sys
from pathlib import Path
from types import ModuleType

import pytest

from vekna.lexicon import _loader

_LOADER_PATH = Path(_loader.__file__)


def _load_loader(name: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, _LOADER_PATH)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class TestTomlBackend:
    @staticmethod
    @pytest.mark.skipif(sys.version_info < (3, 11), reason="stdlib tomllib needs 3.11+")
    def test_uses_stdlib_tomllib_on_modern_python(monkeypatch):
        monkeypatch.setattr(sys, "version_info", (3, 11, 0, "final", 0))

        module = _load_loader("vekna.lexicon._loader_modern")

        assert module.tomllib.__name__ == "tomllib"

    @staticmethod
    def test_falls_back_to_tomli_below_311(monkeypatch, tmp_path):
        loaded: list[bytes] = []
        stub = ModuleType("tomli")

        def _load(handle):
            loaded.append(handle.read())
            return {"rituals": {"modules": ["pkg.rites"], "files": ["rituals.py"]}}

        stub.load = _load
        monkeypatch.setitem(sys.modules, "tomli", stub)
        monkeypatch.setattr(sys, "version_info", (3, 10, 12, "final", 0))

        module = _load_loader("vekna.lexicon._loader_py310")

        assert module.tomllib is stub

        config = tmp_path / ".vekna.toml"
        config.write_bytes(b"[rituals]\n")

        assert module.read_config(config) == (["pkg.rites"], ["rituals.py"])
        assert loaded == [b"[rituals]\n"]
