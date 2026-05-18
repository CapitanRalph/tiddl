from types import SimpleNamespace

from fastapi.testclient import TestClient

import tiddl.web.app as web_app
from tiddl.cli.utils.auth import AuthData
from tiddl.core.api.models import Track
from tiddl.web.app import (
    DownloadJob,
    JobResult,
    WebState,
    clamp_concurrency,
    clean_path_segment,
    configure_download_root,
    create_app,
    finalize_canceled_job,
    finalize_job,
    format_bytes,
    get_all_web_playlists,
    page,
    parse_supported_resource,
    render_file_explorer,
    render_library,
    render_job,
    request_job_cancel,
    save_download_root_config,
    strip_rich,
    web_playlist_folder,
    web_playlist_item_filename,
)


def test_session_panel_prompts_for_login(monkeypatch):
    monkeypatch.setattr("tiddl.web.app.load_auth_data", lambda: AuthData())

    client = TestClient(create_app(WebState()))
    response = client.get("/partials/session")

    assert response.status_code == 200
    assert "Conecta tu cuenta de TIDAL" in response.text
    assert "Iniciar sesión" in response.text


def test_jobs_panel_renders_empty_queue():
    client = TestClient(create_app(WebState()))
    response = client.get("/partials/jobs")

    assert response.status_code == 200
    assert "Sin descargas activas" in response.text


def test_jobs_panel_renders_existing_job():
    state = WebState()
    state.jobs["abc"] = DownloadJob(
        id="abc",
        resource="track/123",
        status="running",
        message="Downloading",
        total=2,
        completed=1,
    )

    client = TestClient(create_app(state))
    response = client.get("/partials/jobs")

    assert response.status_code == 200
    assert "track/123" in response.text
    assert "1/2 ítems" in response.text


def test_page_renders_direct_download_full_width():
    html = page()

    assert "Tiddl DDJ" in html
    assert html.count("Psybots") == 1
    assert "/assets/tiddl-ddj-logo.png" in html
    assert '<section class="direct-bar">' in html
    assert html.index("Descarga directa") < html.index("<main>")
    assert "__TRACK_QUALITY_OPTIONS__" not in html
    assert "HIGH - FLAC 16-bit/44.1 kHz" in html
    assert "unpkg.com" not in html
    assert "X-Requested-With" in html


def test_update_panel_uses_github_release_status(monkeypatch):
    monkeypatch.setattr(
        "tiddl.web.app.check_for_update",
        lambda: SimpleNamespace(
            available=True,
            latest_version="1.2.0",
            release_url="https://github.com/CapitanRalph/tiddl/releases/tag/v1.2.0",
            asset=SimpleNamespace(name="Tiddl-DDJ-v1.2.0-Windows-x64-Setup.exe"),
        ),
    )

    client = TestClient(create_app(WebState()))
    response = client.get("/partials/update")

    assert response.status_code == 200
    assert "1.2.0 disponible" in response.text
    assert "/update/install" in response.text


def test_file_explorer_renders_download_root(monkeypatch, tmp_path):
    (tmp_path / "playlist" / "My Playlist").mkdir(parents=True)
    (tmp_path / "playlist" / "My Playlist" / "001 - Track.flac").write_bytes(b"data")
    monkeypatch.setattr("tiddl.web.app.explorer_root", lambda: tmp_path)

    html = render_file_explorer()

    assert "Ruta de descargas" in html
    assert "playlist" in html
    assert "1 playlists detectadas" in html


def test_configure_download_root_updates_runtime_and_persists(monkeypatch, tmp_path):
    saved = []
    monkeypatch.setattr(
        web_app.CONFIG.download,
        "download_path",
        web_app.CONFIG.download.download_path,
    )
    monkeypatch.setattr(
        web_app.CONFIG.download,
        "scan_path",
        web_app.CONFIG.download.scan_path,
    )
    monkeypatch.setattr("tiddl.web.app.save_download_root_config", saved.append)

    root = configure_download_root(str(tmp_path))

    assert root == tmp_path.resolve()
    assert saved == [tmp_path.resolve()]


