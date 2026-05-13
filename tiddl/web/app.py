import asyncio
import re
import socket
import threading
import time
import webbrowser
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal
from uuid import uuid4

from fastapi import FastAPI, Form, HTTPException
from fastapi.responses import HTMLResponse
import uvicorn

from tiddl.cli.config import CONFIG, TRACK_QUALITY_LITERAL, VIDEO_QUALITY_LITERAL
from tiddl.cli.commands.download.downloader import Downloader
from tiddl.cli.const import APP_PATH
from tiddl.cli.utils.auth import AuthData, load_auth_data, save_auth_data
from tiddl.cli.utils.resource import TidalResource
from tiddl.core.api import TidalAPI, TidalClient, ApiError
from tiddl.core.api.models import Album, AlbumItemsCredits, Track, Video
from tiddl.core.auth import AuthAPI, AuthClientError
from tiddl.core.metadata import Cover, add_track_metadata, add_video_metadata
from tiddl.core.utils.const import track_qualities, video_qualities
from tiddl.core.utils.ffmpeg import convert_audio_to_mp3_320, convert_audio_to_wav
from tiddl.core.utils.format import format_template

ResourceKind = Literal["track", "album", "playlist"]
AudioOutputFormat = Literal["raw", "wav", "mp3_320"]


@dataclass
class LoginAttempt:
    id: str
    uri: str
    expires_at: float
    status: str = "pending"
    message: str = "Waiting for authorization"


@dataclass
class JobResult:
    title: str
    path: str
    status: str


@dataclass
class DownloadJob:
    id: str
    resource: str
    output_format: AudioOutputFormat = "raw"
    concurrency: int = 3
    track_quality: TRACK_QUALITY_LITERAL = "high"
    video_quality: VIDEO_QUALITY_LITERAL = "fhd"
    status: str = "queued"
    message: str = "Queued"
    total: int = 0
    completed: int = 0
    bytes_downloaded: int = 0
    results: list[JobResult] = field(default_factory=list)
    active_items: dict[int, str] = field(default_factory=dict)
    terminal: list[str] = field(default_factory=list)
    error: str = ""
    created_at: float = field(default_factory=time.time)


class WebState:
    def __init__(self) -> None:
        self.auth_api = AuthAPI()
        self.login_attempt: LoginAttempt | None = None
        self.jobs: dict[str, DownloadJob] = {}
        self.lock = threading.Lock()

    def authenticated(self) -> bool:
        auth_data = load_auth_data()
        return bool(auth_data.token and auth_data.refresh_token)

    def api(self) -> TidalAPI:
        auth_data = ensure_fresh_auth(self.auth_api)

        if not auth_data.token or not auth_data.user_id or not auth_data.country_code:
            raise HTTPException(status_code=401, detail="Not signed in")

        refresh_token = auth_data.refresh_token

        def on_token_expiry() -> str | None:
            if not refresh_token:
                return None

            refreshed = self.auth_api.refresh_token(refresh_token)
            auth_data.token = refreshed.access_token
            auth_data.expires_at = refreshed.expires_in + int(time.time())
            save_auth_data(auth_data)
            return refreshed.access_token

        client = TidalClient(
            token=auth_data.token,
            cache_name=APP_PATH / "api_cache",
            omit_cache=False,
            on_token_expiry=on_token_expiry,
        )

        return TidalAPI(client, auth_data.user_id, auth_data.country_code)


class WebConsole:
    def __init__(self, job: DownloadJob) -> None:
        self.job = job

    def print(self, *values: Any, **_: Any) -> None:
        message = " ".join(str(value) for value in values)
        self.job.message = strip_rich(message)
        self.job.terminal.append(self.job.message)
        self.job.terminal = self.job.terminal[-40:]


@dataclass
class WebTask:
    description: str


class WebOutput:
    def __init__(self, job: DownloadJob) -> None:
        self.job = job
        self.console = WebConsole(job)
        self.tasks: dict[int, WebTask] = {}
        self.next_task_id = 1

    def total_increment(self, count: float = 1) -> None:
        self.job.total += int(count)

    def download_start(self, description: str) -> int:
        task_id = self.next_task_id
        self.next_task_id += 1
        clean_description = strip_rich(description)
        self.tasks[task_id] = WebTask(description=clean_description)
        self.job.active_items[task_id] = clean_description
        self.job.status = "running"
        self.job.message = clean_description
        self.job.terminal.append(f"Starting {clean_description}")
        return task_id

    def download_advance(self, task_id: int, size: float) -> None:
        self.job.bytes_downloaded += int(size)

    def download_finish(self, task_id: int) -> WebTask:
        task = self.tasks.pop(task_id)
        self.job.active_items.pop(task_id, None)
        self.job.completed += 1
        return task

    def show_item_result(
        self, result_message: str, item_description: str, item_path: Path | None
    ) -> None:
        self.job.results.append(
            JobResult(
                title=strip_rich(item_description),
                path=str(item_path) if item_path else "",
                status=strip_rich(result_message),
            )
        )
        self.job.terminal.append(
            f"{strip_rich(result_message)} {strip_rich(item_description)}"
        )
        self.job.terminal = self.job.terminal[-40:]

    def update_last_result_path(self, path: Path) -> None:
        if not self.job.results:
            return

        self.job.results[-1].path = str(path)

    def show_item_error(self, item: Track | Video, error: Exception) -> None:
        message = f"{item.title}: {error}"
        self.job.results.append(
            JobResult(title=item.title, path="", status=f"Error {error}")
        )
        self.job.terminal.append(message)
        self.job.terminal = self.job.terminal[-40:]


