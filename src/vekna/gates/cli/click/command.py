import asyncio
import os
from typing import TYPE_CHECKING

import click

if TYPE_CHECKING:
    from collections.abc import Callable

    from vekna.pacts.notify import NotifyClientMillProtocol
    from vekna.pacts.server import ServerMillProtocol

    ServerMillFactory = Callable[[], ServerMillProtocol]
    NotifyClientMillFactory = Callable[[str], NotifyClientMillProtocol]


_MISSING_TMUX_MSG = (
    "TMUX and TMUX_PANE must be set — run `vekna notify` from inside a tmux pane"
)


class ClickGate:
    def __init__(
        self,
        server_mill_factory: ServerMillFactory,
        notify_client_mill_factory: NotifyClientMillFactory,
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
        def notify() -> None:
            tmux_env = os.environ.get("TMUX")
            pane_id = os.environ.get("TMUX_PANE")
            if tmux_env is None or pane_id is None:
                raise click.UsageError(_MISSING_TMUX_MSG)
            mill = self._notify_client_mill_factory(tmux_env)
            asyncio.run(mill.notify(pane_id))

        vekna.add_command(notify)

        return vekna
