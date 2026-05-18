import asyncio
import logging
import re
import socket
import subprocess
import sys
import threading
import time
import webbrowser
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Literal
from uuid import uuid4

from fastapi import FastAPI, Form, HTTPException
from fastapi.responses import HTMLResponse
import uvicorn

from tiddl.cli.config import CONFIG, TRACK_QUALITY_LITERAL, VIDEO_QUALITY_LITERAL
from tiddl.cli.commands.download.downloader import DownloadCancelled, Downloader
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
from tiddl.core.utils.sanitize import sanitize_string
from tiddl.version import APP_VERSION

ResourceKind = Literal["track", "album", "playlist"]
AudioOutputFormat = Literal["raw", "wav", "mp3_320"]
WEB_FAVORITES_LIMIT = 50
log = logging.getLogger("tiddl.web")


@dataclass
class LoginAttempt:
    id: str
    uri: str
    expires_at: float
    status: str = "pending"
    message: str = "Esperando autorización"


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
    target_path: str = ""
    status: str = "queued"
    message: str = "En cola"
    total: int = 0
    completed: int = 0
    bytes_downloaded: int = 0
    results: list[JobResult] = field(default_factory=list)
    active_items: dict[int, str] = field(default_factory=dict)
    terminal: list[str] = field(default_factory=list)
    error: str = ""
    cancel_requested: bool = False
    canceled_at: float | None = None
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
        log.info("%s", self.job.message)


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
        self.job.terminal.append(f"Iniciando {clean_description}")
        log.info("job=%s start item=%s", self.job.id, clean_description)
        return task_id

    def download_advance(self, task_id: int, size: float) -> None:
        self.job.bytes_downloaded += int(size)

    def download_finish(self, task_id: int) -> WebTask:
        task = self.tasks.pop(task_id)
        self.job.active_items.pop(task_id, None)
        self.job.completed += 1
        return task

    def mark_item_processed(self) -> None:
        if self.job.completed < self.job.total:
            self.job.completed += 1

    def show_item_result(
        self, result_message: str, item_description: str, item_path: Path | None
    ) -> None:
        status = display_result_status(result_message)
        self.job.results.append(
            JobResult(
                title=strip_rich(item_description),
                path=str(item_path) if item_path else "",
                status=status,
            )
        )
        self.job.terminal.append(f"{status} {strip_rich(item_description)}")
        self.job.terminal = self.job.terminal[-40:]
        log.info(
            "job=%s result=%s item=%s path=%s",
            self.job.id,
            status,
            strip_rich(item_description),
            item_path,
        )

    def show_item_skipped(self, item: Track | Video, reason: str) -> None:
        self.job.results.append(
            JobResult(title=item.title, path="", status=f"Omitido: {reason}")
        )
        self.job.terminal.append(f"Omitido {item.title}: {reason}")
        self.job.terminal = self.job.terminal[-40:]
        log.info(
            "job=%s skipped item_id=%s title=%s reason=%s",
            self.job.id,
            item.id,
            item.title,
            reason,
        )

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
        if error.__traceback__:
            log.error(
                "job=%s item_id=%s item=%s failed: %s",
                self.job.id,
                item.id,
                item.title,
                error,
                exc_info=(type(error), error, error.__traceback__),
            )
        else:
            log.error(
                "job=%s item_id=%s item=%s failed: %s",
                self.job.id,
                item.id,
                item.title,
                error,
            )


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
    app = FastAPI(title=f"Psybots Tiddl {APP_VERSION}")

    @app.get("/", response_class=HTMLResponse)
    def home() -> str:
        return page()

    @app.get("/partials/session", response_class=HTMLResponse)
    def session_panel() -> str:
        return render_session_panel(web_state)

    @app.post("/auth/start", response_class=HTMLResponse)
    def auth_start() -> str:
        try:
            device_auth = web_state.auth_api.get_device_auth()
        except Exception as exc:
            log.exception("could not start auth")
            return render_session_error(
                f"No pudimos iniciar sesión con TIDAL: {friendly_error(exc)}"
            )

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
        try:
            ensure_fresh_auth(web_state.auth_api, force=True)
            return render_session_panel(web_state)
        except Exception as exc:
            log.exception("could not refresh auth")
            return render_session_error(
                f"No pudimos actualizar la sesión: {friendly_error(exc)}"
            )

    @app.post("/auth/logout", response_class=HTMLResponse)
    def auth_logout() -> str:
        save_auth_data(AuthData())
        with web_state.lock:
            web_state.login_attempt = None
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
            return (
                '<p class="muted">Inicia sesión para cargar tu biblioteca de TIDAL.</p>'
            )

        try:
            api = web_state.api()
            return render_library(api, kind)
        except Exception as exc:
            log.exception("could not render library kind=%s", kind)
            return render_inline_error(
                f"No pudimos cargar la biblioteca: {friendly_error(exc)}"
            )

    @app.get("/partials/preview", response_class=HTMLResponse)
    def preview(resource: str) -> str:
        try:
            tidal_resource = parse_supported_resource(resource)
        except ValueError as exc:
            return render_preview_message("Recurso no válido", str(exc))

        if not web_state.authenticated():
            return render_preview_message(
                "Sesión requerida",
                "Inicia sesión con TIDAL para revisar este recurso.",
            )

        try:
            api = web_state.api()
            return render_preview(api, tidal_resource)
        except Exception as exc:
            log.exception("could not render preview resource=%s", tidal_resource)
            return render_preview_message(
                "No pudimos cargar la vista previa", friendly_error(exc)
            )

    @app.post("/jobs", response_class=HTMLResponse)
    def create_job(
        resource: str = Form(...),
        output_format: AudioOutputFormat = Form("raw"),
        track_quality: TRACK_QUALITY_LITERAL = Form("high"),
        video_quality: VIDEO_QUALITY_LITERAL = Form("fhd"),
    ) -> str:
        try:
            tidal_resource = parse_supported_resource(resource.strip())
        except ValueError as exc:
            return render_jobs(web_state, notice=str(exc))

        if not web_state.authenticated():
            return render_jobs(
                web_state,
                notice="Inicia sesión con TIDAL antes de iniciar una descarga.",
            )

        try:
            api = web_state.api()
        except Exception as exc:
            log.exception("could not create api for job resource=%s", tidal_resource)
            return render_jobs(
                web_state,
                notice=f"No pudimos preparar la descarga: {friendly_error(exc)}",
            )

        concurrency = auto_concurrency(tidal_resource)

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

    @app.post("/jobs/{job_id}/cancel", response_class=HTMLResponse)
    def cancel_job(job_id: str) -> str:
        with web_state.lock:
            job = web_state.jobs.get(job_id)

            if not job:
                return render_jobs(
                    web_state,
                    notice="No encontramos esa descarga en la cola.",
                )

            request_job_cancel(job)

        return render_jobs(web_state)

    @app.post("/open-folder", response_class=HTMLResponse)
    def open_download_folder(path: str = Form("")) -> str:
        try:
            folder = resolve_open_folder(path)
            open_folder(folder)
            return render_status_message(f"Carpeta abierta: {folder}")
        except Exception as exc:
            return render_status_message(f"No se pudo abrir la carpeta: {exc}")

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
                attempt.message = f"Esperando autorización ({remaining}s restantes)"
                continue

            attempt.status = "failed"
            attempt.message = (
                exc.error_description or exc.error or "No se pudo autorizar"
            )
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
        attempt.message = "Sesión iniciada"
        return

    attempt.status = "expired"
    attempt.message = "La autorización expiró"


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
    if not resource.strip():
        raise ValueError("Ingresa un recurso para descargar.")

    try:
        tidal_resource = TidalResource.from_string(resource)
    except ValueError as exc:
        raise ValueError(
            "Ingresa un recurso válido: track/123, album/123 o playlist/uuid."
        ) from exc

    if tidal_resource.type not in ("track", "album", "playlist"):
        raise ValueError("La aplicación soporta canciones, álbumes y playlists.")

    return tidal_resource