@dataclass
class MetadataPayload:
    date: str = ""
    artist: str = ""
    credits: list[AlbumItemsCredits.ItemWithCredits.CreditsEntry] = field(
        default_factory=list
    )
    cover: Cover | None = None


def create_app(state: WebState | None = None) -> FastAPI:
    web_state = state or WebState()
    app = FastAPI(title="tiddl desktop")

    @app.get("/", response_class=HTMLResponse)
    def home() -> str:
        return page()

    @app.get("/partials/session", response_class=HTMLResponse)
    def session_panel() -> str:
        return render_session_panel(web_state)

    @app.post("/auth/start", response_class=HTMLResponse)
    def auth_start() -> str:
        device_auth = web_state.auth_api.get_device_auth()
        uri = f"https://{device_auth.verificationUriComplete}"
        attempt = LoginAttempt(
            id=uuid4().hex,
            uri=uri,
            expires_at=time.time() + device_auth.expiresIn,
        )

        with web_state.lock:
            web_state.login_attempt = attempt

        thread = threading.Thread(
            target=poll_auth,
            args=(web_state, attempt, device_auth.deviceCode, device_auth.interval),
            daemon=True,
        )
        thread.start()
        webbrowser.open(uri)
        return render_login_attempt(attempt)

    @app.post("/auth/refresh", response_class=HTMLResponse)
    def auth_refresh() -> str:
        ensure_fresh_auth(web_state.auth_api, force=True)
        return render_session_panel(web_state)

    @app.post("/auth/logout", response_class=HTMLResponse)
    def auth_logout() -> str:
        save_auth_data(AuthData())
        return render_session_panel(web_state)

    @app.get("/auth/status", response_class=HTMLResponse)
    def auth_status() -> str:
        attempt = web_state.login_attempt
        if not attempt:
            return render_session_panel(web_state)

        if attempt.status == "complete":
            return render_session_panel(web_state)

        return render_login_attempt(attempt)

    @app.get("/partials/library", response_class=HTMLResponse)
    def library(kind: ResourceKind = "playlist") -> str:
        if not web_state.authenticated():
            return '<p class="muted">Sign in to load your Tidal favorites.</p>'

        api = web_state.api()
        return render_library(api, kind)

    @app.get("/partials/preview", response_class=HTMLResponse)
    def preview(resource: str) -> str:
        api = web_state.api()
        try:
            tidal_resource = parse_supported_resource(resource)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

        return render_preview(api, tidal_resource)

    @app.post("/jobs", response_class=HTMLResponse)
    def create_job(
        resource: str = Form(...),
        output_format: AudioOutputFormat = Form("raw"),
        concurrency: int = Form(3),
        track_quality: TRACK_QUALITY_LITERAL = Form("high"),
        video_quality: VIDEO_QUALITY_LITERAL = Form("fhd"),
    ) -> str:
        api = web_state.api()
        try:
            tidal_resource = parse_supported_resource(resource.strip())
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

        concurrency = clamp_concurrency(concurrency)

        job = DownloadJob(
            id=uuid4().hex[:8],
            resource=str(tidal_resource),
            output_format=output_format,
            concurrency=concurrency,
            track_quality=track_quality,
            video_quality=video_quality,
        )
        with web_state.lock:
            web_state.jobs[job.id] = job

        thread = threading.Thread(
            target=run_download_job,
            args=(
                api,
                tidal_resource,
                job,
                output_format,
                concurrency,
                track_quality,
                video_quality,
            ),
            daemon=True,
        )
        thread.start()
        return render_jobs(web_state)

    @app.get("/partials/jobs", response_class=HTMLResponse)
    def jobs() -> str:
        return render_jobs(web_state)

    @app.get("/partials/status", response_class=HTMLResponse)
    def status() -> str:
        return render_status(web_state)

    return app


