import typer
import logging
from rich.console import Console
from typing_extensions import Annotated

from tiddl.cli.config import APP_PATH, CONFIG
from tiddl.cli.ctx import ContextObject, Context
from tiddl.cli.commands import register_commands
from tiddl.core.utils.ffmpeg import is_ffmpeg_installed as ifs
from tiddl.version import APP_VERSION

log = logging.getLogger("tiddl")

app = typer.Typer(name="tiddl", no_args_is_help=True, rich_markup_mode="rich")
register_commands(app)


def version_callback(value: bool | None):
    if value:
        typer.echo(APP_VERSION)
        raise typer.Exit()


@app.callback()
def callback(
    ctx: Context,
    OMIT_CACHE: Annotated[
        bool,
        typer.Option(
            "--omit-cache",
        ),
    ] = not CONFIG.enable_cache,
    DEBUG: Annotated[
        bool,
        typer.Option(
            "--debug",
        ),
    ] = CONFIG.debug,
    VERSION: Annotated[
        bool | None,
        typer.Option(
            "--version",
            callback=version_callback,
            is_eager=True,
            help="Show version and exit.",
        ),
    ] = None,
):
    f"""
    tiddl {APP_VERSION} - download tidal tracks \u266b

    [link=https://github.com/CapitanRalph/tiddl]github (https://github.com/CapitanRalph/tiddl)[/link]
    """

    log.debug(f"{APP_VERSION=}")
    log.debug(f"{ctx.params=}")

    is_ffmpeg_installed = ifs()
    log.debug(f"{is_ffmpeg_installed=}")

    if DEBUG:
        debug_path = APP_PATH / "api_debug"
    else:
        debug_path = None

    ctx.obj = ContextObject(
        api_omit_cache=OMIT_CACHE, console=Console(), debug_path=debug_path
    )

    if not is_ffmpeg_installed:
        ctx.obj.console.print(
            "[yellow]WARNING ffmpeg is not installed, tiddl might not work properly, "
            + "[link=https://github.com/oskvr37/tiddl/blob/main/README.md#installation]read README.md (https://github.com/oskvr37/tiddl/blob/main/README.md#installation)[/]"
        )
