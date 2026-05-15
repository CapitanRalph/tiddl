from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
import tomllib

PACKAGE_NAME = "tiddl"


def _version_from_pyproject() -> str:
    pyproject = Path(__file__).resolve().parents[1] / "pyproject.toml"
    with pyproject.open("rb") as file:
        data = tomllib.load(file)

    return str(data["project"]["version"])


def _package_version() -> str:
    try:
        return _version_from_pyproject()
    except (FileNotFoundError, KeyError, tomllib.TOMLDecodeError):
        pass

    try:
        return version(PACKAGE_NAME)
    except PackageNotFoundError:
        return "0.0.0"


PACKAGE_VERSION = _package_version()
APP_VERSION = f"v{PACKAGE_VERSION}"

__all__ = ["APP_VERSION", "PACKAGE_VERSION"]
