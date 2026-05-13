import asyncio
import os
import shutil
from logging import getLogger
from pathlib import Path
from tempfile import NamedTemporaryFile

import aiofiles
import aiohttp

from tiddl.cli.config import VIDEOS_FILTER_LITERAL, ATMOS_FILTER_LITERAL
from tiddl.cli.utils.download import get_existing_track_filename
from tiddl.cli.utils.path import resolve_existing_path_case
from tiddl.core.api import ApiError, TidalAPI
from tiddl.core.api.models import StreamVideoQuality, Track, TrackQuality, Video
from tiddl.core.utils import parse_track_stream, parse_video_stream
from tiddl.core.utils.const import (
    TRACK_QUALITY_LITERAL,
    VIDEO_QUALITY_LITERAL,
    track_qualities,
    video_qualities,
)
from tiddl.core.utils.ffmpeg import convert_to_mp4, extract_flac

from .output import RichOutput

log = getLogger(__name__)

CHUNK_SIZE = 1024**2

track_qualities_color: dict[TrackQuality, str] = {
    "LOW": "[gray]96 kbps",
    "HIGH": "[gray]320 kbps",
    "LOSSLESS": "[cyan]",
    "HI_RES_LOSSLESS": "[yellow]",
}

video_qualities_color: dict[StreamVideoQuality, str] = {
    "LOW": "[gray]360p",
    "MEDIUM": "[cyan]720p",
    "HIGH": "[yellow]1080p",
}


def get_track_quality_fallbacks(
    item: Track, requested_quality: TrackQuality
) -> list[TrackQuality]:
    tags = item.mediaMetadata.tags
    has_hires = "HIRES_LOSSLESS" in tags
    has_lossless = has_hires or "LOSSLESS" in tags or item.audioQuality in [
        "LOSSLESS",
        "HI_RES_LOSSLESS",
    ]

    match requested_quality:
        case "HI_RES_LOSSLESS":
            if has_hires:
                return ["HI_RES_LOSSLESS", "LOSSLESS", "HIGH", "LOW"]
            if has_lossless:
                return ["LOSSLESS", "HIGH", "LOW"]
            return ["HIGH", "LOW"]

        case "LOSSLESS":
            if has_lossless:
                return ["LOSSLESS", "HIGH", "LOW"]
            return ["HIGH", "LOW"]

        case "HIGH":
            return ["HIGH", "LOW"]

        case "LOW":
            return ["LOW"]


