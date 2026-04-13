import hashlib
import re
import tempfile
from pathlib import Path, PurePosixPath

_SLUG_CLEAN = re.compile(r"[^a-z0-9]+")
STEM_DIGEST_LENGTH = 6

IDLE_TYPING_THRESHOLD_SECONDS = 3.0
ATTENTION_POLL_INTERVAL_SECONDS = 1.0
ATTENTION_WINDOW_STATUS_STYLE = "bg=red,fg=white,bold"


def _slug(value: str) -> str:
    cleaned = _SLUG_CLEAN.sub("-", value.lower()).strip("-")
    return cleaned or "root"


def stem_for_cwd(cwd: Path) -> str:
    absolute = cwd.resolve()
    name = _slug(absolute.name)
    digest = hashlib.sha256(str(absolute).encode()).hexdigest()[:STEM_DIGEST_LENGTH]
    return f"vekna-{name}-{digest}"


def stem_from_tmux_env(tmux_env: str) -> str:
    socket_path = tmux_env.split(",", 1)[0]
    return PurePosixPath(socket_path).name


def paths_for(stem: str) -> tuple[str, str, str]:
    unix_socket_path = str(PurePosixPath(tempfile.gettempdir()) / f"{stem}.sock")
    return stem, stem, unix_socket_path
