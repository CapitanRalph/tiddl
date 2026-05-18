from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QImage


ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "tiddl" / "web" / "assets" / "tiddl-ddj-logo.png"
OUTPUT_DIR = ROOT / "build" / "installer-icons"


def save_icon(image: QImage, size: int, path: Path, fmt: str) -> None:
    scaled = image.scaled(
        size,
        size,
        Qt.AspectRatioMode.KeepAspectRatio,
        Qt.TransformationMode.SmoothTransformation,
    )
    if not scaled.save(str(path), fmt):
        raise RuntimeError(f"No se pudo crear el icono: {path}")


def main() -> None:
    image = QImage(str(SOURCE))
    if image.isNull():
        raise RuntimeError(f"No se pudo leer el logo base: {SOURCE}")

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    save_icon(image, 256, OUTPUT_DIR / "tiddl-ddj.ico", "ICO")
    save_icon(image, 1024, OUTPUT_DIR / "tiddl-ddj.icns", "ICNS")


if __name__ == "__main__":
    main()
