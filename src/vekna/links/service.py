import asyncio
import os
import shutil
from collections.abc import Sequence
from pathlib import Path

from vekna.wire import default_config_path

UNIT = "vekna.service"
_SYSTEMCTL = "systemctl"
_VEKNA = "vekna"
_NO_SYSTEMCTL = "systemctl is not on PATH"
# Where a user's own tools are installed, under home: pip and pipx, then mise.
_HOME_TOOLS = (".local/bin", ".local/share/mise/shims")
_SYSTEM_TOOLS = "/usr/local/bin:/usr/bin:/bin"
_TEMPLATE = """\
[Unit]
Description=vekna daemon
Documentation=https://vekna.fancysnake.dev/cli/#vekna-service

[Service]
# `serve` forks the daemon and returns.
Type=forking
ExecStart={serve}
ExecStop={stop}
# Casts live in this unit's control group. The default would kill them with the
# daemon; `vekna stop` leaves them running to rejoin the next one.
KillMode=process
# Home, and a PATH of the user's own tools: nothing of the project or the shell
# the unit was written from reaches the daemon, or the casts that inherit this.
WorkingDirectory=%h
Environment={path}

[Install]
WantedBy=default.target
"""


# One word of a unit file's value: systemd splits on spaces and reads `%` as a
# specifier.
def _word(value: str) -> str:
    escaped = value.replace("\\", "\\\\").replace('"', '\\"').replace("%", "%%")
    return f'"{escaped}"'


# A command line, where systemd also reads `$` as a variable.
def _line(words: Sequence[str]) -> str:
    return " ".join(_word(word).replace("$", "$$") for word in words)


# Where systemd looks for a user's own units.
def unit_path() -> Path:
    return default_config_path().parents[1] / "systemd" / "user" / UNIT


def search_path() -> str:
    home = Path.home()
    return os.pathsep.join(
        [*(str(home / tools) for tools in _HOME_TOOLS), _SYSTEM_TOOLS]
    )


# The vekna the service runs: the user's own, never one a project installed.
def user_vekna() -> str | None:
    return shutil.which(_VEKNA, path=search_path())


def write_unit(*, vekna: str) -> Path:
    path = unit_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        _TEMPLATE.format(
            serve=_line([vekna, "serve"]),
            stop=_line([vekna, "stop"]),
            path=_word(f"PATH={search_path()}"),
        ),
        encoding="utf-8",
    )
    return path


# What went wrong, in a sentence, or `None`.
async def systemctl(*args: str) -> str | None:
    if (found := shutil.which(_SYSTEMCTL)) is None:
        return _NO_SYSTEMCTL
    ran = await asyncio.create_subprocess_exec(
        found,
        "--user",
        *args,
        stdin=asyncio.subprocess.DEVNULL,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
    )
    said, _ = await ran.communicate()
    if ran.returncode:
        told = said.decode(errors="replace").strip()
        return f"`systemctl --user {' '.join(args)}` failed ({ran.returncode}): {told}"
    return None
