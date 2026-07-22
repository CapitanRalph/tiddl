"""
LECCIÓN 07 — Fakes por inyección de dependencias + monkeypatch.setenv.

Módulo bajo prueba: tiddl/core/auth/
    El login de tiddl es OAuth2 "device flow" contra auth.tidal.com:
      1. get_device_auth()  -> Tidal da un código y una URL para el navegador.
      2. get_auth(code)     -> se repite hasta que apruebas; devuelve tokens.
      3. refresh_token(...) -> renueva el access_token cuando caduca.

    AuthAPI recibe el cliente HTTP en el constructor:
        AuthAPI(client: AuthClient | None = None)
    Eso es INYECCIÓN DE DEPENDENCIAS: en producción usa el AuthClient real,
    y en tests le pasamos un doble ("fake") que devuelve JSON enlatado.
    Así probamos la lógica de parseo/errores sin tocar la red jamás.
"""

import pytest

from tiddl.core.auth.api import AuthAPI
from tiddl.core.auth.client import get_auth_credentials
from tiddl.core.auth.exceptions import AuthClientError

# JSON como el que responde auth.tidal.com (recortado a lo obligatorio).
USER_JSON = {
    "userId": 42,
    "email": "yo@example.com",
    "countryCode": "CL",
    "fullName": None,
    "firstName": None,
    "lastName": None,
    "nickname": None,
    "username": "yo@example.com",
    "address": None,
    "city": None,
    "postalcode": None,
    "usState": None,
    "phoneNumber": None,
    "birthday": None,
    "channelId": 1,
    "parentId": 0,
    "acceptedEULA": True,
    "created": 1600000000,
    "updated": 1700000000,
    "accountLinkCreated": False,
    "emailVerified": True,
    "newUser": False,
}

AUTH_JSON = {
    "user": USER_JSON,
    "scope": "r_usr w_usr",
    "clientName": "Tiddl",
    "token_type": "Bearer",
    "access_token": "token-de-acceso",
    "expires_in": 604800,
    "user_id": 42,
}


class FakeAuthClient:
    """Doble de prueba: misma interfaz que AuthClient, respuestas enlatadas."""

    def __init__(self) -> None:
        self.llamadas: list[str] = []
        self.pendiente = False  # simula que el usuario aún no aprueba

    def get_device_auth(self):
        self.llamadas.append("device_auth")
        return {
            "deviceCode": "device-123",
            "userCode": "ABCDE",
            "verificationUri": "link.tidal.com",
            "verificationUriComplete": "link.tidal.com/ABCDE",
            "expiresIn": 300,
            "interval": 2,
        }

    def get_auth(self, device_code: str):
        self.llamadas.append(f"auth:{device_code}")
        if self.pendiente:
            # Igual que el cliente real cuando Tidal responde != 200
            raise AuthClientError(
                status=400,
                error="authorization_pending",
                error_description="El usuario aun no aprueba",
            )
        return {**AUTH_JSON, "refresh_token": "token-de-refresco"}

    def refresh_token(self, refresh_token: str):
        self.llamadas.append(f"refresh:{refresh_token}")
        return AUTH_JSON


def test_device_auth_se_parsea_a_modelo():
    fake = FakeAuthClient()
    api = AuthAPI(client=fake)  # <- inyectamos el doble

    device = api.get_device_auth()

    # AuthAPI convierte el dict crudo en un modelo tipado y validado
    assert device.deviceCode == "device-123"
    assert device.interval == 2
    assert fake.llamadas == ["device_auth"]


def test_auth_completa_trae_tokens_y_usuario():
    api = AuthAPI(client=FakeAuthClient())

    auth = api.get_auth("device-123")

    assert auth.access_token == "token-de-acceso"
    assert auth.refresh_token == "token-de-refresco"
    assert auth.user.countryCode == "CL"


def test_autorizacion_pendiente_propaga_el_error():
    fake = FakeAuthClient()
    fake.pendiente = True
    api = AuthAPI(client=fake)

    # `as exc_info` captura la excepción para inspeccionar sus atributos:
    # la web (poll_auth) distingue "authorization_pending" de un fallo real.
    with pytest.raises(AuthClientError) as exc_info:
        api.get_auth("device-123")

    assert exc_info.value.error == "authorization_pending"


def test_refresh_devuelve_access_token_nuevo():
    api = AuthAPI(client=FakeAuthClient())

    auth = api.refresh_token("token-de-refresco")

    assert auth.access_token == "token-de-acceso"
    assert auth.expires_in == 604800


def test_credenciales_se_pueden_inyectar_por_entorno(monkeypatch):
    # monkeypatch.setenv define la variable SOLO durante este test;
    # al terminar, pytest restaura el entorno original.
    monkeypatch.setenv("TIDDL_AUTH", "mi-id;mi-secreto")

    client_id, client_secret = get_auth_credentials()

    assert (client_id, client_secret) == ("mi-id", "mi-secreto")


def test_credenciales_por_defecto_sin_entorno(monkeypatch):
    monkeypatch.delenv("TIDDL_AUTH", raising=False)

    client_id, client_secret = get_auth_credentials()

    # No fijamos el valor exacto (está ofuscado en base64), solo su forma.
    assert client_id and client_secret
    assert ";" not in client_id