def friendly_error(exc: Exception) -> str:
    if isinstance(exc, HTTPException):
        return str(exc.detail)

    if isinstance(exc, ApiError):
        return exc.user_message

    return str(exc) or exc.__class__.__name__


def request_job_cancel(job: DownloadJob) -> bool:
    if job.cancel_requested or job.status in ("done", "failed", "canceled"):
        return False

    job.cancel_requested = True
    job.canceled_at = time.time()
    job.status = "canceling"
    job.message = "Cancelando descarga"
    job.terminal.append("Cancelación solicitada por el usuario")
    job.terminal = job.terminal[-40:]
    return True


def finalize_canceled_job(job: DownloadJob) -> None:
    job.cancel_requested = True
    job.status = "canceled"
    job.message = "Cancelada por el usuario"
    job.error = ""
    job.active_items.clear()
    if not job.terminal or job.terminal[-1] != job.message:
        job.terminal.append(job.message)
        job.terminal = job.terminal[-40:]


def raise_if_job_canceled(job: DownloadJob) -> None:
    if job.cancel_requested:
        raise DownloadCancelled("Descarga cancelada por el usuario")


def can_cancel_job(job: DownloadJob) -> bool:
    return job.status in ("queued", "running", "canceling") and not job.cancel_requested


def clamp_concurrency(value: int) -> int:
    return max(1, min(3, value))


def auto_concurrency(resource: TidalResource) -> int:
    if resource.type == "track":
        return 1

    return 3


def resolve_open_folder(path: str) -> Path:
    if path.strip():
        target = Path(path).expanduser()
        if target.is_file():
            return target.parent
        if target.is_dir():
            return target

    return CONFIG.download.download_path