class Downloader:
    api: TidalAPI
    rich_output: RichOutput
    semaphore: asyncio.Semaphore
    track_quality: TrackQuality
    video_quality: StreamVideoQuality
    videos_filter: VIDEOS_FILTER_LITERAL
    skip_existing: bool
    download_path: Path
    scan_path: Path
    match_existing_path_case: bool
    dolby_atmos_filter: ATMOS_FILTER_LITERAL

    def __init__(
        self,
        tidal_api: TidalAPI,
        threads_count: int,
        rich_output: RichOutput,
        track_quality: TRACK_QUALITY_LITERAL,
        video_quality: VIDEO_QUALITY_LITERAL,
        videos_filter: VIDEOS_FILTER_LITERAL,
        skip_existing: bool,
        download_path: Path,
        scan_path: Path,
        match_existing_path_case: bool = False,
        dolby_atmos_filter: ATMOS_FILTER_LITERAL = "none",
    ) -> None:
        self.api = tidal_api
        self.rich_output = rich_output
        self.semaphore = asyncio.Semaphore(threads_count)
        self.track_quality = track_qualities[track_quality]
        self.video_quality = video_qualities[video_quality]
        self.videos_filter = videos_filter
        self.skip_existing = skip_existing
        self.download_path = download_path
        self.scan_path = scan_path
        self.match_existing_path_case = match_existing_path_case
        self.dolby_atmos_filter = dolby_atmos_filter

    def get_path(self, base_path: Path, relative_path: Path) -> Path:
        if self.match_existing_path_case:
            return resolve_existing_path_case(base_path, relative_path)

        return base_path / relative_path

    async def download(
        self, item: Track | Video, file_path: Path
    ) -> tuple[Path | None, bool]:
        """
        returns
        - Path `item_path` path of existing/downloaded item
        - bool `was_downloaded`
        """

        if not item.allowStreaming:
            self.rich_output.console.print(
                f"[red]Can't stream[/] {item.title} ({item.id})"
            )
            return None, False

        if isinstance(item, Track):
            filename = get_existing_track_filename(
                item.audioQuality, self.track_quality, file_path
            )
            existing_file_path = self.get_path(self.scan_path, filename)
            vibrant_color = item.album.vibrantColor

        elif isinstance(item, Video):
            filename = file_path.with_suffix(".mp4")
            existing_file_path = self.get_path(self.scan_path, filename)
            vibrant_color = item.vibrantColor

        vibrant_color = vibrant_color or "gray"

        log.debug(f"{file_path=}, {filename=}, {existing_file_path=}")

        result_message = "[green]Downloaded"

        if existing_file_path.exists():
            result_message = "[cyan]Overwrited"

            if self.skip_existing:
                self.rich_output.show_item_result(
                    result_message="[yellow]Exists",
                    item_description=f"[{vibrant_color}]{item.title}",
                    item_path=existing_file_path,
                )
                return existing_file_path, False

        elif (isinstance(item, Video) and self.videos_filter == "none") or (
            isinstance(item, Track) and self.videos_filter == "only"
        ):
            log.debug(f"skipping {item.id} due to {self.videos_filter=}")
            self.rich_output.console.print(
                f"Skipping '{item.title}' due to video filter set to '{self.videos_filter}'"
            )
            return None, False

        should_extract_flac = False

        async with self.semaphore:
            if isinstance(item, Track):
                stream = None
                stream_error: ApiError | None = None

                for quality in get_track_quality_fallbacks(item, self.track_quality):
                    try:
                        stream = self.api.get_track_stream(
                            track_id=item.id, quality=quality
                        )
                        if quality != self.track_quality:
                            self.rich_output.console.print(
                                f"[yellow]Fallback[/] {item.title}: {self.track_quality} -> {quality}"
                            )
                        break
                    except ApiError as e:
                        stream_error = e
                        log.warning(f"{item.id=} {quality=} {e=}")

                if stream is None:
                    log.error(f"{item.id=} {stream_error=}")
                    self.rich_output.console.print(
                        f"[red]Error [{vibrant_color}]{item.title}[/] - {stream_error.user_message if stream_error else 'No stream available'}"
                    )
                    return None, False

                log.debug(
                    f"{stream.trackId=}, {stream.audioQuality=}, {stream.audioMode=}"
                )

                if (
                    self.dolby_atmos_filter == "none"
                    and stream.audioMode == "DOLBY_ATMOS"
                ) or (
                    self.dolby_atmos_filter == "only"
                    and stream.audioMode == "STEREO"
                ):
                    self.rich_output.console.print(
                        f"[blue]Skipping[/] [gray]{item.title}[/] [blue]due to Dolby Atmos filter[/] {self.dolby_atmos_filter}"
                    )
                    return None, False

                urls, _ = parse_track_stream(stream)
                download_path = self.get_path(self.download_path, filename)

                quality_string = track_qualities_color[stream.audioQuality]

                if (
                    stream.audioQuality in ["HI_RES_LOSSLESS", "LOSSLESS"]
                    and stream.audioMode == "STEREO"
                ):
                    quality_string = f"{quality_string} {stream.bitDepth}-bit, {(stream.sampleRate or 0) / 1000:.1f} kHz"
                    should_extract_flac = True
                else:
                    download_path = download_path.with_suffix(".m4a")

                    if stream.audioMode == "DOLBY_ATMOS":
                        quality_string = "[blue]Dolby Atmos[/]"

            elif isinstance(item, Video):
                stream = self.api.get_video_stream(
                    video_id=item.id, quality=self.video_quality
                )

                urls, ext = parse_video_stream(stream), ".ts"
                download_path = self.get_path(self.download_path, filename).with_suffix(
                    ext
                )
                quality_string = video_qualities_color[stream.videoQuality]

            task_id = self.rich_output.download_start(
                f"[{vibrant_color}]{item.title} {quality_string}"
            )

            download_path.parent.mkdir(exist_ok=True, parents=True)
            tmp_name: str | None = None

            # TODO shouldnt session be reused instead of
            # creating new one on every download?

            try:
                with NamedTemporaryFile(
                    "wb", delete=False, dir=download_path.parent
                ) as tmp:
                    tmp_name = tmp.name

                async with aiohttp.ClientSession(trust_env=True) as session:
                    async with aiofiles.open(tmp_name, "wb") as f:
                        for url in urls:
                            async with session.get(url) as resp:
                                if resp.status >= 400:
                                    body = await resp.text()
                                    log.error(
                                        "download http error item_id=%s title=%s status=%s url=%s body=%s",
                                        item.id,
                                        item.title,
                                        resp.status,
                                        url,
                                        body[:500],
                                    )
                                    resp.raise_for_status()

                                async for chunk in resp.content.iter_chunked(
                                    CHUNK_SIZE
                                ):
                                    await f.write(chunk)
                                    self.rich_output.download_advance(
                                        task_id, size=len(chunk)
                                    )

                shutil.move(tmp_name, download_path)
                tmp_name = None

                try:
                    download_path.chmod(0o644)
                except OSError:
                    pass

                try:
                    if isinstance(item, Track) and should_extract_flac:
                        download_path = extract_flac(download_path)
                    elif isinstance(item, Video):
                        download_path = convert_to_mp4(download_path)
                except Exception as exc:
                    log.exception(
                        "postprocess failed item_id=%s title=%s path=%s should_extract_flac=%s",
                        item.id,
                        item.title,
                        download_path,
                        should_extract_flac,
                    )
                    raise exc

                task = self.rich_output.download_finish(
                    task_id=task_id,
                )

                self.rich_output.show_item_result(
                    result_message=result_message,
                    item_description=task.description,
                    item_path=download_path,
                )

            except Exception:
                if tmp_name and os.path.exists(tmp_name):
                    try:
                        os.unlink(tmp_name)
                    except OSError:
                        log.warning("could not remove temp download %s", tmp_name)
                try:
                    self.rich_output.download_finish(task_id=task_id)
                except Exception:
                    pass
                log.exception(
                    "download failed item_id=%s title=%s target=%s",
                    item.id,
                    item.title,
                    download_path,
                )
                raise

            return download_path, True
