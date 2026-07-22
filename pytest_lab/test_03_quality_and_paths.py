"""
LECCIÓN 03 — La fixture `tmp_path`: probar código que toca el disco.

Módulos bajo prueba:
  - tiddl/cli/utils/download.py → get_existing_track_filename() predice la
    extensión (.flac o .m4a) que tendrá un track ya descargado, para que
    `skip_existing` no vuelva a bajar lo que ya tienes.
  - tiddl/cli/utils/path.py → resolve_existing_path_case() reutiliza las
    mayúsculas/minúsculas de carpetas existentes (importante en discos
    case-insensitive como macOS/Windows para no duplicar carpetas).

Novedades de pytest:
  - `tmp_path`: fixture INTEGRADA. Pytest crea una carpeta temporal única
    por test y la limpia después. Nunca escribas tests sobre rutas reales.
  - parametrize con `ids=` legibles para que el reporte se lea como specs.
"""

from pathlib import Path

import pytest

from tiddl.cli.utils.download import get_existing_track_filename
from tiddl.cli.utils.path import find_existing_child_case, resolve_existing_path_case
from tiddl.core.utils.const import track_qualities


# La regla de negocio: solo hay FLAC si tanto la calidad del track en Tidal
# como la calidad pedida son lossless; en cualquier otro caso el archivo es m4a.
@pytest.mark.parametrize(
    ("calidad_track", "calidad_pedida", "extension"),
    [
        ("LOSSLESS", "LOSSLESS", ".flac"),
        ("HI_RES_LOSSLESS", "HI_RES_LOSSLESS", ".flac"),
        ("LOSSLESS", "HIGH", ".m4a"),  # pediste calidad baja -> m4a
        ("HIGH", "HI_RES_LOSSLESS", ".m4a"),  # el track no da para flac
        ("LOW", "LOW", ".m4a"),
    ],
    ids=[
        "lossless+lossless=flac",
        "hires+hires=flac",
        "pedido-bajo=m4a",
        "track-bajo=m4a",
        "low=m4a",
    ],
)
def test_prediccion_de_extension(calidad_track, calidad_pedida, extension):
    resultado = get_existing_track_filename(
        calidad_track, calidad_pedida, Path("Artista/Album/01 - Cancion")
    )

    assert resultado == Path(f"Artista/Album/01 - Cancion{extension}")


def test_mapa_de_calidades_cli_a_api():
    # La CLI habla en minúsculas ("high"), la API de Tidal en literales
    # ("LOSSLESS"). Este dict es el puente — fijarlo en un test evita que
    # un cambio accidental degrade la calidad de descarga de todos.
    assert track_qualities == {
        "low": "LOW",
        "normal": "HIGH",
        "high": "LOSSLESS",
        "max": "HI_RES_LOSSLESS",
    }


def test_reutiliza_mayusculas_existentes(tmp_path: Path):
    # tmp_path llega como pathlib.Path a una carpeta vacía y desechable.
    (tmp_path / "Artista" / "Mi Album").mkdir(parents=True)

    resultado = resolve_existing_path_case(
        tmp_path, Path("artista/mi album/01 - cancion.flac")
    )

    # Encuentra "Artista" y "Mi Album" ya creados (ignorando mayúsculas)
    # y los reutiliza; el archivo final aún no existe, así que queda tal cual.
    assert resultado == tmp_path / "Artista" / "Mi Album" / "01 - cancion.flac"


def test_ruta_nueva_se_usa_tal_cual(tmp_path: Path):
    resultado = resolve_existing_path_case(tmp_path, Path("Nueva/Carpeta"))
    assert resultado == tmp_path / "Nueva" / "Carpeta"


def test_ruta_absoluta_esta_prohibida(tmp_path: Path):
    with pytest.raises(ValueError, match="must not be absolute"):
        resolve_existing_path_case(tmp_path, Path("/etc"))


def test_busqueda_de_hijo_ignora_mayusculas(tmp_path: Path):
    # Lección aprendida al correr esto por primera vez: el disco de macOS es
    # case-INsensitive, así que crear "rock" y "Rock" a la vez falla con
    # FileExistsError. Los tests también te enseñan cosas del sistema.
    (tmp_path / "Rock").mkdir()

    assert find_existing_child_case(tmp_path, "Rock") == "Rock"
    assert find_existing_child_case(tmp_path, "ROCK") == "Rock"
    assert find_existing_child_case(tmp_path, "jazz") is None