def open_folder(folder: Path) -> None:
    folder.mkdir(parents=True, exist_ok=True)

    if sys.platform == "darwin":
        subprocess.Popen(["open", str(folder)])
    elif sys.platform.startswith("win"):
        import os

        os.startfile(folder)  # type: ignore[attr-defined]
    else:
        subprocess.Popen(["xdg-open", str(folder)])


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
        raise_if_job_canceled(job)
        job.status = "running"
        job.message = "Preparando descarga"
        job.target_path = str(CONFIG.download.download_path)
        job.terminal.append(
            f"En cola {resource} como {output_format.upper()} con {concurrency} descarga(s) en paralelo"
        )
        log.info(
            "job=%s resource=%s output=%s audio=%s video=%s concurrency=%s download_path=%s log=%s",
            job.id,
            resource,
            output_format,
            track_quality,
            video_quality,
            concurrency,
            CONFIG.download.download_path,
            APP_PATH / "latest.log",
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
        if job.cancel_requested:
            finalize_canceled_job(job)
            log.info("job=%s canceled", job.id)
        elif job.status != "failed":
            finalize_job(job)
            log.info(
                "job=%s finished status=%s message=%s", job.id, job.status, job.message
            )
    except DownloadCancelled:
        finalize_canceled_job(job)
        log.info("job=%s canceled", job.id)
    except Exception as exc:
        if job.cancel_requested:
            finalize_canceled_job(job)
            log.info("job=%s canceled after error=%s", job.id, exc)
        else:
            job.status = "failed"
            job.error = str(exc)
            job.message = str(exc)
            job.terminal.append(f"Error: {exc}")
            log.exception("job=%s failed", job.id)


async def download_resource(
    api: TidalAPI,
    resource: TidalResource,
    job: DownloadJob,
    output_format: AudioOutputFormat,
    concurrency: int,
    track_quality: TRACK_QUALITY_LITERAL,
    video_quality: VIDEO_QUALITY_LITERAL,
) -> None:
    if not job.target_path:
        job.target_path = str(CONFIG.download.download_path)

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
        cancel_requested=lambda: job.cancel_requested,
    )

    async def handle_item(
        item: Track | Video,
        file_path: str,
        metadata: MetadataPayload | None = None,
    ) -> tuple[Path | None, Track | Video]:
        raise_if_job_canceled(job)
        output.total_increment()
        metadata = metadata or MetadataPayload()
        completed_before = job.completed

        try:
            path, was_downloaded = await downloader.download(item, Path(file_path))
        except DownloadCancelled:
            if job.completed == completed_before:
                output.mark_item_processed()
            return None, item
        except Exception as exc:
            if job.completed == completed_before:
                output.mark_item_processed()
            output.show_item_error(item, exc)
            return None, item

        if not path:
            if job.completed == completed_before:
                output.mark_item_processed()
            last_message = job.terminal[-1] if job.terminal else ""
            if last_message.startswith("Error") or "Can't stream" in last_message:
                output.show_item_error(item, RuntimeError(last_message))
            else:
                output.show_item_skipped(
                    item,
                    "omitido, no disponible o filtrado por configuración",
                )
            return path, item

        if not was_downloaded and job.completed == completed_before:
            output.mark_item_processed()

        if isinstance(item, Track) and was_downloaded:
            try:
                path = convert_track_output(path, output_format)
                output.update_last_result_path(path)
            except Exception as exc:
                if job.completed == completed_before:
                    output.mark_item_processed()
                output.show_item_error(item, exc)
                return None, item

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
            raise_if_job_canceled(job)
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
                    cover=Cover(album.cover)
                    if album.cover and CONFIG.metadata.cover
                    else None,
                ),
            )

        case "album":
            raise_if_job_canceled(job)
            album = api.get_album(resource.id)
            await download_album(
                api,
                album,
                handle_item,
                track_quality,
                video_quality,
                cancel_requested=lambda: job.cancel_requested,
            )

        case "playlist":
            raise_if_job_canceled(job)
            playlist = api.get_playlist(resource.id)
            playlist_folder = web_playlist_folder(playlist)
            job.target_path = str(CONFIG.download.download_path / playlist_folder)
            job.terminal.append(f"Destino de playlist: {job.target_path}")
            log.info(
                "job=%s playlist=%s playlist_title=%s target=%s",
                job.id,
                resource.id,
                playlist.title,
                job.target_path,
            )
            offset = 0
            playlist_index = 0
            futures = []

            while True:
                raise_if_job_canceled(job)
                items = api.get_playlist_items(resource.id, offset=offset)
                for playlist_item in items.items:
                    playlist_index += 1
                    item = playlist_item.item
                    album = None
                    if (
                        isinstance(item, Track)
                        and "{album" in CONFIG.templates.playlist
                    ):
                        try:
                            album = api.get_album(item.album.id)
                        except ApiError:
                            album = None

                    futures.append(
                        handle_item(
                            item,
                            str(
                                playlist_folder
                                / web_playlist_item_filename(
                                    item=item,
                                    album=album,
                                    playlist=playlist,
                                    playlist_index=playlist_index,
                                    track_quality=track_quality,
                                    video_quality=video_quality,
                                )
                            ),
                        )
                    )

                offset += items.limit
                if offset >= items.totalNumberOfItems:
                    break

            await asyncio.gather(*futures)

        case _:
            raise ValueError(f"Unsupported resource type: {resource.type}")


def web_playlist_folder(playlist: Any) -> Path:
    return Path("playlist") / clean_path_segment(playlist.title)


def web_playlist_item_filename(
    item: Track | Video,
    album: Album | None,
    playlist: Any,
    playlist_index: int,
    track_quality: TRACK_QUALITY_LITERAL,
    video_quality: VIDEO_QUALITY_LITERAL,
) -> Path:
    return Path(
        format_template(
            "{playlist.index:03d} - {item.artist} - {item.title}",
            item=item,
            album=album,
            playlist=playlist,
            playlist_index=playlist_index,
            quality=get_item_quality(item, track_quality, video_quality),
            with_asterisk_ext=False,
        )
    )


def clean_path_segment(value: str) -> str:
    value = sanitize_string(value)
    value = re.sub(r"\.{2,}", ".", value)
    value = value.rstrip(" .")
    value = re.sub(r"\s{2,}", " ", value)
    value = value.strip()
    return value or "_"


async def download_album(
    api: TidalAPI,
    album: Album,
    handle_item: Any,
    track_quality: TRACK_QUALITY_LITERAL,
    video_quality: VIDEO_QUALITY_LITERAL,
    cancel_requested: Callable[[], bool] | None = None,
) -> None:
    offset = 0
    futures = []
    cover = Cover(album.cover, size=CONFIG.cover.size) if album.cover else None
    is_canceled = cancel_requested or (lambda: False)

    while True:
        if is_canceled():
            raise DownloadCancelled("Descarga cancelada por el usuario")

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
    rows = []
    total_count = 0

    if kind == "playlist":
        playlists = get_all_web_playlists(api)
        total_count = len(playlists)
        for item in playlists:
            title = item.title
            meta = f"{item.numberOfTracks} canciones · {item.numberOfVideos} videos"
            resource = f"playlist/{item.uuid}"
            rows.append(resource_row(kind, title, meta, resource))
    else:
        favorites = api.get_favorites()
        ids = favorites.model_dump()[kind.upper()]
        total_count = len(ids)

        for resource_id in ids[:WEB_FAVORITES_LIMIT]:
            try:
                match kind:
                    case "album":
                        item = api.get_album(resource_id)
                        title = item.title
                        meta = item.artist.name if item.artist else "Álbum"
                        resource = f"album/{item.id}"
                    case "track":
                        item = api.get_track(resource_id)
                        title = item.title
                        meta = item.artist.name if item.artist else "Canción"
                        resource = f"track/{item.id}"
                    case _:
                        continue
            except Exception:
                log.exception(
                    "could not load favorite kind=%s resource_id=%s",
                    kind,
                    resource_id,
                )
                continue

            rows.append(resource_row(kind, title, meta, resource))

    if not rows:
        return '<p class="muted">No hay favoritos guardados en esta categoría.</p>'

    return f"""
    <div class="library-list">
      <p class="muted list-count">{escape(library_count_label(kind, len(rows), total_count))}</p>
      {"".join(rows)}
    </div>
    """


