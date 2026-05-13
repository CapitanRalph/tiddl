import typer
from typing_extensions import Annotated

desktop_command = typer.Typer(
    name="desktop",
    help="Run the local desktop-like web app.",
    no_args_is_help=False,
)


def _run_desktop(host: str, port: int, browser: bool) -> None:
    from tiddl.web import run_desktop

    run_desktop(host=host, port=port, browser=browser)


@desktop_command.callback(invoke_without_command=True)
def desktop(
    host: Annotated[
        str,
        typer.Option("--host", help="Host for the local web server."),
    ] = "127.0.0.1",
    port: Annotated[
        int,
        typer.Option("--port", "-p", help="Port for the local web server."),
    ] = 8765,
    browser: Annotated[
        bool,
        typer.Option(
            "--browser",
            help="Run in the browser instead of the native webview window.",
        ),
    ] = False,
):
    """
    Start a local FastAPI + HTMX interface for trusted-device downloads.
    """

    _run_desktop(host=host, port=port, browser=browser)


def main() -> None:
    desktop_command()