def poll_auth(
    state: WebState, attempt: LoginAttempt, device_code: str, interval: int
) -> None:
    while time.time() < attempt.expires_at:
        time.sleep(interval)

        try:
            auth = state.auth_api.get_auth(device_code)
        except AuthClientError as exc:
            if exc.error == "authorization_pending":
                remaining = max(0, int(attempt.expires_at - time.time()))
                attempt.message = f"Waiting for authorization ({remaining}s left)"
                continue

            attempt.status = "failed"
            attempt.message = exc.error_description or exc.error or "Authorization failed"
            return

        save_auth_data(
            AuthData(
                token=auth.access_token,
                refresh_token=auth.refresh_token,
                expires_at=auth.expires_in + int(time.time()),
                user_id=str(auth.user_id),
                country_code=auth.user.countryCode,
            )
        )
        attempt.status = "complete"
        attempt.message = "Signed in"
        return

    attempt.status = "expired"
    attempt.message = "Authorization expired"


def ensure_fresh_auth(auth_api: AuthAPI, force: bool = False) -> AuthData:
    auth_data = load_auth_data()

    if not auth_data.refresh_token:
        return auth_data

    expires_soon = time.time() >= auth_data.expires_at - 600
    if not force and auth_data.token and not expires_soon:
        return auth_data

    refreshed = auth_api.refresh_token(auth_data.refresh_token)
    auth_data.token = refreshed.access_token
    auth_data.expires_at = refreshed.expires_in + int(time.time())
    save_auth_data(auth_data)
    return auth_data


def parse_supported_resource(resource: str) -> TidalResource:
    tidal_resource = TidalResource.from_string(resource)

    if tidal_resource.type not in ("track", "album", "playlist"):
        raise ValueError("La aplicacion soporta tracks, albumes y playlists.")

    return tidal_resource


def clamp_concurrency(value: int) -> int:
    return max(1, min(3, value))


def run_download_job(
    api: TidalAPI,
    resource: TidalResource,
    job: DownloadJob,
    output_format: AudioOutputFormat,
    concurrency: int,
    track_quality: TRACK_QUALITY_LITERAL,
    video_quality: VIDEO_QUALITY_LITERAL,
) -> None:
    try:
        job.status = "running"
        job.message = "Preparing download"
        job.terminal.append(
            f"Queued {resource} as {output_format.upper()} with {concurrency} workers"
        )
        asyncio.run(
            download_resource(
                api,
                resource,
                job,
                output_format,
                concurrency,
                track_quality,
                video_quality,
            )
        )
        if job.status != "failed":
            job.status = "done"
            job.message = "Finished"
    except Exception as exc:
        job.status = "failed"
        job.error = str(exc)
        job.message = str(exc)
        job.terminal.append(f"Error: {exc}")


async def download_resource(
    api: TidalAPI,
    resource: TidalResource,
    job: DownloadJob,
    output_format: AudioOutputFormat,
    concurrency: int,
    track_quality: TRACK_QUALITY_LITERAL,
    video_quality: VIDEO_QUALITY_LITERAL,
) -> None:
    output = WebOutput(job)
    downloader = Downloader(
        tidal_api=api,
        threads_count=clamp_concurrency(concurrency),
        rich_output=output,  # type: ignore[arg-type]
        track_quality=track_quality,
        video_quality=video_quality,
        videos_filter=CONFIG.download.videos_filter,
        skip_existing=CONFIG.download.skip_existing,
        download_path=CONFIG.download.download_path,
        scan_path=CONFIG.download.scan_path,
        match_existing_path_case=CONFIG.download.match_existing_path_case,
        dolby_atmos_filter=CONFIG.download.atmos_filter,
    )

    async def handle_item(
        item: Track | Video,
        file_path: str,
        metadata: MetadataPayload | None = None,
    ) -> tuple[Path | None, Track | Video]:
        output.total_increment()
        metadata = metadata or MetadataPayload()

        try:
            path, was_downloaded = await downloader.download(item, Path(file_path))
        except Exception as exc:
            output.show_item_error(item, exc)
            raise

        if not path:
            return path, item

        if isinstance(item, Track) and was_downloaded:
            try:
                path = convert_track_output(path, output_format)
                output.update_last_result_path(path)
            except Exception as exc:
                output.show_item_error(item, exc)
                raise

        if not (CONFIG.metadata.enable and was_downloaded):
            return path, item

        if isinstance(item, Track):
            if output_format != "raw":
                return path, item

            if not metadata.cover and item.album.cover and CONFIG.metadata.cover:
                metadata.cover = Cover(item.album.cover)

            if metadata.cover and metadata.cover.data is None:
                metadata.cover.fetch_data()

            add_track_metadata(
                path=path,
                track=item,
                album_artist=metadata.artist,
                cover_data=metadata.cover.data if metadata.cover else None,
                date=metadata.date,
                credits_contributors=metadata.credits,
            )
        else:
            add_video_metadata(path=path, video=item)

        return path, item

    match resource.type:
        case "track":
            track = api.get_track(resource.id)
            album = api.get_album(track.album.id)
            await handle_item(
                track,
                format_template(
                    CONFIG.templates.track,
                    item=track,
                    album=album,
                    quality=get_item_quality(track, track_quality, video_quality),
                ),
                MetadataPayload(
                    date=str(album.releaseDate or ""),
                    artist=album.artist.name if album.artist else "",
                    cover=Cover(album.cover) if album.cover and CONFIG.metadata.cover else None,
                ),
            )

        case "album":
            album = api.get_album(resource.id)
            await download_album(
                api, album, handle_item, track_quality, video_quality
            )

        case "playlist":
            playlist = api.get_playlist(resource.id)
            offset = 0
            playlist_index = 0
            futures = []

            while True:
                items = api.get_playlist_items(resource.id, offset=offset)
                for playlist_item in items.items:
                    playlist_index += 1
                    item = playlist_item.item
                    album = None
                    if isinstance(item, Track) and "{album" in CONFIG.templates.playlist:
                        try:
                            album = api.get_album(item.album.id)
                        except ApiError:
                            album = None

                    futures.append(
                        handle_item(
                            item,
                            format_template(
                                CONFIG.templates.playlist,
                                item=item,
                                album=album,
                                playlist=playlist,
                                playlist_index=playlist_index,
                                quality=get_item_quality(
                                    item, track_quality, video_quality
                                ),
                            ),
                        )
                    )

                offset += items.limit
                if offset >= items.totalNumberOfItems:
                    break

            await asyncio.gather(*futures)

        case _:
            raise ValueError(f"Unsupported resource type: {resource.type}")