def get_all_web_playlists(api: TidalAPI) -> list[Any]:
    offset = 0
    playlists: list[Any] = []
    seen: set[str] = set()

    while True:
        page = api.get_user_and_favorite_playlists(offset=offset)
        for playlist_item in page.items:
            playlist = playlist_item.playlist
            if playlist.uuid in seen:
                continue
            seen.add(playlist.uuid)
            playlists.append(playlist)

        offset += page.limit
        if offset >= page.totalNumberOfItems:
            break

    return playlists


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
            meta = f"{playlist.numberOfTracks} canciones · {playlist.numberOfVideos} videos"

        case "album":
            album = api.get_album(resource.id)
            items = api.get_album_items(resource.id, limit=50)
            rows = [
                preview_item_row(index + 1, item.item)
                for index, item in enumerate(items.items)
            ]
            title = album.title
            artist = album.artist.name if album.artist else "Álbum"
            meta = f"{artist} · {album.numberOfTracks} canciones"

        case "track":
            track = api.get_track(resource.id)
            title = track.title
            artist = track.artist.name if track.artist else "Canción"
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
            <h2>Sesión</h2>
            <p class="muted">Conecta tu cuenta de TIDAL para ver favoritos y descargar.</p>
          </div>
          <button class="primary" hx-post="/auth/start" hx-target="#session-panel" hx-swap="outerHTML">Iniciar sesión</button>
        </section>
        """

    expires = max(0, int((auth_data.expires_at - time.time()) / 60))
    return f"""
    <section class="panel" id="session-panel">
      <div>
        <h2>Sesión activa</h2>
        <p class="muted">Usuario {escape(auth_data.user_id or "")} · {escape(auth_data.country_code or "")} · expira en {expires} min</p>
      </div>
      <div class="actions">
        <button hx-post="/auth/refresh" hx-target="#session-panel" hx-swap="outerHTML">Actualizar</button>
        <button hx-post="/auth/logout" hx-target="#session-panel" hx-swap="outerHTML">Cerrar sesión</button>
      </div>
    </section>
    """


def render_login_attempt(attempt: LoginAttempt) -> str:
    return f"""
    <section class="panel" id="session-panel" hx-get="/auth/status" hx-trigger="every 3s" hx-swap="outerHTML">
      <div>
        <h2>Sesión</h2>
        <p class="muted">{escape(attempt.message)}</p>
        <a class="link" href="{escape(attempt.uri)}" target="_blank">Abrir autorización de TIDAL</a>
      </div>
    </section>
    """


def render_session_error(message: str) -> str:
    return f"""
    <section class="panel" id="session-panel">
      <div>
        <h2>Sesión</h2>
        <p class="error">{escape(message)}</p>
      </div>
      <button class="primary" hx-post="/auth/start" hx-target="#session-panel" hx-swap="outerHTML">Reintentar</button>
    </section>
    """


def render_inline_error(message: str) -> str:
    return f'<p class="error">{escape(message)}</p>'


def render_preview_message(title: str, message: str) -> str:
    return f"""
    <section class="preview-card">
      <div class="preview-head">
        <div>
          <h2>{escape(title)}</h2>
          <p class="error">{escape(message)}</p>
        </div>
      </div>
    </section>
    """


def render_jobs(state: WebState, notice: str = "") -> str:
    jobs = sorted(state.jobs.values(), key=lambda item: item.created_at, reverse=True)
    if not jobs:
        notice_html = (
            render_job_notice(notice) if notice else '<p class="muted">Sin errores.</p>'
        )
        return """
        <section id="jobs" class="job-board">
          <div class="job-column"><h3>En curso</h3><p class="muted">Sin descargas activas.</p></div>
          <div class="job-column"><h3>Completadas</h3><p class="muted">Sin descargas completas.</p></div>
          <div class="job-column"><h3>Canceladas</h3><p class="muted">Sin cancelaciones.</p></div>
          <div class="job-column"><h3>Errores</h3>__NOTICE__</div>
        </section>
        """.replace("__NOTICE__", notice_html)

    queued = [job for job in jobs if job.status in ("queued", "running", "canceling")]
    done = [job for job in jobs if job.status == "done" and not has_job_errors(job)]
    canceled = [job for job in jobs if job.status == "canceled"]
    failed = [job for job in jobs if job.status == "failed" or has_job_errors(job)]
    return f"""
    <section id="jobs" class="job-board">
      {render_job_column("En curso", queued)}
      {render_job_column("Completadas", done)}
      {render_job_column("Canceladas", canceled)}
      {render_job_column("Errores", failed, render_job_notice(notice) if notice else "")}
    </section>
    """


def render_job_column(title: str, jobs: list[DownloadJob], extra: str = "") -> str:
    if not jobs and not extra:
        return f'<div class="job-column"><h3>{escape(title)}</h3><p class="muted">Sin registros.</p></div>'

    rows = [render_job(job) for job in jobs[:12]]
    return (
        f'<div class="job-column"><h3>{escape(title)}</h3>{"".join(rows)}{extra}</div>'
    )


def render_job_notice(message: str) -> str:
    if not message:
        return ""

    return f"""
    <article class="job notice-job">
      <div class="job-top">
        <div>
          <strong>No se pudo iniciar</strong>
          <p class="error">{escape(message)}</p>
        </div>
        <span class="badge failed">Error</span>
      </div>
    </article>
    """


def has_job_errors(job: DownloadJob) -> bool:
    return any(is_error_status(result.status) for result in job.results)


def successful_result_count(job: DownloadJob) -> int:
    return sum(
        1
        for result in job.results
        if result.path and not is_error_status(result.status)
    )


def skipped_result_count(job: DownloadJob) -> int:
    return sum(1 for result in job.results if is_skipped_status(result.status))


def finalize_job(job: DownloadJob) -> None:
    successes = successful_result_count(job)

    if successes == 0:
        job.status = "failed"
        job.error = (
            "No se descargó ningún archivo. Revisa filtros, calidad seleccionada, "
            "disponibilidad regional o si la playlist contiene solo videos."
        )
        job.message = "Finalizada sin archivos descargables"
        job.terminal.append(job.error)
        log.error("job=%s finished without files results=%s", job.id, job.results)
        return

    job.status = "done"
    if has_job_errors(job):
        job.message = f"Finalizada con errores ({format_file_count(successes)})"
    else:
        job.message = f"Finalizada ({format_file_count(successes)})"


def render_job(job: DownloadJob) -> str:
    percent = int((job.completed / job.total) * 100) if job.total else 0
    percent = max(0, min(100, percent))
    results = "".join(render_job_result(result) for result in job.results[-5:])
    error = f'<p class="error">{escape(job.error)}</p>' if job.error else ""
    target_path = job.target_path or str(CONFIG.download.download_path)
    warnings = skipped_result_count(job)
    warning_text = f" · {warnings} omitidos" if warnings else ""
    return f"""
    <article class="job">
      <div class="job-top">
        <div>
          <strong>{escape(job.resource)}</strong>
          <p class="muted">{escape(job.message)}</p>
        </div>
        <div class="job-actions">
          <span class="badge {escape(job.status)}">{escape(job_status_label(job.status))}</span>
          {cancel_job_form(job)}
        </div>
      </div>
      <div class="meter"><span style="width: {percent}%"></span></div>
      <dl class="job-facts">
        <div><dt>Progreso</dt><dd>{job.completed}/{job.total or "?"} ítems{warning_text}</dd></div>
        <div><dt>Datos</dt><dd>{format_bytes(job.bytes_downloaded)}</dd></div>
        <div><dt>Formato</dt><dd>{escape(job.output_format.upper())}</dd></div>
        <div><dt>Audio</dt><dd>{escape(job.track_quality.upper())}</dd></div>
        <div><dt>Video</dt><dd>{escape(job.video_quality.upper())}</dd></div>
        <div><dt>Paralelo</dt><dd>{job.concurrency}x auto</dd></div>
      </dl>
      <div class="job-path">
        <span>Destino</span>
        <code>{escape(target_path)}</code>
        <form hx-post="/open-folder" hx-target="#status-bar" hx-swap="outerHTML">
          <input type="hidden" name="path" value="{escape(target_path)}">
          <button>Abrir carpeta</button>
        </form>
      </div>
      {error}
      <div class="result-list">{results}</div>
    </article>
    """


def render_job_result(result: JobResult) -> str:
    open_button = ""
    if result.path:
        open_button = f"""
        <form hx-post="/open-folder" hx-target="#status-bar" hx-swap="outerHTML">
          <input type="hidden" name="path" value="{escape(result.path)}">
          <button>Abrir carpeta</button>
        </form>
        """

    return f"""
    <div class="result-row">
      <span class="result-status">{escape(result.status)}</span>
      <strong>{escape(result.title)}</strong>
      <code>{escape(result.path or "Sin archivo")}</code>
      {open_button}
    </div>
    """


def cancel_job_form(job: DownloadJob) -> str:
    if not can_cancel_job(job):
        return ""

    return f"""
    <form class="cancel-form" hx-post="/jobs/{escape(job.id)}/cancel" hx-target="#jobs" hx-swap="outerHTML">
      <button class="ghost danger" title="Cancelar esta descarga">Cancelar</button>
    </form>
    """


def resource_row(kind: str, title: str, meta: str, resource: str) -> str:
    return f"""
    <button class="resource-row" hx-get="/partials/preview?resource={escape(resource)}" hx-target="#preview" hx-swap="innerHTML">
      <div class="resource-main">
        <strong>{escape(title)}</strong>
        <p class="muted">{escape(resource_kind_label(kind))} · {escape(meta)}</p>
      </div>
      <span>Revisar</span>
    </button>
    """


def preview_item_row(index: int, item: Track | Video) -> str:
    artist = item.artist.name if item.artist else ""
    if isinstance(item, Track):
        detail = f"{artist} · canción {item.trackNumber} · {item.audioQuality}"
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
        <span>Formato</span>
        <select name="output_format">
          <option value="raw">RAW</option>
          <option value="wav">WAV</option>
          <option value="mp3_320">MP3 320</option>
        </select>
      </label>
      <button class="primary">Iniciar descarga</button>
    </form>
    """