def test_save_download_root_config_updates_download_section(tmp_path):
    config_file = tmp_path / "config.toml"
    config_file.write_text("[download]\nthreads_count = 4\n")

    save_download_root_config(tmp_path / "Music" / "Tiddl DDJ", config_file)

    text = config_file.read_text()
    assert 'download_path = "' in text
    assert 'scan_path = "' in text
    assert "threads_count = 4" in text


def test_job_card_renders_aligned_download_details():
    job = DownloadJob(
        id="abc",
        resource="playlist/123",
        status="running",
        message="Downloading",
        total=2,
        completed=1,
        bytes_downloaded=1536,
        target_path="/tmp/tiddl/playlist/My Playlist",
    )
    job.results.append(
        JobResult(
            title="Track",
            path="/tmp/tiddl/playlist/My Playlist/001. Track.flac",
            status="Downloaded",
        )
    )

    html = render_job(job)

    assert "job-facts" in html
    assert "job-path" in html
    assert "/tmp/tiddl/playlist/My Playlist" in html
    assert "result-row" in html
    assert "/jobs/abc/cancel" in html


def test_strip_rich_removes_known_tags():
    assert strip_rich("[green]Downloaded[/] [blue]Track") == "Downloaded Track"


def test_format_bytes_scales_units():
    assert format_bytes(1536) == "1.5 KB"


def test_clamp_concurrency_limits_to_three():
    assert clamp_concurrency(0) == 1
    assert clamp_concurrency(2) == 2
    assert clamp_concurrency(9) == 3


def test_parse_supported_resource_returns_friendly_error():
    try:
        parse_supported_resource("not-a-resource")
    except ValueError as exc:
        assert "track/123" in str(exc)
    else:
        raise AssertionError("Expected invalid resources to raise ValueError")


def test_create_job_invalid_resource_renders_notice():
    client = TestClient(create_app(WebState()))
    response = client.post("/jobs", data={"resource": "not-a-resource"})

    assert response.status_code == 200
    assert "No se pudo iniciar" in response.text
    assert "track/123" in response.text


def test_create_job_requires_session(monkeypatch):
    monkeypatch.setattr("tiddl.web.app.load_auth_data", lambda: AuthData())

    client = TestClient(create_app(WebState()))
    response = client.post("/jobs", data={"resource": "track/123"})

    assert response.status_code == 200
    assert "Inicia sesión con TIDAL" in response.text


def test_preview_invalid_resource_renders_message():
    client = TestClient(create_app(WebState()))
    response = client.get("/partials/preview?resource=not-a-resource")

    assert response.status_code == 200
    assert "Recurso no válido" in response.text
    assert "track/123" in response.text


def test_web_playlist_folder_is_sanitized():
    playlist = SimpleNamespace(title="My: Playlist / 2026.", uuid="uuid")

    assert web_playlist_folder(playlist).as_posix() == "playlist/My Playlist 2026"
    assert clean_path_segment("...") == "_"


def test_web_playlist_item_filename_is_flat_and_indexed():
    playlist = SimpleNamespace(
        title="Playlist",
        uuid="uuid",
        created="2026-01-01T00:00:00",
        lastUpdated="2026-01-01T00:00:00",
    )
    track = make_track()

    filename = web_playlist_item_filename(
        item=track,
        album=None,
        playlist=playlist,
        playlist_index=7,
        track_quality="high",
        video_quality="fhd",
    )

    assert filename.as_posix() == "007 - Artist - Track"


def test_web_playlist_item_filename_keeps_track_version():
    playlist = SimpleNamespace(
        title="Playlist",
        uuid="uuid",
        created="2026-01-01T00:00:00",
        lastUpdated="2026-01-01T00:00:00",
    )
    track = make_track()
    track.version = "Extended Mix"

    filename = web_playlist_item_filename(
        item=track,
        album=None,
        playlist=playlist,
        playlist_index=7,
        track_quality="high",
        video_quality="fhd",
    )

    assert filename.as_posix() == "007 - Artist - Track (Extended Mix)"


