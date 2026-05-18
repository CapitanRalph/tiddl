import hashlib
import os
import platform
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

import requests

from tiddl.cli.const import APP_PATH
from tiddl.version import APP_NAME, PACKAGE_VERSION

GITHUB_REPOSITORY = "CapitanRalph/tiddl"
GITHUB_LATEST_RELEASE_URL = (
    f"https://api.github.com/repos/{GITHUB_REPOSITORY}/releases/latest"
)
GITHUB_RELEASES_URL = f"https://github.com/{GITHUB_REPOSITORY}/releases"
REQUEST_TIMEOUT = (3, 8)


@dataclass(frozen=True)
class UpdateAsset:
    name: str
    url: str
    size: int = 0
    sha256: str = ""


@dataclass(frozen=True)
class UpdateInfo:
    current_version: str
    latest_version: str
    release_url: str
    notes: str
    platform_key: str
    asset: UpdateAsset | None
    available: bool
    message: str


def normalize_version(value: str) -> str:
    return value.strip().removeprefix("v").removeprefix("V")


def version_tuple(value: str) -> tuple[int, ...]:
    numbers = re.findall(r"\d+", normalize_version(value))
    return tuple(int(number) for number in numbers[:3]) or (0,)


def is_newer_version(latest: str, current: str) -> bool:
    latest_parts = version_tuple(latest)
    current_parts = version_tuple(current)
    size = max(len(latest_parts), len(current_parts))
    return latest_parts + (0,) * (size - len(latest_parts)) > current_parts + (0,) * (
        size - len(current_parts)
    )


def detect_platform_key() -> str:
    machine = platform.machine().lower()
    is_arm = machine in {"arm64", "aarch64"}

    if sys.platform == "darwin":
        return "macos-arm64" if is_arm else "macos-x64"

    if sys.platform.startswith("win"):
        return "windows-arm64" if is_arm else "windows-x64"

    if sys.platform.startswith("linux"):
        return "linux-arm64" if is_arm else "linux-x64"

    return f"{sys.platform}-{machine or 'unknown'}"


def release_asset_sha(asset: dict[str, Any]) -> str:
    digest = str(asset.get("digest") or "")
    if digest.startswith("sha256:"):
        return digest.removeprefix("sha256:")

    return ""


def asset_matches_platform(name: str, platform_key: str) -> bool:
    clean_name = name.lower()
    platform_tokens = {
        "macos-arm64": ["macos", "arm64"],
        "macos-x64": ["macos", "x64"],
        "windows-x64": ["windows", "x64"],
        "windows-arm64": ["windows", "arm64"],
        "linux-x64": ["linux", "x64"],
        "linux-arm64": ["linux", "arm64"],
    }.get(platform_key, [platform_key])

    if not all(token in clean_name for token in platform_tokens):
        return False

    suffixes = {
        "macos-arm64": (".pkg", ".dmg"),
        "macos-x64": (".pkg", ".dmg"),
        "windows-x64": (".exe", ".msi"),
        "windows-arm64": (".exe", ".msi"),
        "linux-x64": (".appimage", ".deb"),
        "linux-arm64": (".appimage", ".deb"),
    }.get(platform_key, ())

    return not suffixes or clean_name.endswith(suffixes)


def select_release_asset(
    assets: list[dict[str, Any]], platform_key: str
) -> UpdateAsset | None:
    for asset in assets:
        name = str(asset.get("name") or "")
        url = str(asset.get("browser_download_url") or "")
        if not name or not url:
            continue

        if asset_matches_platform(name, platform_key):
            return UpdateAsset(
                name=name,
                url=url,
                size=int(asset.get("size") or 0),
                sha256=release_asset_sha(asset),
            )

    return None


def fetch_latest_release(
    get: Callable[..., Any] = requests.get,
) -> dict[str, Any]:
    response = get(
        GITHUB_LATEST_RELEASE_URL,
        headers={"Accept": "application/vnd.github+json"},
        timeout=REQUEST_TIMEOUT,
    )
    response.raise_for_status()
    data = response.json()
    if not isinstance(data, dict):
        raise ValueError("GitHub no devolvió un release válido.")
    return data


def check_for_update(
    current_version: str = PACKAGE_VERSION,
    get: Callable[..., Any] = requests.get,
) -> UpdateInfo:
    platform_key = detect_platform_key()
    release = fetch_latest_release(get=get)
    latest_version = normalize_version(str(release.get("tag_name") or "0.0.0"))
    release_url = str(release.get("html_url") or GITHUB_RELEASES_URL)
    notes = str(release.get("body") or "")
    assets = release.get("assets") or []
    if not isinstance(assets, list):
        assets = []

    available = is_newer_version(latest_version, current_version)
    asset = select_release_asset(assets, platform_key) if available else None

    if not available:
        message = f"{APP_NAME} está actualizado."
    elif asset:
        message = f"Disponible {latest_version} para {platform_key}."
    else:
        message = (
            f"Disponible {latest_version}, pero no hay instalador para "
            f"{platform_key} en GitHub Releases."
        )

    return UpdateInfo(
        current_version=current_version,
        latest_version=latest_version,
        release_url=release_url,
        notes=notes,
        platform_key=platform_key,
        asset=asset,
        available=available,
        message=message,
    )


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def download_update_asset(
    asset: UpdateAsset,
    destination_dir: Path | None = None,
    get: Callable[..., Any] = requests.get,
) -> Path:
    destination_dir = destination_dir or APP_PATH / "updates"
    destination_dir.mkdir(parents=True, exist_ok=True)
    target = destination_dir / asset.name
    partial = target.with_suffix(f"{target.suffix}.download")

    with get(asset.url, stream=True, timeout=REQUEST_TIMEOUT) as response:
        response.raise_for_status()
        with partial.open("wb") as file:
            for chunk in response.iter_content(chunk_size=1024 * 1024):
                if chunk:
                    file.write(chunk)

    if asset.sha256:
        actual = sha256_file(partial)
        if actual.lower() != asset.sha256.lower():
            partial.unlink(missing_ok=True)
            raise ValueError("El instalador descargado no pasó la verificación SHA256.")

    shutil.move(str(partial), target)
    return target


def open_installer(path: Path) -> None:
    if sys.platform == "darwin":
        subprocess.Popen(["open", str(path)])
        return

    if sys.platform.startswith("win"):
        os.startfile(path)  # type: ignore[attr-defined]
        return

    if path.suffix.lower() == ".appimage":
        path.chmod(path.stat().st_mode | 0o111)

    subprocess.Popen(["xdg-open", str(path)])


def download_and_open_update(
    get: Callable[..., Any] = requests.get,
    destination_dir: Path | None = None,
) -> tuple[UpdateInfo, Path | None]:
    info = check_for_update(get=get)
    if not info.available or not info.asset:
        return info, None

    installer = download_update_asset(
        info.asset, destination_dir=destination_dir, get=get
    )
    open_installer(installer)
    return info, installer
