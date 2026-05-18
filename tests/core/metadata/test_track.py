from tiddl.core.api.models import Track
from tiddl.core.metadata import track as track_metadata


def test_track_metadata_preserves_artist_order(monkeypatch, tmp_path):
    captured = {}

    def capture_metadata(path, metadata):
        del path
        captured["artists"] = metadata.artists

    monkeypatch.setattr(track_metadata, "add_flac_metadata", capture_metadata)
    path = tmp_path / "track.flac"

    track_metadata.add_track_metadata(path, make_track())

    assert captured["artists"] == ["Main Artist", "Featured Artist"]


def make_track() -> Track:
    return Track.model_validate(
        {
            "id": 1,
            "title": "Track",
            "duration": 180,
            "replayGain": 0,
            "peak": 1,
            "allowStreaming": True,
            "streamReady": True,
            "adSupportedStreamReady": False,
            "djReady": False,
            "stemReady": False,
            "premiumStreamingOnly": False,
            "trackNumber": 1,
            "volumeNumber": 1,
            "popularity": 1,
            "url": "https://listen.tidal.com/track/1",
            "isrc": "US0000000001",
            "editable": False,
            "explicit": False,
            "audioQuality": "HIGH",
            "audioModes": ["STEREO"],
            "mediaMetadata": {"tags": []},
            "artists": [
                {"id": 1, "name": "Main Artist", "type": "MAIN"},
                {"id": 2, "name": "Featured Artist", "type": "FEATURED"},
            ],
            "artist": {"id": 1, "name": "Main Artist", "type": "MAIN"},
            "album": {"id": 1, "title": "Album"},
        }
    )