async def download_album(
    api: TidalAPI,
    album: Album,
    handle_item: Any,
    track_quality: TRACK_QUALITY_LITERAL,
    video_quality: VIDEO_QUALITY_LITERAL,
) -> None:
    offset = 0
    futures = []
    cover = Cover(album.cover, size=CONFIG.cover.size) if album.cover else None

    while True:
        album_items = api.get_album_items_credits(album.id, offset=offset)
        for album_item in album_items.items:
            item = album_item.item
            futures.append(
                handle_item(
                    item,
                    format_template(
                        CONFIG.templates.album,
                        item=item,
                        album=album,
                        quality=get_item_quality(item, track_quality, video_quality),
                    ),
                    MetadataPayload(
                        date=str(album.releaseDate or ""),
                        artist=album.artist.name if album.artist else "",
                        credits=album_item.credits,
                        cover=cover,
                    ),
                )
            )

        offset += album_items.limit
        if offset >= album_items.totalNumberOfItems:
            break

    await asyncio.gather(*futures)


def get_item_quality(
    item: Track | Video,
    track_quality: TRACK_QUALITY_LITERAL,
    video_quality: VIDEO_QUALITY_LITERAL,
) -> str:
    if isinstance(item, Track):
        if track_quality == "max" and "HIRES_LOSSLESS" not in item.mediaMetadata.tags:
            return "HIGH"
        return track_qualities[track_quality]

    return video_qualities[video_quality]


def convert_track_output(path: Path, output_format: AudioOutputFormat) -> Path:
    match output_format:
        case "raw":
            return path
        case "wav":
            return convert_audio_to_wav(path)
        case "mp3_320":
            return convert_audio_to_mp3_320(path)


def render_library(api: TidalAPI, kind: ResourceKind) -> str:
    favorites = api.get_favorites()
    ids = favorites.model_dump()[kind.upper()][:20]
    rows = []

    for resource_id in ids:
        try:
            match kind:
                case "playlist":
                    item = api.get_playlist(resource_id)
                    title = item.title
                    meta = f"{item.numberOfTracks} tracks"
                    resource = f"playlist/{item.uuid}"
                case "album":
                    item = api.get_album(resource_id)
                    title = item.title
                    meta = item.artist.name if item.artist else "Album"
                    resource = f"album/{item.id}"
                case "track":
                    item = api.get_track(resource_id)
                    title = item.title
                    meta = item.artist.name if item.artist else "Track"
                    resource = f"track/{item.id}"
        except Exception:
            continue

        rows.append(resource_row(kind, title, meta, resource))

    if not rows:
        return '<p class="muted">No favorites found for this type.</p>'

    return "".join(rows)


