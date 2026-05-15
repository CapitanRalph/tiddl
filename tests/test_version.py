from pathlib import Path
import tomllib

from tiddl.version import APP_VERSION, PACKAGE_VERSION


def test_version_comes_from_pyproject():
    pyproject = Path(__file__).resolve().parents[1] / "pyproject.toml"
    with pyproject.open("rb") as file:
        version = tomllib.load(file)["project"]["version"]

    assert PACKAGE_VERSION == version
    assert APP_VERSION == f"v{version}"
