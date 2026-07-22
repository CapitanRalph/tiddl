"""
LECCIÓN 08 — Mockear la capa HTTP: retries, errores y refresh de token.

Módulo bajo prueba: tiddl/core/api/client.py
    TidalClient.fetch() es el ÚNICO punto por donde tiddl habla con
    api.tidal.com: agrega el header Bearer, cachea en sqlite, reintenta
    respuestas corruptas, renueva el token al recibir 401 y valida el JSON
    contra un modelo Pydantic. Toda la app depende de que esto funcione.

Qué aprender aquí:
  - `monkeypatch.setattr(objeto, "atributo", reemplazo)`: sustituimos
    `client.session.get` por una función nuestra que devuelve respuestas
    falsas. El resto del código corre INTACTO — probamos su lógica real
    (retries, headers, excepciones) sin tocar la red.
  - Una clase FakeResponse mínima: solo imita lo que fetch() usa
    (status_code, from_cache, .json()).
  - El truco de la cola de respuestas: `respuestas.pop(0)` permite guionar
    "primero un 401, después un 200".
"""

from pathlib import Path

import pytest
from pydantic import BaseModel
from requests.exceptions import JSONDecodeError

from tiddl.core.api.client import TidalClient
from tiddl.core.api.exceptions import ApiError


class Saludo(BaseModel):
    """Modelo mínimo para validar la respuesta en los tests."""

    mensaje: str


class FakeResponse:
    def __init__(self, status_code: int, payload):
        self.status_code = status_code
        self.from_cache = False
        self._payload = payload

    def json(self):
        if isinstance(self._payload, Exception):
            raise self._payload
        return self._payload


@pytest.fixture
def client(tmp_path: Path) -> TidalClient:
    # cache_name en tmp_path: el sqlite de requests-cache se crea en la
    # carpeta temporal del test, nunca en tu ~/.tiddl real.
    return TidalClient(token="token-inicial", cache_name=tmp_path / "cache")


def encolar_respuestas(monkeypatch, client: TidalClient, respuestas: list):
    """Reemplaza session.get: cada llamada consume la siguiente respuesta."""
    llamadas = []

    def fake_get(url, params=None, expire_after=None):
        llamadas.append({"url": url, "params": params})
        return respuestas.pop(0)

    monkeypatch.setattr(client.session, "get", fake_get)
    return llamadas


def test_respuesta_200_se_valida_con_el_modelo(monkeypatch, client):
    llamadas = encolar_respuestas(
        monkeypatch, client, [FakeResponse(200, {"mensaje": "hola"})]
    )

    resultado = client.fetch(Saludo, "saludo", {"countryCode": "CL"})

    assert resultado == Saludo(mensaje="hola")
    # y podemos verificar CÓMO se llamó a la API:
    assert llamadas == [
        {
            "url": "https://api.tidal.com/v1/saludo",
            "params": {"countryCode": "CL"},
        }
    ]


def test_error_de_api_lanza_apierror(monkeypatch, client):
    # Tidal responde los errores con este JSON; fetch lo convierte en
    # una excepción tipada que las capas de arriba saben mostrar.
    encolar_respuestas(
        monkeypatch,
        client,
        [
            FakeResponse(
                404,
                {"status": 404, "subStatus": "2001", "userMessage": "Not found"},
            )
        ],
    )

    with pytest.raises(ApiError) as exc_info:
        client.fetch(Saludo, "tracks/999")

    assert exc_info.value.status == 404
    assert str(exc_info.value) == "Not found, 404/2001"


def test_401_renueva_token_y_reintenta(monkeypatch, client):
    # Guion: la primera llamada devuelve 401 (token vencido), el callback
    # on_token_expiry entrega uno nuevo y fetch reintenta solo.
    client.on_token_expiry = lambda: "token-nuevo"
    llamadas = encolar_respuestas(
        monkeypatch,
        client,
        [FakeResponse(401, {}), FakeResponse(200, {"mensaje": "hola"})],
    )

    resultado = client.fetch(Saludo, "saludo")

    assert resultado.mensaje == "hola"
    assert len(llamadas) == 2  # reintentó
    assert client.token == "token-nuevo"
    assert client.session.headers["Authorization"] == "Bearer token-nuevo"


def test_json_corrupto_reintenta_y_luego_falla(monkeypatch, client):
    # fetch duerme RETRY_DELAY segundos entre reintentos; parcheamos sleep
    # para que el test no tarde 8 segundos. Regla: parchear el nombre
    # DONDE SE USA (tiddl.core.api.client.sleep), no time.sleep global.
    monkeypatch.setattr("tiddl.core.api.client.sleep", lambda _: None)

    corrupta = lambda: FakeResponse(  # noqa: E731
        200, JSONDecodeError("Expecting value", "<html>", 0)
    )
    encolar_respuestas(monkeypatch, client, [corrupta() for _ in range(5)])

    with pytest.raises(ApiError, match="does not contain valid json"):
        client.fetch(Saludo, "saludo")


def test_setter_de_token_actualiza_el_header(client):
    client.token = "otro-token"

    assert client.session.headers["Authorization"] == "Bearer otro-token"