def render_preview(api: TidalAPI, resource: TidalResource) -> str:
    match resource.type:
        case "playlist":
            playlist = api.get_playlist(resource.id)
            items = api.get_playlist_items(resource.id, limit=50)
            rows = [
                preview_item_row(index + 1, item.item)
                for index, item in enumerate(items.items)
            ]
            title = playlist.title
            meta = f"{playlist.numberOfTracks} tracks · {playlist.numberOfVideos} videos"

        case "album":
            album = api.get_album(resource.id)
            items = api.get_album_items(resource.id, limit=50)
            rows = [
                preview_item_row(index + 1, item.item)
                for index, item in enumerate(items.items)
            ]
            title = album.title
            artist = album.artist.name if album.artist else "Album"
            meta = f"{artist} · {album.numberOfTracks} tracks"

        case "track":
            track = api.get_track(resource.id)
            title = track.title
            artist = track.artist.name if track.artist else "Track"
            meta = f"{artist} · {track.audioQuality} · {track.duration}s"
            rows = [preview_item_row(1, track)]

        case _:
            raise ValueError(f"Unsupported resource type: {resource.type}")

    return f"""
    <section class="preview-card">
      <div class="preview-head">
        <div>
          <h2>{escape(title)}</h2>
          <p class="muted">{escape(meta)}</p>
          <code>{escape(str(resource))}</code>
        </div>
        {download_form(str(resource), compact=False)}
      </div>
      <div class="track-list">
        {"".join(rows)}
      </div>
    </section>
    """


def render_session_panel(state: WebState) -> str:
    auth_data = load_auth_data()
    if not auth_data.token:
        return """
        <section class="panel" id="session-panel">
          <div>
            <h2>Session</h2>
            <p class="muted">Not signed in. Start device login to trust this machine.</p>
          </div>
          <button class="primary" hx-post="/auth/start" hx-target="#session-panel" hx-swap="outerHTML">Sign in</button>
        </section>
        """

    expires = max(0, int((auth_data.expires_at - time.time()) / 60))
    return f"""
    <section class="panel" id="session-panel">
      <div>
        <h2>Session</h2>
        <p class="muted">Signed in as user {escape(auth_data.user_id or "")} · {escape(auth_data.country_code or "")} · token expires in {expires}m</p>
      </div>
      <div class="actions">
        <button hx-post="/auth/refresh" hx-target="#session-panel" hx-swap="outerHTML">Refresh</button>
        <button hx-post="/auth/logout" hx-target="#session-panel" hx-swap="outerHTML">Forget</button>
      </div>
    </section>
    """


def render_login_attempt(attempt: LoginAttempt) -> str:
    return f"""
    <section class="panel" id="session-panel" hx-get="/auth/status" hx-trigger="every 3s" hx-swap="outerHTML">
      <div>
        <h2>Session</h2>
        <p class="muted">{escape(attempt.message)}</p>
        <a class="link" href="{escape(attempt.uri)}" target="_blank">Open Tidal authorization</a>
      </div>
    </section>
    """


def render_jobs(state: WebState) -> str:
    jobs = sorted(state.jobs.values(), key=lambda item: item.created_at, reverse=True)
    if not jobs:
        return """
        <section id="jobs" class="job-board">
          <div class="job-column"><h3>En cola</h3><p class="muted">Sin descargas en cola.</p></div>
          <div class="job-column"><h3>Completadas</h3><p class="muted">Sin descargas completas.</p></div>
          <div class="job-column"><h3>Errores</h3><p class="muted">Sin errores.</p></div>
        </section>
        """

    queued = [job for job in jobs if job.status in ("queued", "running")]
    done = [job for job in jobs if job.status == "done"]
    failed = [job for job in jobs if job.status == "failed"]
    return f"""
    <section id="jobs" class="job-board">
      {render_job_column("En cola", queued)}
      {render_job_column("Completadas", done)}
      {render_job_column("Errores", failed)}
    </section>
    """


def render_job_column(title: str, jobs: list[DownloadJob]) -> str:
    if not jobs:
        return f'<div class="job-column"><h3>{escape(title)}</h3><p class="muted">Sin registros.</p></div>'

    rows = [render_job(job) for job in jobs[:12]]
    return f'<div class="job-column"><h3>{escape(title)}</h3>{"".join(rows)}</div>'


def render_job(job: DownloadJob) -> str:
    percent = int((job.completed / job.total) * 100) if job.total else 0
    results = "".join(
        f'<li><span>{escape(result.status)}</span><code>{escape(result.path or result.title)}</code></li>'
        for result in job.results[-4:]
    )
    error = f'<p class="error">{escape(job.error)}</p>' if job.error else ""
    return f"""
    <article class="job">
      <div class="job-top">
        <strong>{escape(job.resource)}</strong>
        <span class="badge {escape(job.status)}">{escape(job.status)}</span>
      </div>
      <p class="muted">{escape(job.message)}</p>
      <div class="meter"><span style="width: {percent}%"></span></div>
      <p class="muted">{job.completed}/{job.total or '?'} items · {format_bytes(job.bytes_downloaded)} · {escape(job.output_format.upper())} · audio {escape(job.track_quality.upper())} · video {escape(job.video_quality.upper())} · {job.concurrency}x</p>
      {error}
      <ul>{results}</ul>
    </article>
    """


