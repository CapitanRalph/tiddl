"""
LECCIÓN 05 — Probar la configuración: defaults, TOML y validación.

Módulo bajo prueba: tiddl/cli/config.py
    Todo tiddl se gobierna por un `config.toml` (en ~/.tiddl/) que se parsea
    a un modelo Pydantic `Config`. Aquí es donde Pydantic brilla: valores
    inválidos fallan al CARGAR, no a mitad de una descarga.

Qué aprender aquí:
  - Los modelos Pydantic se prueban en 3 frentes: defaults, parseo de
    entrada real (TOML) y rechazo de valores inválidos (ValidationError).
  - `load_config_file` acepta la ruta como parámetro: eso se llama diseño
    "testeable" — le pasamos un archivo en tmp_path en vez de tocar ~/.tiddl.
  - OJO: importar tiddl.cli.config ejecuta `CONFIG = load_config_file(...)`
    sobre TU config real. Es solo lectura, pero es un buen ejemplo de por qué
    los efectos colaterales al importar complican el testing.
"""

from pathlib import Path

import pytest
from pydantic import ValidationError

from tiddl.cli.config import (
    DEFAULT_DOWNLOAD_PATH,
    DEFAULT_REKORDBOX_TEMPLATE,
    Config,
    load_config_file,
)


def test_defaults_sensatos():
    config = Config()

    assert config.download.track_quality == "high"
    assert config.download.skip_existing is True
    assert config.download.download_path == DEFAULT_DOWNLOAD_PATH
    assert config.metadata.enable is True


def test_plantillas_vacias_heredan_la_default():
    # model_post_init rellena track/album/... con `default` si están vacías.
    config = Config()

    assert config.templates.default == DEFAULT_REKORDBOX_TEMPLATE
    assert config.templates.track == DEFAULT_REKORDBOX_TEMPLATE
    assert config.templates.album == DEFAULT_REKORDBOX_TEMPLATE
    # las que traen su propio valor no se pisan
    assert config.templates.video == "video/{item.artist}/{item.title_version}"


def test_archivo_inexistente_devuelve_defaults(tmp_path: Path):
    config = load_config_file(tmp_path / "no_existe.toml")

    assert config == Config()


def test_carga_toml_real(tmp_path: Path):
    # Escribimos un config.toml de verdad en la carpeta temporal.
    config_file = tmp_path / "config.toml"
    config_file.write_text(
        "\n".join(
            [
                "[download]",
                'track_quality = "max"',
                f'download_path = "{tmp_path / "Musica"}"',
                "",
                "[templates]",
                'default = "{item.artist} - {item.title}"',
            ]
        )
    )

    config = load_config_file(config_file)

    assert config.download.track_quality == "max"
    assert config.download.download_path == tmp_path / "Musica"
    # scan_path sigue a download_path cuando no se define aparte
    assert config.download.scan_path == tmp_path / "Musica"
    # y la default nueva se propaga a las plantillas vacías
    assert config.templates.track == "{item.artist} - {item.title}"


def test_download_path_expande_usuario():
    # El validador `str_to_path` convierte "~" en tu home y normaliza.
    config = Config.model_validate({"download": {"download_path": "~/MusicaTest"}})

    assert config.download.download_path.is_absolute()
    assert config.download.download_path == (Path.home() / "MusicaTest").resolve()


def test_calidad_invalida_lanza_validationerror():
    # track_quality es un Literal["low","normal","high","max"]: cualquier
    # otra cosa revienta al cargar el config, con un mensaje claro.
    with pytest.raises(ValidationError):
        Config.model_validate({"download": {"track_quality": "ultra"}})


def test_default_template_vacia_esta_prohibida():
    with pytest.raises(ValidationError, match="Default template cannot be empty"):
        Config.model_validate({"templates": {"default": ""}})
