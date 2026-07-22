"""
Fixtures compartidas del laboratorio de pytest.

pytest carga automáticamente cualquier `conftest.py` y hace que sus fixtures
estén disponibles en todos los tests de la carpeta, sin necesidad de imports.

Aquí definimos "factory fixtures": fixtures que devuelven una FUNCIÓN para
fabricar modelos Pydantic de la API de Tidal. Los modelos reales (`Track`,
`Album`, `Playlist`) tienen decenas de campos obligatorios porque replican la
respuesta JSON de api.tidal.com; la factory rellena todo con valores por
defecto razonables y deja que cada test cambie solo lo que le importa:

    def test_algo(make_track):
        track = make_track(title="Otra", explicit=True)
"""

import pytest

from tiddl.core.api.models import Album, Playlist, Track


def artist_payload(id: int = 1, name: str = "Artista Principal", type: str = "MAIN"):
    return {"id": id, "name": name, "type": type}


@pytest.fixture
def make_track():
    def factory(**overrides) -> Track:
        data = {
            "id": 101,
            "title": "Mi Cancion",
            "duration": 240,
            "replayGain": -7.5,
            "peak": 0.98,
            "allowStreaming": True,
            "streamReady": True,
            "adSupportedStreamReady": True,
            "djReady": True,
            "stemReady": False,
            "premiumStreamingOnly": False,
            "trackNumber": 3,
            "volumeNumber": 1,
            "version": None,
            "popularity": 50,
            "copyright": "2026 Sello Discografico",
            "bpm": 120,
            "url": "http://www.tidal.com/track/101",
            "isrc": "USRC12345678",
            "editable": False,
            "explicit": False,
            "audioQuality": "LOSSLESS",
            "audioModes": ["STEREO"],
            "mediaMetadata": {"tags": ["LOSSLESS"]},
            "artist": artist_payload(),
            "artists": [artist_payload()],
            "album": {"id": 555, "title": "Mi Album", "cover": "cover-uuid"},
        }
        data.update(overrides)
        return Track.model_validate(data)

    return factory


@pytest.fixture
def make_album():
    def factory(**overrides) -> Album:
        data = {
            "id": 555,
            "title": "Mi Album",
            "duration": 2400,
            "streamReady": True,
            "adSupportedStreamReady": True,
            "djReady": True,
            "stemReady": False,
            "allowStreaming": True,
            "premiumStreamingOnly": False,
            "numberOfTracks": 10,
            "numberOfVideos": 0,
            "numberOfVolumes": 1,
            "releaseDate": "2020-05-01",
            "copyright": "2020 Sello Discografico",
            "type": "ALBUM",
            "url": "http://www.tidal.com/album/555",
            "cover": "cover-uuid",
            "explicit": False,
            "popularity": 70,
            "audioQuality": "LOSSLESS",
            "audioModes": ["STEREO"],
            "mediaMetadata": {"tags": ["LOSSLESS"]},
            "artist": artist_payload(),
            "artists": [artist_payload()],
        }
        data.update(overrides)
        return Album.model_validate(data)

    return factory


@pytest.fixture
def make_playlist():
    def factory(**overrides) -> Playlist:
        data = {
            "uuid": "11111111-2222-3333-4444-555555555555",
            "title": "Mi Playlist",
            "numberOfTracks": 20,
            "numberOfVideos": 1,
            "creator": {"id": 42},
            "description": "Playlist de prueba",
            "duration": 4800,
            "lastUpdated": "2026-01-15T10:30:00.000+00:00",
            "created": "2025-12-01T08:00:00.000+00:00",
            "type": "USER",
            "publicPlaylist": False,
            "url": "http://www.tidal.com/playlist/1111",
            "popularity": 0,
            "promotedArtists": [],
        }
        data.update(overrides)
        return Playlist.model_validate(data)

    return factory
