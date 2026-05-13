from types import SimpleNamespace

from fastapi.testclient import TestClient

from tiddl.cli.utils.auth import AuthData
from tiddl.core.api.models import Track
from tiddl.web.app import (
    DownloadJob,
    JobResult,
    WebState,
    clamp_concurrency,
    clean_path_segment,
    create_app,
    finalize_job,
    format_bytes,
    get_all_web_playlists,
    page,
    render_job,
    strip_rich,
    web_playlist_folder,
    web_playlist_item_filename,
)


def test_session_panel_prompts_for_login(monkeypatch):
    monkeypatch.setattr("tiddl.web.app.load_auth_data", lambda: AuthData())

    client = TestClient(create_app(WebState()))
    response = client.get("/partials/session")

    assert response.status_code == 200
    assert "Not signed in" in response.text
    assert "Sign in" in response.text


def test_jobs_panel_renders_empty_queue():
    client = TestClient(create_app(WebState()))
    response = client.get("/partials/jobs")

    assert response.status_code == 200
    assert "Sin descargas en cola" in response.text


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
    assert "1/2 items" in response.text


def test_page_renders_direct_download_full_width():
    html = page()

    assert '<section class="direct-bar">' in html
    assert html.index("Descarga directa") < html.index("<main>")


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
        JobResult(title="Track", path="/tmp/tiddl/playlist/My Playlist/001. Track.flac", status="Downloaded")
    )

    html = render_job(job)

    assert "job-facts" in html
    assert "job-path" in html
    assert "/tmp/tiddl/playlist/My Playlist" in html
    assert "result-row" in html


def test_strip_rich_removes_known_tags():
    assert strip_rich("[green]Downloaded[/] [blue]Track") == "Downloaded Track"


def test_format_bytes_scales_units():
    assert format_bytes(1536) == "1.5 KB"


def test_clamp_concurrency_limits_to_three():
    assert clamp_concurrency(0) == 1
    assert clamp_concurrency(2) == 2
    assert clamp_concurrency(9) == 3


def test_web_playlist_folder_is_sanitized():
    playlist = SimpleNamespace(title='My: Playlist / 2026.', uuid="uuid")

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
        get_user_and_favorite_playlists=lambda offset=0: first if offset == 0 else second
    )

    playlists = get_all_web_playlists(api)

    assert [playlist.uuid for playlist in playlists] == ["one", "two", "three"]


def test_finalize_job_without_files_marks_failed():
    job = DownloadJob(id="abc", resource="playlist/test")

    finalize_job(job)

    assert job.status == "failed"
    assert "No se descargó ningún archivo" in job.error


def test_finalize_job_with_file_marks_done():
    job = DownloadJob(id="abc", resource="playlist/test")
    job.results.append(JobResult(title="Track", path="/tmp/track.flac", status="Downloaded"))

    finalize_job(job)

    assert job.status == "done"
    assert "1 files" in job.message


def test_finalize_job_with_skipped_items_keeps_successful_job_done():
    job = DownloadJob(id="abc", resource="playlist/test")
    job.results.append(JobResult(title="Track", path="/tmp/track.flac", status="Downloaded"))
    job.results.append(JobResult(title="Video", path="", status="Skipped filtrado"))

    finalize_job(job)

    assert job.status == "done"
    assert "1 files" in job.message


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
