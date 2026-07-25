import click
from click import Group

from vekna.lexicon import main, rituals_list, rituals_show

_CAST_CONTEXT: dict[str, bool] = {"ignore_unknown_options": True}


@click.command(
    "cast",
    context_settings=_CAST_CONTEXT,
    add_help_option=False,
    help="Run a ritual from rituals.py (try `vekna cast --help`).",
)
@click.argument("ritual_args", nargs=-1, type=click.UNPROCESSED)
def _cast(ritual_args: tuple[str, ...]) -> None:
    raise SystemExit(main(list(ritual_args)))


@click.command("list", help="List rituals and the options each one takes.")
def _rituals_list() -> None:
    raise SystemExit(rituals_list())


@click.command("show", help="Show a ritual's components and step graph.")
@click.argument("name")
def _rituals_show(name: str) -> None:
    raise SystemExit(rituals_show(name))


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