def resource_kind_label(kind: str, plural: bool = False) -> str:
    labels = {
        "playlist": ("Playlist", "playlists"),
        "album": ("Álbum", "álbumes"),
        "track": ("Canción", "canciones"),
    }
    singular_label, plural_label = labels.get(kind, (kind.title(), f"{kind}s"))
    return plural_label if plural else singular_label


def library_count_label(kind: str, visible: int, total: int) -> str:
    label = resource_kind_label(kind, plural=True)
    if total and visible < total:
        return f"Mostrando {visible} de {total} {label}"

    return f"{visible} {label}"


def job_status_label(status: str) -> str:
    labels = {
        "queued": "En cola",
        "running": "En curso",
        "canceling": "Cancelando",
        "canceled": "Cancelada",
        "done": "Completada",
        "failed": "Error",
    }
    return labels.get(status, status)


def display_result_status(status: str) -> str:
    clean_status = strip_rich(status).strip()
    labels = {
        "Downloaded": "Descargado",
        "Overwrited": "Sobrescrito",
        "Exists": "Ya existía",
    }
    return labels.get(clean_status, clean_status)


def is_error_status(status: str) -> bool:
    return status.startswith("Error")


def is_skipped_status(status: str) -> bool:
    return status.startswith("Skipped") or status.startswith("Omitido")


