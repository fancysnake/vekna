import importlib
from typing import Protocol, cast

import click
from click import Group

_CAST_CONTEXT: dict[str, bool] = {"ignore_unknown_options": True}
_RUNTIME = "vekna.lexicon._inits"


# The root project may not import the lexicon: `vekna` (daemon) and `vekna cast`
# are one binary, so importing the CLI must never pull ritual code, folios or
# the agent SDK into the daemon's process. The cast runtime is reached by name
# at call time, and typed through this Protocol rather than by attribute access
# on an untyped module.
class _Runtime(Protocol):
    @staticmethod
    def main(argv: list[str]) -> int: ...
    @staticmethod
    def rituals_list() -> int: ...
    @staticmethod
    def rituals_show(name: str) -> int: ...


def _runtime() -> _Runtime:
    return cast("_Runtime", importlib.import_module(_RUNTIME))


@click.command(
    "cast",
    context_settings=_CAST_CONTEXT,
    add_help_option=False,
    help="Run a ritual from rituals.py (try `vekna cast --help`).",
)
@click.argument("ritual_args", nargs=-1, type=click.UNPROCESSED)
def _cast(ritual_args: tuple[str, ...]) -> None:
    raise SystemExit(_runtime().main(list(ritual_args)))


@click.command("list", help="List rituals and the options each one takes.")
def _rituals_list() -> None:
    raise SystemExit(_runtime().rituals_list())


@click.command("show", help="Show a ritual's components and step graph.")
@click.argument("name")
def _rituals_show(name: str) -> None:
    raise SystemExit(_runtime().rituals_show(name))


@click.group("rituals", help="Inspect the ritual library.")
def _rituals() -> None:
    pass


_rituals.add_command(_rituals_list)
_rituals.add_command(_rituals_show)


def init_command() -> Group:
    @click.group(invoke_without_command=True)
    def vekna() -> None:
        ctx = click.get_current_context()
        if ctx.invoked_subcommand is None:
            click.echo(ctx.get_help())

    vekna.add_command(_cast)
    vekna.add_command(_rituals)
    return vekna


def run() -> None:  # pragma: no cover
    init_command()()


if __name__ == "__main__":
    run()  # pragma: no cover