def resource_row(kind: str, title: str, meta: str, resource: str) -> str:
    return f"""
    <article class="resource-row" hx-get="/partials/preview?resource={escape(resource)}" hx-target="#preview" hx-swap="innerHTML">
      <div class="resource-main">
        <strong>{escape(title)}</strong>
        <p class="muted">{escape(kind.title())} · {escape(meta)}</p>
      </div>
      <button hx-get="/partials/preview?resource={escape(resource)}" hx-target="#preview" hx-swap="innerHTML">Vista previa</button>
    </article>
    """


def preview_item_row(index: int, item: Track | Video) -> str:
    artist = item.artist.name if item.artist else ""
    if isinstance(item, Track):
        detail = f"{artist} · track {item.trackNumber} · {item.audioQuality}"
        resource = f"track/{item.id}"
    else:
        detail = f"{artist} · video · {item.quality}"
        resource = f"video/{item.id}"

    return f"""
    <article class="track-row">
      <span>{index:02d}</span>
      <div>
        <strong>{escape(item.title)}</strong>
        <p class="muted">{escape(detail)}</p>
      </div>
      {download_form(resource, compact=True) if isinstance(item, Track) else ""}
    </article>
    """


def download_form(resource: str, compact: bool) -> str:
    compact_class = "compact-form" if compact else "download-form"
    return f"""
    <form class="{compact_class}" hx-post="/jobs" hx-target="#jobs" hx-swap="outerHTML">
      <input type="hidden" name="resource" value="{escape(resource)}">
      <label>
        <span>Calidad audio</span>
        <select name="track_quality">
          {quality_options(CONFIG.download.track_quality)}
        </select>
      </label>
      <label>
        <span>Calidad video</span>
        <select name="video_quality">
          {video_quality_options(CONFIG.download.video_quality)}
        </select>
      </label>
      <label>
        <span>Salida</span>
        <select name="output_format">
          <option value="raw">RAW</option>
          <option value="wav">WAV</option>
          <option value="mp3_320">MP3 320</option>
        </select>
      </label>
      <label>
        <span>Paralelo</span>
        <input name="concurrency" type="number" min="1" max="3" value="3">
      </label>
      <button class="primary">Descargar</button>
    </form>
    """


def quality_options(selected: TRACK_QUALITY_LITERAL) -> str:
    labels: dict[TRACK_QUALITY_LITERAL, str] = {
        "low": "LOW - 96 kbps",
        "normal": "NORMAL - 320 kbps",
        "high": "HIGH - FLAC 16-bit/44.1 kHz",
        "max": "MAX - HiRes hasta 24-bit/192 kHz",
    }
    return "".join(
        f'<option value="{value}"{" selected" if value == selected else ""}>{label}</option>'
        for value, label in labels.items()
    )


def video_quality_options(selected: VIDEO_QUALITY_LITERAL) -> str:
    labels: dict[VIDEO_QUALITY_LITERAL, str] = {
        "sd": "SD - 360p",
        "hd": "HD - 720p",
        "fhd": "FHD - 1080p",
    }
    return "".join(
        f'<option value="{value}"{" selected" if value == selected else ""}>{label}</option>'
        for value, label in labels.items()
    )


def render_status(state: WebState) -> str:
    jobs = sorted(state.jobs.values(), key=lambda item: item.created_at, reverse=True)
    running = [job for job in jobs if job.status == "running"]
    queued = [job for job in jobs if job.status == "queued"]
    done = [job for job in jobs if job.status == "done"]
    failed = [job for job in jobs if job.status == "failed"]
    active = running[0] if running else None
    active_downloads = ", ".join(active.active_items.values()) if active else "Ninguna"
    latest_terminal = "Sin actividad"

    for job in jobs:
        if job.terminal:
            latest_terminal = job.terminal[-1]
            break

    return f"""
    <section id="status-bar" class="status-bar">
      <div>
        <strong>Terminal</strong>
        <p>{escape(latest_terminal)}</p>
      </div>
      <div>
        <strong>Descarga actual</strong>
        <p>{escape(active_downloads)}</p>
      </div>
      <div>
        <strong>Progreso</strong>
        <p>{len(running)} activas · {len(queued)} en cola · {len(done)} completas · {len(failed)} errores</p>
      </div>
    </section>
    """