def format_file_count(count: int) -> str:
    return f"{count} archivo" if count == 1 else f"{count} archivos"


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
    canceling = [job for job in jobs if job.status == "canceling"]
    done = [job for job in jobs if job.status == "done"]
    canceled = [job for job in jobs if job.status == "canceled"]
    failed = [job for job in jobs if job.status == "failed"]
    active = (running or canceling)[0] if running or canceling else None
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
        <p>{len(running)} activas · {len(queued)} en cola · {len(canceling)} cancelando · {len(done)} completas · {len(canceled)} canceladas · {len(failed)} errores · log {escape(str(APP_PATH / "latest.log"))}</p>
      </div>
    </section>
    """


def render_status_message(message: str) -> str:
    return f"""
    <section id="status-bar" class="status-bar">
      <div>
        <strong>Terminal</strong>
        <p>{escape(message)}</p>
      </div>
      <div>
        <strong>Descarga actual</strong>
        <p>Ninguna</p>
      </div>
      <div>
        <strong>Progreso</strong>
        <p>Solicitud completada</p>
      </div>
    </section>
    """


def page() -> str:
    html = """
    <!doctype html>
    <html lang="es">
    <head>
      <meta charset="utf-8">
      <meta name="viewport" content="width=device-width, initial-scale=1">
      <title>Psybots Tiddl __APP_VERSION__</title>
      <script>
        (() => {
          const escapeHtml = (value) => String(value)
            .replace(/&/g, "&amp;")
            .replace(/</g, "&lt;")
            .replace(/>/g, "&gt;")
            .replace(/"/g, "&quot;");

          const everyDelay = (trigger) => {
            const match = trigger.match(/every\\s+([0-9.]+)s/);
            return match ? Number(match[1]) * 1000 : 0;
          };

          const swapHtml = (target, html, mode) => {
            if (!target) return null;
            if (mode === "outerHTML") {
              const template = document.createElement("template");
              template.innerHTML = html.trim();
              const next = template.content.firstElementChild;
              if (!next) return null;
              target.replaceWith(next);
              bind(next);
              return next;
            }

            target.innerHTML = html;
            bind(target);
            return target;
          };

          const request = async (el, method, url, body = null) => {
            const targetSelector = el.getAttribute("hx-target");
            const target = targetSelector ? document.querySelector(targetSelector) : el;
            const swapMode = el.getAttribute("hx-swap") || "innerHTML";
            el.setAttribute("aria-busy", "true");

            try {
              const response = await fetch(url, {
                method,
                body,
                headers: { "X-Requested-With": "tiddl-desktop" },
              });
              const html = await response.text();
              if (!response.ok) {
                throw new Error(html || response.statusText);
              }
              swapHtml(target, html, swapMode);
            } catch (error) {
              const message = escapeHtml(error.message || error);
              const html = `<p class="error">No se pudo completar la solicitud. ${message}</p>`;
              if (target) {
                target.insertAdjacentHTML("afterbegin", html);
              }
            } finally {
              el.removeAttribute("aria-busy");
            }
          };

          const initTrigger = (el) => {
            if (el.dataset.hxBound === "true") return;
            el.dataset.hxBound = "true";
            const trigger = el.getAttribute("hx-trigger") || "";
            const url = el.getAttribute("hx-get");
            if (!url) return;

            if (trigger.includes("load")) {
              request(el, "GET", url);
            }

            const delay = everyDelay(trigger);
            if (delay > 0) {
              const interval = window.setInterval(() => {
                if (!document.documentElement.contains(el)) {
                  window.clearInterval(interval);
                  return;
                }
                request(el, "GET", url);
              }, delay);
            }
          };

          const bind = (root = document) => {
            if (root.matches && root.matches("[hx-trigger]")) {
              initTrigger(root);
            }
            root.querySelectorAll?.("[hx-trigger]").forEach(initTrigger);
          };

          document.addEventListener("submit", (event) => {
            const form = event.target.closest("form[hx-post]");
            if (!form) return;
            event.preventDefault();
            request(form, "POST", form.getAttribute("hx-post"), new FormData(form));
          });

          document.addEventListener("click", (event) => {
            const el = event.target.closest("[hx-get], [hx-post]");
            if (!el || el.closest("form")) return;
            event.preventDefault();
            if (el.hasAttribute("hx-get")) {
              request(el, "GET", el.getAttribute("hx-get"));
            } else {
              request(el, "POST", el.getAttribute("hx-post"));
            }
          });

          document.addEventListener("DOMContentLoaded", () => bind(document));
        })();
      </script>
      <style>
        :root { color-scheme: light; --ink: #162029; --muted: #61707f; --line: #d7e0e7; --soft-line: #edf2f6; --panel: #eef3f7; --surface: #ffffff; --surface-soft: #f8fafc; --accent: #0b806c; --accent-hover: #066c5c; --danger: #b33a3a; --danger-bg: #fff1f1; --warn: #98690d; --focus: #85d6ca; --shadow: 0 14px 34px rgba(18, 35, 49, .08); }
        * { box-sizing: border-box; }
        html { height: 100%; background: #101820; }
        body { display: grid; grid-template-rows: auto auto minmax(0, 1fr) auto; height: 100%; margin: 0; font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; background: #f2f6f8; color: var(--ink); overflow: hidden; }
        header { min-height: 60px; display: flex; align-items: center; justify-content: space-between; gap: 16px; padding: 0 22px; border-bottom: 1px solid #243642; background: #101820; color: #f6fafb; }
        .app-subtitle { text-align: right; color: #b7c5cd; }
        .direct-bar { padding: 14px 20px; border-bottom: 1px solid var(--line); background: var(--surface); box-shadow: 0 8px 24px rgba(24, 35, 45, .04); z-index: 1; }
        main { display: grid; grid-template-columns: minmax(300px, 360px) minmax(560px, 1fr); min-height: 0; overflow: hidden; }
        aside { border-right: 1px solid var(--line); padding: 14px 12px; background: var(--panel); overflow: auto; }
        .workspace { display: grid; grid-template-rows: minmax(0, 1fr) minmax(210px, 34vh); min-height: 0; height: 100%; overflow: hidden; }
        section.preview-pane, section.queue-pane { min-height: 0; padding: 18px; overflow: auto; }
        section.preview-pane { border-bottom: 1px solid var(--line); }
        h1 { font-size: 18px; line-height: 1.2; margin: 0; white-space: nowrap; }
        .version-badge { display: inline-flex; align-items: center; height: 22px; padding: 0 8px; margin-left: 8px; border: 1px solid #375260; border-radius: 999px; font-size: 12px; color: #8ce0d1; background: #17242d; vertical-align: middle; }
        h2 { font-size: 16px; line-height: 1.25; margin: 0 0 6px; }
        h3 { font-size: 13px; line-height: 1.3; margin: 0 0 8px; }
        .muted { color: var(--muted); margin: 0; font-size: 13px; line-height: 1.45; }
        .panel { display: flex; align-items: center; justify-content: space-between; gap: 12px; padding: 12px; border: 1px solid var(--line); background: var(--surface); border-radius: 8px; margin-bottom: 12px; box-shadow: var(--shadow); }
        .actions, .tabs, form.inline { display: flex; gap: 8px; align-items: center; flex-wrap: wrap; }
        button, input, select { min-height: 38px; border: 1px solid var(--line); border-radius: 7px; background: var(--surface); color: var(--ink); padding: 0 11px; font: inherit; font-size: 14px; }
        input { min-width: 0; width: 100%; }
        button { cursor: pointer; font-weight: 600; transition: background .16s ease, border-color .16s ease, color .16s ease; }
        button:hover { border-color: #aab6bf; background: #f6f8fa; }
        [aria-busy="true"] { cursor: progress; opacity: .72; }
        button:focus-visible, input:focus-visible, select:focus-visible, a:focus-visible { outline: 3px solid var(--focus); outline-offset: 2px; }
        button.primary { background: var(--accent); color: white; border-color: var(--accent); }
        button.primary:hover { background: var(--accent-hover); border-color: var(--accent-hover); }
        button.ghost { min-height: 32px; background: transparent; }
        button.danger { color: var(--danger); border-color: #efc8c8; }
        button.danger:hover { background: var(--danger-bg); border-color: #e9aaaa; }
        .tabs { margin: 8px 0 4px; }
        .tabs button { min-width: 86px; background: #f9fbfd; }
        .link { color: var(--accent); font-size: 13px; font-weight: 600; }
        .library-list { display: grid; gap: 2px; margin-top: 8px; }
        .list-count { padding: 4px 2px 6px; }
        .resource-row, .job, .track-row { border-bottom: 1px solid var(--line); padding: 10px 0; }
        .resource-row { width: 100%; min-height: 52px; display: flex; justify-content: space-between; gap: 10px; align-items: center; text-align: left; border: 0; border-bottom: 1px solid var(--line); border-radius: 0; background: transparent; padding: 10px 4px; }
        .resource-main { min-width: 0; }
        .resource-main strong { display: block; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
        .resource-row > span { flex: 0 0 auto; color: var(--accent); font-size: 12px; font-weight: 700; }
        .resource-row:hover { background: #e8f4f1; padding-left: 10px; padding-right: 10px; border-radius: 7px; }
        .preview-card { border: 1px solid var(--line); border-radius: 8px; background: var(--surface); box-shadow: var(--shadow); }
        .preview-head { display: flex; justify-content: space-between; align-items: flex-start; gap: 16px; padding: 16px; border-bottom: 1px solid var(--soft-line); }
        .preview-head > div { min-width: 0; }
        .track-list { padding: 0 14px 6px; }
        .track-row { display: grid; grid-template-columns: 34px 1fr auto; gap: 12px; align-items: center; }
        .download-form, .compact-form { display: flex; gap: 8px; align-items: end; flex-wrap: wrap; }
        .download-form label, .compact-form label { display: grid; gap: 4px; font-size: 12px; color: var(--muted); }
        .compact-form select { width: 96px; }
        .compact-form label:first-of-type select { width: 150px; }
        .compact-form label:nth-of-type(2) select { width: 120px; }
        .manual-download { display: grid; gap: 8px; width: 100%; }
        .manual-download h2 { margin-bottom: 0; }
        .manual-download .settings { display: grid; grid-template-columns: minmax(300px, 1fr) minmax(190px, 240px) minmax(140px, 190px) minmax(120px, 150px) auto; gap: 10px; align-items: end; }
        .manual-download label { display: grid; gap: 4px; font-size: 12px; color: var(--muted); }
        .job-board { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 12px; }
        .job-column { min-width: 0; border: 1px solid var(--line); border-radius: 8px; padding: 12px; background: var(--surface); box-shadow: var(--shadow); }
        .job-top { display: flex; justify-content: space-between; gap: 12px; align-items: flex-start; }
        .job-top > div { min-width: 0; }
        .job-top strong { overflow-wrap: anywhere; }
        .job-actions { display: grid; gap: 6px; justify-items: end; }
        .cancel-form { margin: 0; }
        .notice-job { border-bottom: 0; padding-bottom: 0; }
        .badge { flex: 0 0 auto; font-size: 11px; border: 1px solid var(--line); border-radius: 999px; padding: 4px 8px; text-transform: uppercase; font-weight: 700; letter-spacing: .02em; background: var(--surface-soft); }
        .badge.done { color: var(--accent); border-color: var(--accent); }
        .badge.failed { color: var(--danger); border-color: var(--danger); }
        .badge.running { color: var(--warn); border-color: var(--warn); }
        .badge.canceling, .badge.canceled { color: #607184; border-color: #aebac5; }
        .meter { height: 6px; background: #e8ecef; border-radius: 999px; overflow: hidden; margin: 8px 0; }
        .meter span { display: block; height: 100%; background: var(--accent); }
        .job-facts { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 8px; margin: 10px 0; }
        .job-facts div { min-width: 0; }
        .job-facts dt { color: var(--muted); font-size: 11px; margin: 0 0 2px; }
        .job-facts dd { margin: 0; font-size: 13px; overflow-wrap: anywhere; }
        .job-path { display: grid; grid-template-columns: auto minmax(0, 1fr) auto; gap: 8px; align-items: center; padding: 8px; border: 1px solid var(--line); border-radius: 7px; background: var(--surface-soft); }
        .job-path span { color: var(--muted); font-size: 12px; }
        .job-path form, .result-row form { margin: 0; }
        .result-list { display: grid; gap: 8px; margin-top: 10px; }
        .result-row { display: grid; grid-template-columns: minmax(82px, auto) minmax(0, 1fr) auto; gap: 4px 8px; align-items: center; padding-bottom: 8px; border-bottom: 1px solid #eef1f3; }
        .result-row code { grid-column: 1 / -1; }
        .result-status { color: var(--muted); font-size: 12px; }
        code { font-size: 12px; word-break: break-all; }
        .error { color: var(--danger); font-size: 13px; margin: 8px 0 0; }
        .status-bar { height: 96px; display: grid; grid-template-columns: 1.4fr 1fr 1fr; gap: 16px; padding: 12px 20px; border-top: 1px solid var(--line); background: #101820; color: #f4f7f8; }
        .status-bar strong { display: block; font-size: 12px; color: #9fd7cc; margin-bottom: 4px; }
        .status-bar p { margin: 0; font-size: 13px; line-height: 1.45; color: #e1e7ea; overflow-wrap: anywhere; }
        @media (max-width: 920px) {
          body { display: block; height: auto; overflow: auto; }
          header { align-items: flex-start; flex-direction: column; gap: 4px; padding: 10px 20px; }
          h1 { white-space: normal; }
          .app-subtitle { text-align: left; }
          main { grid-template-columns: 1fr; height: auto; }
          section.workspace { grid-template-rows: auto auto; }
          aside { border-right: 0; border-bottom: 1px solid var(--line); }
          .panel, .preview-head { align-items: stretch; flex-direction: column; }
          .download-form, .compact-form { display: grid; grid-template-columns: 1fr; }
          .download-form select, .compact-form select, .compact-form label:first-of-type select, .compact-form label:nth-of-type(2) select { width: 100%; }
          .track-row { grid-template-columns: 34px 1fr; }
          .track-row form { grid-column: 1 / -1; }
          .job-board, .status-bar { grid-template-columns: 1fr; }
          .status-bar { height: auto; }
          .manual-download .settings { grid-template-columns: 1fr; }
          .job-path, .result-row { grid-template-columns: 1fr; }
        }
      </style>
    </head>
    <body>
      <header>
        <h1>Psybots Tiddl <span class="version-badge">__APP_VERSION__</span></h1>
        <span class="muted app-subtitle">Autor: Psybots · Aplicación de escritorio local · __APP_VERSION__</span>
      </header>
      <section class="direct-bar">
        <form class="manual-download" hx-post="/jobs" hx-target="#jobs" hx-swap="outerHTML">
          <h2>Descarga directa</h2>
          <div class="settings">
            <label>
              <span>Recurso</span>
              <input name="resource" placeholder="track/123, album/123 o playlist/uuid">
            </label>
            <label>
              <span>Calidad audio</span>
              <select name="track_quality" title="Calidad de streaming de audio">
                __TRACK_QUALITY_OPTIONS__
              </select>
            </label>
            <label>
              <span>Calidad video</span>
              <select name="video_quality" title="Calidad de streaming de video">
                __VIDEO_QUALITY_OPTIONS__
              </select>
            </label>
            <label>
              <span>Formato</span>
              <select name="output_format">
                <option value="raw">RAW</option>
                <option value="wav">WAV</option>
                <option value="mp3_320">MP3 320</option>
              </select>
            </label>
            <button class="primary">Iniciar descarga</button>
          </div>
        </form>
      </section>
      <main>
        <aside>
          <div hx-get="/partials/session" hx-trigger="load" hx-swap="outerHTML"></div>
          <section>
            <h2>Biblioteca</h2>
            <div class="tabs">
              <button hx-get="/partials/library?kind=playlist" hx-target="#library">Playlists</button>
              <button hx-get="/partials/library?kind=album" hx-target="#library">Álbumes</button>
              <button hx-get="/partials/library?kind=track" hx-target="#library">Canciones</button>
            </div>
            <div id="library" hx-get="/partials/library?kind=playlist" hx-trigger="load">
              <p class="muted">Cargando biblioteca...</p>
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
                    <p class="muted">Selecciona una playlist, álbum o canción para revisar su contenido antes de descargar.</p>
                  </div>
                </div>
              </section>
            </div>
          </section>
          <section class="queue-pane">
            <h2>Descargas</h2>
            <div hx-get="/partials/jobs" hx-trigger="load, every 2s" hx-target="#jobs" hx-swap="outerHTML">
              <section id="jobs" class="job-board">
                <div class="job-column"><h3>En curso</h3><p class="muted">Sin descargas activas.</p></div>
                <div class="job-column"><h3>Completadas</h3><p class="muted">Sin descargas completas.</p></div>
                <div class="job-column"><h3>Canceladas</h3><p class="muted">Sin cancelaciones.</p></div>
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
          <div><strong>Progreso</strong><p>0 activas · 0 en cola · 0 cancelando · 0 completas · 0 canceladas · 0 errores</p></div>
        </section>
      </div>
    </body>
    </html>
    """
    return (
        html.replace("__APP_VERSION__", APP_VERSION)
        .replace(
            "__TRACK_QUALITY_OPTIONS__", quality_options(CONFIG.download.track_quality)
        )
        .replace(
            "__VIDEO_QUALITY_OPTIONS__",
            video_quality_options(CONFIG.download.video_quality),
        )
    )


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


def run_desktop(
    host: str = "127.0.0.1", port: int = 8765, browser: bool = False
) -> None:
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

        webview.create_window(
            "Psybots Tiddl",
            f"http://{host}:{port}",
            width=1240,
            height=820,
        )
        webview.start(gui="qt")
    except Exception as exc:
        server.should_exit = True
        raise RuntimeError(
            "No se pudo iniciar la aplicación de escritorio con Qt. "
            "Reinstala con `uv tool install --force .` para incluir PySide6/Qt."
        ) from exc
    finally:
        server.should_exit = True
