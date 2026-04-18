import asyncio
import os
import sys
from collections.abc import Callable
from typing import IO

import click

from vekna.pacts.notify import NotifyClientMillProtocol
from vekna.pacts.server import ServerMillProtocol

_MISSING_TMUX_MSG = (
    "TMUX and TMUX_PANE must be set — run `vekna notify` from inside a tmux pane"
)


class ClickGate:
    def __init__(
        self,
        server_mill_factory: Callable[[], ServerMillProtocol],
        notify_client_mill_factory: Callable[[str], NotifyClientMillProtocol],
    ) -> None:
        self._server_mill_factory = server_mill_factory
        self._notify_client_mill_factory = notify_client_mill_factory

    def build_group(self) -> click.Group:
        @click.group(invoke_without_command=True)
        def vekna() -> None:
            ctx = click.get_current_context()
            if ctx.invoked_subcommand is None:
                asyncio.run(self._server_mill_factory().run())

        @click.command()
        @click.option("--app", required=True, help="Application name (e.g. claude)")
        @click.option("--hook", required=True, help="Hook name (e.g. Notification)")
        def notify(app: str, hook: str) -> None:
            tmux_env = os.environ.get("TMUX")
            pane_id = os.environ.get("TMUX_PANE")
            if tmux_env is None or pane_id is None:
                raise click.UsageError(_MISSING_TMUX_MSG)
            stdin: IO[str] = sys.stdin
            payload: str = "" if stdin.isatty() else stdin.read()
            mill = self._notify_client_mill_factory(tmux_env)
            asyncio.run(
                mill.notify(
                    app=app, hook=hook, payload=payload, meta={"TMUX_PANE": pane_id}
                )
            )

        vekna.add_command(notify)

        return vekna
