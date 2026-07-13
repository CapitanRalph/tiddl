from pathlib import Path

import tiddl.core.utils.ffmpeg as ff


def test_ffmpeg_exe_env_override(monkeypatch):
    monkeypatch.setenv("TIDDL_FFMPEG", "/custom/ffmpeg")

    assert ff.ffmpeg_exe() == "/custom/ffmpeg"


def test_ffmpeg_exe_resolves_binary(monkeypatch):
    monkeypatch.delenv("TIDDL_FFMPEG", raising=False)

    exe = ff.ffmpeg_exe()

    # bundled imageio-ffmpeg binary, or PATH fallback
    assert exe == "ffmpeg" or Path(exe).is_file()


def test_convert_audio_keep_source(tmp_path, monkeypatch):
    def fake_run(cmd):
        Path(cmd[-1]).write_bytes(b"out")

    monkeypatch.setattr(ff, "run", fake_run)

    source = tmp_path / "track.flac"
    source.write_bytes(b"src")

    output = ff.convert_audio_to_mp3_320(source, keep_source=True)

    assert output == tmp_path / "track.mp3"
    assert output.exists()
    assert source.exists()


def test_convert_audio_removes_source_by_default(tmp_path, monkeypatch):
    def fake_run(cmd):
        Path(cmd[-1]).write_bytes(b"out")

    monkeypatch.setattr(ff, "run", fake_run)

    source = tmp_path / "track.flac"
    source.write_bytes(b"src")

    output = ff.convert_audio_to_wav(source)

    assert output == tmp_path / "track.wav"
    assert not source.exists()
