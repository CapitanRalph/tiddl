from tiddl.cli.commands.download.downloader import get_track_quality_fallbacks
from tiddl.core.api.models import Track


def make_track(tags: list[str], audio_quality: str = "HIGH") -> Track:
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
            "audioQuality": audio_quality,
            "audioModes": ["STEREO"],
            "mediaMetadata": {"tags": tags},
            "artists": [{"id": 1, "name": "Artist", "type": "MAIN"}],
            "artist": {"id": 1, "name": "Artist", "type": "MAIN"},
            "album": {"id": 1, "title": "Album"},
        }
    )


def test_max_quality_uses_hires_when_track_supports_it():
    track = make_track(["HIRES_LOSSLESS"], "HI_RES_LOSSLESS")

    assert get_track_quality_fallbacks(track, "HI_RES_LOSSLESS") == [
        "HI_RES_LOSSLESS",
        "LOSSLESS",
        "HIGH",
        "LOW",
    ]


def test_max_quality_falls_back_to_lossless_when_no_hires():
    track = make_track(["LOSSLESS"], "LOSSLESS")

    assert get_track_quality_fallbacks(track, "HI_RES_LOSSLESS") == [
        "LOSSLESS",
        "HIGH",
        "LOW",
    ]


def test_max_quality_falls_back_to_high_when_source_is_not_lossless():
    track = make_track([], "HIGH")

    assert get_track_quality_fallbacks(track, "HI_RES_LOSSLESS") == ["HIGH", "LOW"]


def test_low_quality_does_not_fallback_upward():
    track = make_track(["HIRES_LOSSLESS"], "HI_RES_LOSSLESS")

    assert get_track_quality_fallbacks(track, "LOW") == ["LOW"]
