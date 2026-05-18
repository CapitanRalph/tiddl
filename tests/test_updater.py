from hashlib import sha256

from tiddl.updater import (
    UpdateAsset,
    asset_matches_platform,
    check_for_update,
    download_update_asset,
    is_newer_version,
    select_release_asset,
)


class FakeResponse:
    def __init__(self, data=None, chunks=None) -> None:
        self.data = data or {}
        self.chunks = chunks or []

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False

    def raise_for_status(self) -> None:
        return None

    def json(self):
        return self.data

    def iter_content(self, chunk_size: int):
        del chunk_size
        yield from self.chunks


def test_is_newer_version_handles_two_digit_patch():
    assert is_newer_version("1.1.10", "1.1.9") is True
    assert is_newer_version("1.1.9", "1.1.10") is False


def test_asset_matches_platform_by_name_and_extension():
    assert asset_matches_platform(
        "Tiddl-DDJ-v1.2.0-Windows-x64-Setup.exe", "windows-x64"
    )
    assert asset_matches_platform("Tiddl-DDJ-v1.2.0-macOS-arm64.pkg", "macos-arm64")
    assert not asset_matches_platform("Tiddl-DDJ-v1.2.0-macOS-x64.pkg", "macos-arm64")


def test_select_release_asset_returns_platform_installer():
    asset = select_release_asset(
        [
            {
                "name": "Tiddl-DDJ-v1.2.0-macOS-arm64.pkg",
                "browser_download_url": "https://example.test/mac.pkg",
                "size": 123,
                "digest": "sha256:abc",
            }
        ],
        "macos-arm64",
    )

    assert asset == UpdateAsset(
        name="Tiddl-DDJ-v1.2.0-macOS-arm64.pkg",
        url="https://example.test/mac.pkg",
        size=123,
        sha256="abc",
    )


def test_check_for_update_uses_github_release(monkeypatch):
    monkeypatch.setattr("tiddl.updater.detect_platform_key", lambda: "windows-x64")

    def get(*_, **__):
        return FakeResponse(
            {
                "tag_name": "v1.2.0",
                "html_url": "https://github.com/CapitanRalph/tiddl/releases/tag/v1.2.0",
                "body": "Notas",
                "assets": [
                    {
                        "name": "Tiddl-DDJ-v1.2.0-Windows-x64-Setup.exe",
                        "browser_download_url": "https://example.test/setup.exe",
                    }
                ],
            }
        )

    info = check_for_update(current_version="1.1.10", get=get)

    assert info.available is True
    assert info.latest_version == "1.2.0"
    assert info.asset
    assert info.asset.name.endswith("Setup.exe")


def test_download_update_asset_verifies_sha256(tmp_path):
    data = b"installer"
    digest = sha256(data).hexdigest()

    def get(*_, **__):
        return FakeResponse(chunks=[data])

    path = download_update_asset(
        UpdateAsset(
            name="Tiddl-DDJ-v1.2.0-Linux-x64.AppImage",
            url="https://example.test/app.AppImage",
            sha256=digest,
        ),
        destination_dir=tmp_path,
        get=get,
    )

    assert path.read_bytes() == data
