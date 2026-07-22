"""
LECCIÓN 02 — Probar errores esperados con pytest.raises.

Módulo bajo prueba: tiddl/cli/utils/resource.py
    TidalResource.from_string() es la PUERTA DE ENTRADA de tiddl: convierte
    lo que el usuario pega (una URL de Tidal o un atajo "track/123") en un
    objeto tipado {type, id}. Tanto la CLI como la web usan esto primero.

Novedades de pytest aquí:
  - `pytest.raises(...)`: un buen test no solo verifica el camino feliz,
    también que las entradas inválidas fallen COMO se espera (ValueError,
    no un crash aleatorio más adelante).
"""

import pytest

from tiddl.cli.utils.resource import TidalResource


@pytest.mark.parametrize(
    ("entrada", "tipo", "id_"),
    [
        # atajos cortos
        ("track/123", "track", "123"),
        ("album/456", "album", "456"),
        ("artist/99", "artist", "99"),
        # URLs completas: urlparse extrae el path y se buscan los segmentos
        ("https://listen.tidal.com/album/456", "album", "456"),
        ("https://tidal.com/browse/track/123", "track", "123"),
        # las playlists usan UUID, no dígitos
        (
            "https://listen.tidal.com/playlist/abc-def-123",
            "playlist",
            "abc-def-123",
        ),
    ],
    ids=lambda v: str(v)[:45],  # `ids` controla el nombre visible de cada caso
)
def test_parseo_valido(entrada: str, tipo: str, id_: str):
    resource = TidalResource.from_string(entrada)

    assert resource.type == tipo
    assert resource.id == id_


def test_str_y_url():
    resource = TidalResource.from_string("track/123")

    # __str__ produce la forma corta; .url reconstruye el link oficial
    assert str(resource) == "track/123"
    assert resource.url == "https://listen.tidal.com/track/123"


def test_tipo_desconocido_lanza_valueerror():
    # `with pytest.raises(X):` = "este bloque DEBE lanzar X".
    # Si no lanza nada (o lanza otra cosa), el test falla.
    with pytest.raises(ValueError):
        TidalResource.from_string("podcast/123")


def test_track_con_id_no_numerico_lanza_valueerror():
    # track/album/video/artist exigen id numérico...
    with pytest.raises(ValueError, match="Invalid resource id"):
        TidalResource.from_string("track/abc")


def test_playlist_acepta_id_no_numerico():
    # ...pero playlist y mix no (usan UUIDs).
    resource = TidalResource.from_string("playlist/no-es-digito")
    assert resource.id == "no-es-digito"


def test_sin_id_lanza_valueerror():
    with pytest.raises(ValueError, match="No resource ID"):
        TidalResource.from_string("track")
