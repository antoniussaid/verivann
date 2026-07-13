"""Image / gallery capture via gallery-dl (GPL-2.0, external CLI/module).

For image hosts (Pinterest, imgur, flickr…) or direct image URLs. Downloads a
bounded number of images, then OCRs them (tesseract) so the note carries any
on-screen text — the useful part for a knowledge system. Activates only when
gallery-dl is available; otherwise the caller falls back.

gallery-dl is invoked as a subprocess (binary or `python -m gallery_dl`), never
imported — its GPL license stays with it.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
import uuid
from pathlib import Path
from urllib.parse import urlparse

from ..schema import Extracted
from .vision import ocr_image

_GALLERY_HOSTS = (
    "pinterest.com", "pinterest.de", "imgur.com", "flickr.com",
    "deviantart.com", "i.redd.it", "500px.com", "artstation.com",
)
_IMG_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp", ".tiff"}
_MAX_IMAGES = 12


def is_gallery_url(url: str) -> bool:
    host = (urlparse(url).hostname or "").lower()
    host = host[4:] if host.startswith("www.") else host
    if any(host == h or host.endswith("." + h) for h in _GALLERY_HOSTS):
        return True
    return any(urlparse(url).path.lower().endswith(e) for e in _IMG_EXTS)


def _gallery_cmd() -> list[str] | None:
    binary = shutil.which("gallery-dl")
    if binary:
        return [binary]
    try:
        proc = subprocess.run([sys.executable, "-m", "gallery_dl", "--version"], capture_output=True, timeout=15)
        if proc.returncode == 0:
            return [sys.executable, "-m", "gallery_dl"]
    except Exception:  # noqa: BLE001
        pass
    return None


def gallery_available() -> bool:
    return _gallery_cmd() is not None


def extract_gallery(url: str, work_base: Path | None) -> Extracted | None:
    cmd = _gallery_cmd()
    if cmd is None:
        return None
    base = Path(work_base) if work_base else Path("data/.subs")
    work = base / ("gal-" + uuid.uuid4().hex)
    try:
        work.mkdir(parents=True, exist_ok=True)
    except OSError:
        return None
    try:
        subprocess.run(
            cmd + ["--range", f"1-{_MAX_IMAGES}", "-D", str(work), url],
            capture_output=True,
            text=True,
            timeout=240,
        )
        images = sorted(p for p in work.rglob("*") if p.suffix.lower() in _IMG_EXTS)[:_MAX_IMAGES]
        if not images:
            return _fallback(url, "no images downloaded")

        ocr_parts = [t for t in (ocr_image(p) for p in images) if t]
        title = f"{len(images)} image(s) from {urlparse(url).hostname}"
        text = title
        if ocr_parts:
            text += "\n\n--- On-screen text (OCR) ---\n" + "\n\n".join(ocr_parts)
        return Extracted(
            title=title,
            text=text[:20000],
            meta={"url": url, "images": len(images), "ocr": bool(ocr_parts)},
        )
    except Exception:  # noqa: BLE001
        return _fallback(url, "gallery-dl failed")
    finally:
        shutil.rmtree(work, ignore_errors=True)


def _fallback(url: str, error: str) -> Extracted:
    return Extracted(
        title=url,
        text=f"[Image extraction limited — process manually]\nURL: {url}\nReason: {error}",
        meta={"url": url, "error": error, "fallback": True},
    )
