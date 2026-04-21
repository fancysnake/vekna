import asyncio
import contextlib
import os
import sys
from collections.abc import Callable
from pathlib import Path
from typing import IO

import click

from vekna.pacts.bus import App, Hook
from vekna.pacts.notify import Event, NotifyClientMillProtocol
from vekna.pacts.server import ServerMillProtocol

_MISSING_TMUX_PANE_MSG = (
    "TMUX_PANE must be set — run `vekna notify` from inside a tmux pane"
)


class ClickGate:
    def __init__(
        self,
        server_mill_factory: Callable[[], ServerMillProtocol],
        notify_client_mill_factory: Callable[[], NotifyClientMillProtocol],
        ensure_daemon: Callable[[], None],
    ) -> None:
        self._server_mill_factory = server_mill_factory
        self._notify_client_mill_factory = notify_client_mill_factory
        self._ensure_daemon = ensure_daemon

    def build_group(self) -> click.Group:
        @click.group(invoke_without_command=True)
        def vekna() -> None:
            ctx = click.get_current_context()
            if ctx.invoked_subcommand is None:
                self._ensure_daemon()
                mill = self._notify_client_mill_factory()
                response = asyncio.run(
                    mill.request(
                        Event(
                            app=App.VEKNA,
                            hook=Hook.ENSURE_SESSION,
                            payload="",
                            meta={"cwd": str(Path.cwd())},
                        )
                    )
                )
                session_name = response.data["session_name"]
                os.execvp(  # noqa: S606
                    "tmux", ["tmux", "attach-session", "-t", session_name]  # noqa: S607
                )

        @click.command()
        def daemon() -> None:
            asyncio.run(self._server_mill_factory().run())

        @click.command()
        @click.option("--app", required=True, help="Application name (e.g. claude)")
        @click.option("--hook", required=True, help="Hook name (e.g. Notification)")
        def notify(app: str, hook: str) -> None:
            if (pane_id := os.environ.get("TMUX_PANE")) is None:
                raise click.UsageError(_MISSING_TMUX_PANE_MSG)
            stdin: IO[str] = sys.stdin
            payload: str = "" if stdin.isatty() else stdin.read()
            mill = self._notify_client_mill_factory()
            asyncio.run(
                mill.notify(
                    app=app, hook=hook, payload=payload, meta={"TMUX_PANE": pane_id}
                )
            )

        @click.command("status-bar")
        @click.option("--session", default="", help="Current tmux session name")
        def status_bar(session: str) -> None:
            mill = self._notify_client_mill_factory()
            with contextlib.suppress(OSError):
                response = asyncio.run(
                    mill.request(
                        Event(
                            app=App.VEKNA,
                            hook=Hook.STATUS_BAR,
                            payload="",
                            meta={"session_name": session},
                        )
                    )
                )
                click.echo(response.data.get("text", ""))

        vekna.add_command(daemon)
        vekna.add_command(notify)
        vekna.add_command(status_bar)

        return vekna
