import os
import re
import subprocess
from pathlib import Path


class FFmpegError(RuntimeError):
    pass


def ffmpeg_exe() -> str:
    """Path to the ffmpeg executable.

    Resolution order: `TIDDL_FFMPEG` env override, the static binary bundled
    with `imageio-ffmpeg` (shipped inside the packaged apps), then plain
    `ffmpeg` from PATH.
    """

    env = os.environ.get("TIDDL_FFMPEG")
    if env:
        return env

    try:
        from imageio_ffmpeg import get_ffmpeg_exe

        return get_ffmpeg_exe()
    except Exception:
        return "ffmpeg"


def run(cmd: list[str]) -> subprocess.CompletedProcess:
    """Run a process; raise `FFmpegError` on non-zero exit with stderr."""
    # Force UTF-8 encoding to prevent UnicodeDecodeError on Windows
    r = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",  # Added as a safety net
    )
    if r.returncode != 0:
        raise FFmpegError(f"{cmd[0]} failed (rc={r.returncode}): {r.stderr.strip()}")
    return r


def is_ffmpeg_installed() -> bool:
    """Checks if `ffmpeg` is available (bundled or on PATH)."""

    try:
        run([ffmpeg_exe(), "-version"])
        return True
    except (FileNotFoundError, FFmpegError):
        return False


def _probe_audio_codec(source: Path) -> str:
    """Return the first audio stream's codec name, or "" if unknown.

    Parses `ffmpeg -i` stream info instead of using ffprobe: the bundled
    imageio-ffmpeg binary ships without ffprobe.
    """

    try:
        r = subprocess.run(
            [ffmpeg_exe(), "-hide_banner", "-i", str(source)],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
    except FileNotFoundError:
        return ""

    match = re.search(r"Audio:\s*([A-Za-z0-9_]+)", r.stderr)
    return match.group(1).lower() if match else ""


def convert_to_mp4(source: Path) -> Path:
    output_path = source.with_suffix(".mp4")

    run([ffmpeg_exe(), "-y", "-i", str(source), "-c", "copy", str(output_path)])

    source.unlink()

    return output_path


def convert_audio_to_wav(source: Path, keep_source: bool = False) -> Path:
    output_path = source.with_suffix(".wav")

    run(
        [
            ffmpeg_exe(),
            "-y",
            "-i",
            str(source),
            "-vn",
            "-acodec",
            "pcm_s16le",
            str(output_path),
        ]
    )

    if source != output_path and not keep_source:
        source.unlink()

    return output_path


def convert_audio_to_mp3_320(source: Path, keep_source: bool = False) -> Path:
    output_path = source.with_suffix(".mp3")

    run(
        [
            ffmpeg_exe(),
            "-y",
            "-i",
            str(source),
            "-vn",
            "-codec:a",
            "libmp3lame",
            "-b:a",
            "320k",
            str(output_path),
        ]
    )

    if source != output_path and not keep_source:
        source.unlink()

    return output_path


def extract_flac(source: Path) -> Path:
    """
    Extract FLAC audio from an MP4 container.

    Tidal can serve AAC-in-MP4 for tracks without a lossless master, so the
    input may not actually contain FLAC.
    """

    codec = _probe_audio_codec(source)
    if codec and codec != "flac":
        target = source.with_suffix(".m4a")
        if target != source:
            source.replace(target)
        return target

    target = source.with_suffix(".flac")
    tmp = source.with_suffix(".tmp.flac")

    run([ffmpeg_exe(), "-y", "-i", str(source), "-c", "copy", str(tmp)])

    tmp.replace(target)
    if source != target and source.exists():
        source.unlink()

    return target
