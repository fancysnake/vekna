import hashlib
import re
from pathlib import Path

STEM_DIGEST_LENGTH = 6

_SLUG_CLEAN = re.compile(r"[^a-z0-9]+")


def _slug(value: str) -> str:
    cleaned = _SLUG_CLEAN.sub("-", value.lower()).strip("-")
    return cleaned or "root"


def stem_for_cwd(cwd: Path) -> str:
    absolute = cwd.resolve()
    name = _slug(absolute.name)
    digest = hashlib.sha256(str(absolute).encode()).hexdigest()[:STEM_DIGEST_LENGTH]
    return f"vekna-{name}-{digest}"
