"""
LECCIÓN 04 — Factory fixtures: probar lógica que consume modelos grandes.

Módulo bajo prueba: tiddl/core/utils/format.py
    format_template() es el corazón de "cómo se llaman tus archivos":
    convierte una plantilla como "{album.artist}/{album.title}/{item.number:02d}"
    más los modelos de la API en una ruta segura para el disco.

Novedades de pytest:
  - Fixtures definidas en conftest.py (make_track, make_album, make_playlist)
    se inyectan SOLO con nombrarlas como parámetro. No hay import.
  - El patrón factory: `make_track(explicit=True)` fabrica un Track válido
    cambiando únicamente lo relevante para el test. Sin esto, cada test
    tendría 30 líneas de datos repetidos.
"""

import pytest

from tiddl.core.utils.format import Explicit, UserFormat, format_template


# --- Los bloques de construcción: Explicit y UserFormat ---------------------
# Son clases pequeñas con __format__ custom: la plantilla decide cómo se ven.


@pytest.mark.parametrize(
    ("valor", "spec", "esperado"),
    [
        (True, "", "E"),  # sin spec: inicial
        (False, "", ""),
        (True, "long", "explicit"),
        (False, "long", ""),  # long: solo marca los explícitos
        (True, "full", "explicit"),
        (False, "full", "clean"),  # full: marca ambos
        (True, "long; upper", "EXPLICIT"),
        (None, "long", ""),  # None = "no se sabe" -> nunca imprime
    ],
)
def test_formatos_de_explicit(valor, spec, esperado):
    assert format(Explicit(valor), spec) == esperado


def test_userformat_muestra_el_spec_solo_si_es_true():
    # Se usa para banderas como {album.master:MASTER}: si el álbum es master
    # imprime "MASTER", si no, nada.
    assert format(UserFormat(True), "MASTER") == "MASTER"
    assert format(UserFormat(False), "MASTER") == ""


# --- format_template: el camino feliz ----------------------------------------


def test_plantilla_de_album(make_track, make_album):
    ruta = format_template(
        "{album.artist}/{album.title}/{item.number:02d} - {item.artist} - {item.title}",
        item=make_track(),
        album=make_album(),
    )

    # `:02d` viene del mini-lenguaje de format() de Python: número a 2 dígitos.
    # El ".*" final es un comodín para buscar el archivo con cualquier extensión.
    assert ruta == "Artista Principal/Mi Album/03 - Artista Principal - Mi Cancion.*"


def test_sin_extension_comodin(make_track):
    ruta = format_template("{item.title}", item=make_track(), with_asterisk_ext=False)
    assert ruta == "Mi Cancion"


def test_sanitiza_cada_segmento(make_track, make_album):
    # Un título con "/" NO debe crear subcarpetas fantasma: se limpia por
    # segmento de la plantilla, no sobre la ruta completa.
    track = make_track(title="What/Ever: Live?")
    ruta = format_template(
        "{album.title}/{item.title}",
        item=track,
        album=make_album(title="Album... Final."),
        with_asterisk_ext=False,
    )

    assert ruta == "Album. Final/WhatEver Live"


def test_segmento_vacio_usa_guion_bajo(make_track):
    # Si el track no es explícito, "{item.explicit}" rinde "" y el segmento
    # quedaría vacío -> el código lo protege con "_" (una ruta "a//b" es inválida).
    ruta = format_template(
        "{item.explicit}/{item.title}",
        item=make_track(explicit=False),
        with_asterisk_ext=False,
    )

    assert ruta == "_/Mi Cancion"


def test_artistas_principales_y_features(make_track):
    from conftest import artist_payload

    track = make_track(
        artists=[
            artist_payload(1, "Zeta", "MAIN"),
            artist_payload(2, "Alfa", "MAIN"),
            artist_payload(3, "Invitado", "FEATURED"),
        ]
    )
    ruta = format_template(
        "{item.artists} feat {item.features}", item=track, with_asterisk_ext=False
    )

    # Los MAIN se ordenan alfabéticamente y se unen con "; "
    assert ruta == "Alfa; Zeta feat Invitado"


def test_calidad_y_master(make_track, make_album):
    # {album.master:MASTER} solo aparece con tag HIRES_LOSSLESS + calidad MAX
    album = make_album(mediaMetadata={"tags": ["HIRES_LOSSLESS"]})
    ruta = format_template(
        "{item.quality} {album.master:MASTER}",
        item=make_track(),
        album=album,
        quality="MAX",
        with_asterisk_ext=False,
    )

    assert ruta == "MAX MASTER"


def test_plantilla_de_playlist(make_track, make_playlist):
    ruta = format_template(
        "{playlist.title}/{playlist.index:02d}. {item.title}",
        item=make_track(),
        playlist=make_playlist(),
        playlist_index=7,
        with_asterisk_ext=False,
    )

    assert ruta == "Mi Playlist/07. Mi Cancion"


def test_fecha_del_album_con_spec_de_datetime(make_track, make_album):
    ruta = format_template(
        "{album.date:%Y} - {album.title}",
        item=make_track(),
        album=make_album(releaseDate="2020-05-01"),
        with_asterisk_ext=False,
    )

    assert ruta == "2020 - Mi Album"


# --- El camino triste ---------------------------------------------------------


def test_campo_inexistente_lanza_attributeerror(make_track):
    # El docstring de format_template lo promete: plantilla inválida ->
    # AttributeError. Un test lo convierte en contrato verificable.
    with pytest.raises(AttributeError):
        format_template("{item.no_existe}", item=make_track())
