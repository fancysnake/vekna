import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import Annotated

from pydantic import AfterValidator, AnyUrl


def _existing_file(path: Path) -> Path:
    if not path.is_file():
        msg = f"not a readable file: {path}"
        raise ValueError(msg)
    return path


def _existing_directory(path: Path) -> Path:
    if not path.is_dir():
        msg = f"not a directory: {path}"
        raise ValueError(msg)
    return path


def _nonempty_git_ref(value: str) -> str:
    if not value.strip():
        msg = "git ref must be non-empty"
        raise ValueError(msg)
    return value


def sha256_of(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


@dataclass(frozen=True)
class TextSpec:
    multiline: bool = False


File = Annotated[Path, AfterValidator(_existing_file)]
Directory = Annotated[Path, AfterValidator(_existing_directory)]
Text = Annotated[str, TextSpec()]
Url = AnyUrl
GitRef = Annotated[str, AfterValidator(_nonempty_git_ref)]


__all__ = ["Directory", "File", "GitRef", "Text", "TextSpec", "Url", "sha256_of"]
