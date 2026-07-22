"""
LECCIÓN 06 — Fabricar datos de prueba realistas (base64, XML, JSON).

Módulo bajo prueba: tiddl/core/utils/parse.py
    Cuando pides un stream, Tidal responde con un "manifiesto" codificado en
    base64. Hay dos dialectos:
      - "BTS" (application/vnd.tidal.bts): un JSON con las URLs directas.
      - DASH (application/dash+xml): un XML MPD con una plantilla de
        segmentos ($Number$) que hay que expandir.
    parse_track_stream() decide además la extensión (.flac / .m4a) según el
    codec. Un error aquí = archivos corruptos o inutilizables.

Qué aprender aquí:
  - No necesitas la API real: basta REPRODUCIR el formato de sus respuestas.
    Construimos los manifiestos a mano igual que los envía Tidal.
  - Helpers de módulo (make_bts_manifest) mantienen los tests legibles.
"""

import json
from base64 import b64encode

import pytest

from tiddl.core.api.models import TrackStream
from tiddl.core.utils.parse import parse_manifest_XML, parse_track_stream


def make_bts_manifest(codecs: str, urls: list[str]) -> str:
    """Codifica un manifiesto estilo BTS igual que lo entrega Tidal."""
    payload = {
        "mimeType": "audio/flac",
        "codecs": codecs,
        "encryptionType": "NONE",
        "urls": urls,
    }
    return b64encode(json.dumps(payload).encode()).decode()


def make_track_stream(
    manifest: str,
    mime: str = "application/vnd.tidal.bts",
    quality: str = "LOSSLESS",
) -> TrackStream:
    return TrackStream.model_validate(
        {
            "trackId": 101,
            "assetPresentation": "FULL",
            "audioMode": "STEREO",
            "audioQuality": quality,
            "manifestMimeType": mime,
            "manifestHash": "hash",
            "manifest": manifest,
        }
    )


DASH_XML = """<?xml version="1.0" encoding="utf-8"?>
<MPD xmlns="urn:mpeg:dash:schema:mpd:2011">
  <Period>
    <AdaptationSet>
      <Representation codecs="mp4a.40.2">
        <SegmentTemplate media="https://cdn.tidal.com/seg_$Number$.mp4">
          <SegmentTimeline>
            <S d="4" r="2"/>
            <S d="4"/>
          </SegmentTimeline>
        </SegmentTemplate>
      </Representation>
    </AdaptationSet>
  </Period>
</MPD>"""


def test_manifiesto_bts_flac():
    stream = make_track_stream(
        make_bts_manifest("flac", ["https://cdn.tidal.com/track.flac"])
    )

    urls, extension = parse_track_stream(stream)

    assert urls == ["https://cdn.tidal.com/track.flac"]
    assert extension == ".flac"


def test_manifiesto_bts_aac_va_a_m4a():
    stream = make_track_stream(
        make_bts_manifest("mp4a.40.2", ["https://cdn.tidal.com/track.mp4"]),
        quality="HIGH",
    )

    _, extension = parse_track_stream(stream)

    assert extension == ".m4a"


def test_codec_desconocido_lanza_valueerror():
    stream = make_track_stream(make_bts_manifest("ogg", ["https://x/y.ogg"]))

    with pytest.raises(ValueError, match="Unknown codecs"):
        parse_track_stream(stream)


def test_manifiesto_dash_expande_segmentos():
    urls, codecs = parse_manifest_XML(DASH_XML)

    assert codecs == "mp4a.40.2"
    # La timeline declara: <S r="2"/> = 1 + 2 repeticiones, más otro <S/> = 4
    # segmentos; el código genera range(0, total+1) -> índices 0..4.
    assert urls == [f"https://cdn.tidal.com/seg_{i}.mp4" for i in range(5)]


def test_manifiesto_dash_via_track_stream():
    manifest = b64encode(DASH_XML.encode()).decode()
    stream = make_track_stream(
        manifest, mime="application/dash+xml", quality="HI_RES_LOSSLESS"
    )

    urls, extension = parse_track_stream(stream)

    assert len(urls) == 5
    assert extension == ".m4a"  # hi-res DASH siempre empaqueta en m4a


def test_xml_sin_representation_lanza_valueerror():
    xml_roto = '<MPD xmlns="urn:mpeg:dash:schema:mpd:2011"><Period/></MPD>'

    with pytest.raises(ValueError, match="Representation element not found"):
        parse_manifest_XML(xml_roto)
