from fastapi.testclient import TestClient

from tiddl.cli.utils.auth import AuthData
from tiddl.web.app import DownloadJob, WebState, create_app, format_bytes, strip_rich


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
    assert "No downloads queued" in response.text


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


def test_strip_rich_removes_known_tags():
    assert strip_rich("[green]Downloaded[/] [blue]Track") == "Downloaded Track"


def test_format_bytes_scales_units():
    assert format_bytes(1536) == "1.5 KB"