def page() -> str:
    return """
    <!doctype html>
    <html lang="es">
    <head>
      <meta charset="utf-8">
      <meta name="viewport" content="width=device-width, initial-scale=1">
      <title>Psybots Tiddl</title>
      <script src="https://unpkg.com/htmx.org@2.0.4"></script>
      <style>
        :root { color-scheme: light; --ink: #172026; --muted: #65717a; --line: #d9dee3; --panel: #f7f8fa; --accent: #0f7b68; --danger: #ad3030; --warn: #9c6a12; }
        * { box-sizing: border-box; }
        body { margin: 0; font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; background: #fff; color: var(--ink); overflow: hidden; }
        header { height: 58px; display: flex; align-items: center; justify-content: space-between; padding: 0 20px; border-bottom: 1px solid var(--line); background: #fbfbfc; }
        main { display: grid; grid-template-columns: minmax(330px, 420px) minmax(460px, 1fr); height: calc(100vh - 154px); }
        aside { border-right: 1px solid var(--line); padding: 16px; background: var(--panel); overflow: auto; }
        section.workspace { display: grid; grid-template-rows: minmax(280px, 1fr) minmax(210px, 34vh); min-height: 0; }
        section.preview-pane, section.queue-pane { padding: 16px; overflow: auto; }
        section.preview-pane { border-bottom: 1px solid var(--line); }
        h1 { font-size: 18px; margin: 0; }
        h2 { font-size: 15px; margin: 0 0 6px; }
        h3 { font-size: 13px; margin: 0 0 8px; }
        .muted { color: var(--muted); margin: 0; font-size: 13px; }
        .panel { display: flex; align-items: center; justify-content: space-between; gap: 16px; padding: 14px; border: 1px solid var(--line); background: #fff; border-radius: 8px; margin-bottom: 14px; }
        .actions, .tabs, form.inline { display: flex; gap: 8px; align-items: center; flex-wrap: wrap; }
        button, input, select { height: 36px; border: 1px solid var(--line); border-radius: 6px; background: #fff; color: var(--ink); padding: 0 10px; font: inherit; }
        input { min-width: 0; width: 100%; }
        button { cursor: pointer; }
        button.primary { background: var(--accent); color: white; border-color: var(--accent); }
        .tabs button { min-width: 82px; }
        .link { color: var(--accent); font-size: 13px; }
        .resource-row, .job, .track-row { border-bottom: 1px solid var(--line); padding: 12px 0; }
        .resource-row { display: flex; justify-content: space-between; gap: 12px; align-items: center; }
        .resource-main { min-width: 0; }
        .resource-row:hover { background: #eef6f4; margin: 0 -8px; padding-left: 8px; padding-right: 8px; border-radius: 6px; }
        .preview-card { border: 1px solid var(--line); border-radius: 8px; background: #fff; }
        .preview-head { display: flex; justify-content: space-between; align-items: flex-start; gap: 16px; padding: 14px; border-bottom: 1px solid var(--line); }
        .track-list { padding: 0 14px 6px; }
        .track-row { display: grid; grid-template-columns: 34px 1fr auto; gap: 12px; align-items: center; }
        .download-form, .compact-form { display: flex; gap: 8px; align-items: end; flex-wrap: wrap; }
        .download-form label, .compact-form label { display: grid; gap: 4px; font-size: 12px; color: var(--muted); }
        .compact-form select { width: 96px; }
        .compact-form input { width: 70px; }
        .compact-form label:first-of-type select { width: 150px; }
        .compact-form label:nth-of-type(2) select { width: 120px; }
        .manual-download { display: grid; gap: 8px; width: 100%; }
        .manual-download .settings { display: grid; grid-template-columns: 1fr 150px 120px 96px 88px auto; gap: 8px; align-items: end; }
        .job-board { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 14px; }
        .job-column { min-width: 0; border: 1px solid var(--line); border-radius: 8px; padding: 12px; background: #fff; }
        .job-top { display: flex; justify-content: space-between; gap: 12px; }
        .badge { font-size: 12px; border: 1px solid var(--line); border-radius: 999px; padding: 3px 8px; text-transform: uppercase; }
        .badge.done { color: var(--accent); border-color: var(--accent); }
        .badge.failed { color: var(--danger); border-color: var(--danger); }
        .badge.running { color: var(--warn); border-color: var(--warn); }
        .meter { height: 6px; background: #e8ecef; border-radius: 999px; overflow: hidden; margin: 8px 0; }
        .meter span { display: block; height: 100%; background: var(--accent); }
        ul { margin: 8px 0 0; padding-left: 18px; }
        code { font-size: 12px; word-break: break-all; }
        .error { color: var(--danger); font-size: 13px; margin: 8px 0 0; }
        .status-bar { height: 96px; display: grid; grid-template-columns: 1.4fr 1fr 1fr; gap: 16px; padding: 12px 20px; border-top: 1px solid var(--line); background: #101820; color: #f4f7f8; }
        .status-bar strong { display: block; font-size: 12px; color: #9fd7cc; margin-bottom: 4px; }
        .status-bar p { margin: 0; font-size: 13px; color: #e1e7ea; }
        @media (max-width: 920px) {
          body { overflow: auto; }
          main { grid-template-columns: 1fr; height: auto; }
          section.workspace { grid-template-rows: auto auto; }
          aside { border-right: 0; border-bottom: 1px solid var(--line); }
          .job-board, .status-bar { grid-template-columns: 1fr; }
          .status-bar { height: auto; }
          .manual-download .settings { grid-template-columns: 1fr; }
        }
      </style>
    </head>
    <body>
      <header>
        <h1>Psybots Tiddl</h1>
        <span class="muted">Autor: Psybots · Aplicacion ejecutable local</span>
      </header>
      <main>
        <aside>
          <div hx-get="/partials/session" hx-trigger="load" hx-swap="outerHTML"></div>
          <section class="panel">
            <form class="manual-download" hx-post="/jobs" hx-target="#jobs" hx-swap="outerHTML">
              <h2>Descarga directa</h2>
              <div class="settings">
                <input name="resource" placeholder="track/123, album/123 or playlist/uuid">
                <select name="track_quality" title="Calidad de streaming de audio">
                  {quality_options(CONFIG.download.track_quality)}
                </select>
                <select name="video_quality" title="Calidad de streaming de video">
                  {video_quality_options(CONFIG.download.video_quality)}
                </select>
                <select name="output_format">
                  <option value="raw">RAW</option>
                  <option value="wav">WAV</option>
                  <option value="mp3_320">MP3 320</option>
                </select>
                <input name="concurrency" type="number" min="1" max="3" value="3" title="Descargas paralelas">
                <button class="primary">Descargar</button>
              </div>
            </form>
          </section>
          <section>
            <h2>Favorites</h2>
            <div class="tabs">
              <button hx-get="/partials/library?kind=playlist" hx-target="#library">Playlists</button>
              <button hx-get="/partials/library?kind=album" hx-target="#library">Albumes</button>
              <button hx-get="/partials/library?kind=track" hx-target="#library">Tracks</button>
            </div>
            <div id="library" hx-get="/partials/library?kind=playlist" hx-trigger="load">
              <p class="muted">Loading favorites...</p>
            </div>
          </section>
        </aside>
        <section class="workspace">
          <section class="preview-pane">
            <div id="preview">
              <section class="preview-card">
                <div class="preview-head">
                  <div>
                    <h2>Vista previa</h2>
                    <p class="muted">Haz click en una playlist, album o track para ver su contenido aqui.</p>
                  </div>
                </div>
              </section>
            </div>
          </section>
          <section class="queue-pane">
            <h2>Descargas</h2>
            <div hx-get="/partials/jobs" hx-trigger="load, every 2s" hx-target="#jobs" hx-swap="outerHTML">
              <section id="jobs" class="job-board">
                <div class="job-column"><h3>En cola</h3><p class="muted">Sin descargas en cola.</p></div>
                <div class="job-column"><h3>Completadas</h3><p class="muted">Sin descargas completas.</p></div>
                <div class="job-column"><h3>Errores</h3><p class="muted">Sin errores.</p></div>
              </section>
            </div>
          </section>
        </section>
      </main>
      <div hx-get="/partials/status" hx-trigger="load, every 2s" hx-target="#status-bar" hx-swap="outerHTML">
        <section id="status-bar" class="status-bar">
          <div><strong>Terminal</strong><p>Sin actividad</p></div>
          <div><strong>Descarga actual</strong><p>Ninguna</p></div>
          <div><strong>Progreso</strong><p>0 activas · 0 en cola · 0 completas · 0 errores</p></div>
        </section>
      </div>
    </body>
    </html>
    """


