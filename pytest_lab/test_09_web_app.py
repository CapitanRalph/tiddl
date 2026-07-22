"""
LECCIÓN 09 — Probar la API HTTP propia (FastAPI) con TestClient.

Módulo bajo prueba: tiddl/web/app.py
    Es la app de escritorio/web: create_app() arma una API FastAPI local
    (POST /jobs, GET /partials/library, POST /auth/start...) que la UI
    consume con htmx. Además contiene helpers puros (parseo de recursos,
    edición del config.toml, protección contra path traversal).

Qué aprender aquí:
  - `TestClient(app)` habla con la app EN MEMORIA: no levanta uvicorn,
    no abre puertos, no necesita sesión de Tidal.
  - Estrategia por capas: primero los helpers puros (baratos y precisos),
    después endpoints de humo con estado monkeypatcheado.
  - Monkeypatch de estado global: web/app.py hizo
    `from ... import load_auth_data`, así que hay que parchear
    `tiddl.web.app.load_auth_data` (el nombre donde SE USA).
"""

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import tiddl.web.app as web_app
from tiddl.cli.utils.auth import AuthData

# --- 1) Helpers puros: sin app, sin HTTP -------------------------------------


def test_parse_supported_resource_acepta_lo_descargable():
    resource = web_app.parse_supported_resource("https://tidal.com/track/123")
    assert (resource.type, resource.id) == ("track", "123")


@pytest.mark.parametrize(
    "entrada",
    ["", "   ", "esto no es un recurso", "video/123", "artist/9"],
    ids=["vacio", "espacios", "basura", "video-no-soportado", "artist-no-soportado"],
)
def test_parse_supported_resource_rechaza(entrada):
    # La web solo descarga track/album/playlist; todo lo demás -> ValueError
    with pytest.raises(ValueError):
        web_app.parse_supported_resource(entrada)


def test_concurrencia_se_limita_entre_1_y_3():
    assert web_app.clamp_concurrency(0) == 1
    assert web_app.clamp_concurrency(2) == 2
    assert web_app.clamp_concurrency(99) == 3


def test_extension_del_formato_de_salida():
    assert web_app.output_format_extension("mp3_320") == ".mp3"
    assert web_app.output_format_extension("wav") == ".wav"
    assert web_app.output_format_extension("raw") is None


def test_toml_string_escapa_comillas_y_backslashes():
    # Windows: la ruta lleva backslashes que romperían el TOML sin escape.
    assert web_app.toml_string('C:\\Musica\\"dj"') == '"C:\\\\Musica\\\\\\"dj\\""'


# --- 2) Helpers que tocan disco: tmp_path ------------------------------------


def test_guardar_ruta_crea_config_nuevo(tmp_path: Path):
    config_file = tmp_path / "config.toml"

    web_app.save_download_root_config(tmp_path / "Descargas", config_file=config_file)

    contenido = config_file.read_text()
    assert "[download]" in contenido
    assert f'download_path = "{tmp_path / "Descargas"}"' in contenido
    assert f'scan_path = "{tmp_path / "Descargas"}"' in contenido


def test_guardar_ruta_respeta_el_resto_del_config(tmp_path: Path):
    # El archivo ya tiene otras secciones: solo debe tocar [download].
    config_file = tmp_path / "config.toml"
    config_file.write_text(
        "[metadata]\nenable = true\n\n[download]\n"
        'download_path = "/vieja/ruta"\nthreads_count = 4\n'
    )

    web_app.save_download_root_config(tmp_path / "Nueva", config_file=config_file)

    contenido = config_file.read_text()
    assert "enable = true" in contenido  # sección ajena intacta
    assert "threads_count = 4" in contenido  # clave vecina intacta
    assert "/vieja/ruta" not in contenido  # ruta reemplazada
    assert f'download_path = "{tmp_path / "Nueva"}"' in contenido


def test_explorador_bloquea_path_traversal(tmp_path: Path, monkeypatch):
    # El explorador de archivos de la web recibe rutas del navegador:
    # "../../etc" NO debe escapar de la carpeta de descargas.
    (tmp_path / "playlist").mkdir()
    monkeypatch.setattr(web_app.CONFIG.download, "download_path", tmp_path)

    target, relative = web_app.resolve_explorer_path("playlist")
    assert target == tmp_path / "playlist"
    assert relative == "playlist"

    target, relative = web_app.resolve_explorer_path("../../etc")
    assert target == tmp_path  # vuelve a la raíz, no escapa
    assert relative == ""

    target, _ = web_app.resolve_explorer_path("/etc")
    assert target == tmp_path


# --- 3) Endpoints con TestClient ----------------------------------------------


@pytest.fixture
def client_web(monkeypatch, tmp_path: Path) -> TestClient:
    # Aislamos el estado global ANTES de crear la app:
    #  - sin sesión de Tidal guardada
    #  - carpeta de descargas en tmp_path
    monkeypatch.setattr(web_app, "load_auth_data", lambda: AuthData())
    monkeypatch.setattr(web_app.CONFIG.download, "download_path", tmp_path)
    return TestClient(web_app.create_app())


def test_home_responde_html(client_web: TestClient):
    respuesta = client_web.get("/")

    assert respuesta.status_code == 200
    assert "text/html" in respuesta.headers["content-type"]


def test_sin_sesion_ofrece_iniciar_sesion(client_web: TestClient):
    respuesta = client_web.get("/partials/session")

    assert respuesta.status_code == 200
    assert "Iniciar sesión" in respuesta.text


def test_biblioteca_pide_sesion(client_web: TestClient):
    respuesta = client_web.get("/partials/library")

    assert "Inicia sesión" in respuesta.text


def test_crear_job_con_recurso_invalido_no_revienta(client_web: TestClient):
    # El endpoint devuelve el panel de jobs con el aviso, en vez de un 500.
    respuesta = client_web.post("/jobs", data={"resource": "no-valido"})

    assert respuesta.status_code == 200
    assert "recurso válido" in respuesta.text


def test_cancelar_job_inexistente_avisa(client_web: TestClient):
    respuesta = client_web.post("/jobs/nope/cancel")

    assert respuesta.status_code == 200
    assert "No encontramos esa descarga" in respuesta.text