def test_get_all_web_playlists_paginates_and_deduplicates():
    first = SimpleNamespace(
        limit=2,
        totalNumberOfItems=3,
        items=[
            SimpleNamespace(playlist=SimpleNamespace(uuid="one", title="One")),
            SimpleNamespace(playlist=SimpleNamespace(uuid="two", title="Two")),
        ],
    )
    second = SimpleNamespace(
        limit=2,
        totalNumberOfItems=3,
        items=[
            SimpleNamespace(playlist=SimpleNamespace(uuid="two", title="Two")),
            SimpleNamespace(playlist=SimpleNamespace(uuid="three", title="Three")),
        ],
    )
    api = SimpleNamespace(
        get_user_and_favorite_playlists=lambda offset=0: (
            first if offset == 0 else second
        )
    )

    playlists = get_all_web_playlists(api)

    assert [playlist.uuid for playlist in playlists] == ["one", "two", "three"]


def test_render_library_limits_track_favorites_for_fast_initial_load():
    favorites = SimpleNamespace(
        model_dump=lambda: {
            "TRACK": [str(index) for index in range(55)],
            "ALBUM": [],
            "PLAYLIST": [],
        }
    )

    def get_track(resource_id):
        return SimpleNamespace(
            id=resource_id,
            title=f"Track {resource_id}",
            artist=SimpleNamespace(name="Artist"),
        )

    api = SimpleNamespace(get_favorites=lambda: favorites, get_track=get_track)

    html = render_library(api, "track")

    assert "Mostrando 50 de 55 canciones" in html
    assert "Track 49" in html
    assert "Track 54" not in html


def test_finalize_job_without_files_marks_failed():
    job = DownloadJob(id="abc", resource="playlist/test")

    finalize_job(job)

    assert job.status == "failed"
    assert "No se descargó ningún archivo" in job.error


def test_finalize_job_with_file_marks_done():
    job = DownloadJob(id="abc", resource="playlist/test")
    job.results.append(
        JobResult(title="Track", path="/tmp/track.flac", status="Downloaded")
    )

    finalize_job(job)

    assert job.status == "done"
    assert "1 archivo" in job.message


def test_finalize_job_with_skipped_items_keeps_successful_job_done():
    job = DownloadJob(id="abc", resource="playlist/test")
    job.results.append(
        JobResult(title="Track", path="/tmp/track.flac", status="Downloaded")
    )
    job.results.append(JobResult(title="Video", path="", status="Omitido: filtrado"))

    finalize_job(job)

    assert job.status == "done"
    assert "1 archivo" in job.message


def test_render_job_progress_is_clamped():
    job = DownloadJob(
        id="abc",
        resource="track/123",
        status="running",
        message="Downloading",
        total=1,
        completed=3,
    )

    html = render_job(job)

    assert "width: 100%" in html


def test_request_job_cancel_marks_job_as_canceling():
    job = DownloadJob(id="abc", resource="playlist/123", status="running")

    did_cancel = request_job_cancel(job)

    assert did_cancel is True
    assert job.cancel_requested is True
    assert job.status == "canceling"
    assert "Cancelación solicitada" in job.terminal[-1]


def test_finalize_canceled_job_sets_terminal_state():
    job = DownloadJob(id="abc", resource="playlist/123", status="canceling")

    finalize_canceled_job(job)

    assert job.status == "canceled"
    assert job.message == "Cancelada por el usuario"
    assert job.active_items == {}


def test_cancel_job_endpoint_marks_existing_job_canceling():
    state = WebState()
    state.jobs["abc"] = DownloadJob(
        id="abc",
        resource="playlist/123",
        status="running",
    )

    client = TestClient(create_app(state))
    response = client.post("/jobs/abc/cancel")

    assert response.status_code == 200
    assert state.jobs["abc"].cancel_requested is True
    assert "Cancelando" in response.text


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
            "artists": [{"id": 1, "name": "Artist", "type": "MAIN"}],
            "artist": {"id": 1, "name": "Artist", "type": "MAIN"},
            "album": {"id": 1, "title": "Album"},
        }
    )