def strip_rich(value: str) -> str:
    return re.sub(r"\[[^\]]*\]", "", value)


def escape(value: str) -> str:
    return (
        value.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def format_bytes(value: int) -> str:
    units = ["B", "KB", "MB", "GB"]
    amount = float(value)
    for unit in units:
        if amount < 1024 or unit == units[-1]:
            return f"{amount:.1f} {unit}"
        amount /= 1024
    return f"{value} B"


def wait_for_port(host: str, port: int, timeout: float = 10) -> None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.settimeout(0.2)
            if sock.connect_ex((host, port)) == 0:
                return
        time.sleep(0.1)
    raise RuntimeError(f"Server did not start on {host}:{port}")


def port_is_available(host: str, port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        return sock.connect_ex((host, port)) != 0


def choose_port(host: str, preferred_port: int) -> int:
    for port in range(preferred_port, preferred_port + 20):
        if port_is_available(host, port):
            return port

    raise RuntimeError("No local port available for the desktop app")


def run_desktop(host: str = "127.0.0.1", port: int = 8765, browser: bool = False) -> None:
    app = create_app()
    port = choose_port(host, port)

    config = uvicorn.Config(app, host=host, port=port, log_level="warning")
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    wait_for_port(host, port)

    if browser:
        webbrowser.open(f"http://{host}:{port}")
        try:
            thread.join()
        except KeyboardInterrupt:
            server.should_exit = True
        return

    try:
        import webview
    except ImportError:
        webbrowser.open(f"http://{host}:{port}")
        thread.join()
        return

    try:
        webview.create_window(
            "Psybots Tiddl",
            f"http://{host}:{port}",
            width=1240,
            height=820,
        )
        webview.start()
    except Exception:
        webbrowser.open(f"http://{host}:{port}")
        thread.join()
    finally:
        server.should_exit = True
