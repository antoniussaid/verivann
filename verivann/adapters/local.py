"""The material that never leaves your machine.

Three sources nobody routes, and everybody has:

  screenshots   Hundreds of them. You took each one because it mattered for four
                seconds, and you will never open the folder again. OCR + routing
                turns them into something searchable — this is the cheapest,
                largest pile of forgotten value on any device.
  voice memos   The fastest path from a thought to a note: say it, Whisper writes
                it, the router routes it.
  documents     PDFs and EPUBs — papers, books, contracts, invoices.

All local, all optional, all degrading cleanly: no tesseract → no OCR; no Whisper
→ no transcript; no PDF reader → a note that says so, rather than nothing.
"""

from __future__ import annotations

import re
import zipfile
from pathlib import Path

from ..schema import Extracted

IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp", ".tif", ".tiff"}
AUDIO_SUFFIXES = {".mp3", ".m4a", ".wav", ".ogg", ".opus", ".flac", ".aac", ".m4b"}
DOC_SUFFIXES = {".pdf", ".epub", ".txt", ".md"}

SUPPORTED = IMAGE_SUFFIXES | AUDIO_SUFFIXES | DOC_SUFFIXES


def extract_file(path: Path) -> Extracted:
    """One entry point for anything on disk."""
    suffix = path.suffix.lower()
    if suffix in IMAGE_SUFFIXES:
        return extract_image(path)
    if suffix in AUDIO_SUFFIXES:
        return extract_audio(path)
    if suffix == ".pdf":
        return extract_pdf(path)
    if suffix == ".epub":
        return extract_epub(path)
    return Extracted(
        title=path.stem,
        text=path.read_text(encoding="utf-8", errors="ignore"),
        meta={"file": str(path), "kind": "text-file"},
    )


# ---------- images ----------

def extract_image(path: Path) -> Extracted:
    from .vision import ocr_available, ocr_image

    if not ocr_available():
        return Extracted(
            title=path.stem,
            text=f"[Image — no OCR available. Install tesseract to read it.]\nFile: {path}",
            meta={"file": str(path), "kind": "image", "ocr": False},
        )
    text = (ocr_image(path) or "").strip()
    return Extracted(
        title=_title_from_text(text) or path.stem,
        text=text or f"[Image — no readable text found]\nFile: {path}",
        meta={"file": str(path), "kind": "image", "ocr": True, "chars": len(text)},
    )


# ---------- audio ----------

def extract_audio(path: Path) -> Extracted:
    from .transcribe import enabled, transcribe_file

    if not enabled():
        return Extracted(
            title=path.stem,
            text=f"[Audio — transcription is off. Set VERIVANN_WHISPER_MODEL to read it.]\nFile: {path}",
            meta={"file": str(path), "kind": "audio", "has_transcript": False},
        )
    text, lang = transcribe_file(path)
    text = (text or "").strip()
    return Extracted(
        title=_title_from_text(text) or path.stem,
        text=text or f"[Audio — nothing transcribed]\nFile: {path}",
        meta={
            "file": str(path), "kind": "audio",
            "transcript": lang, "transcript_source": "whisper",
            "has_transcript": bool(text), "transcript_text": text or None,
        },
    )


# ---------- documents ----------

def extract_pdf(path: Path) -> Extracted:
    """`pdftotext` if installed (fast, exact); else pypdf; else an honest note."""
    text = _pdf_via_poppler(path) or _pdf_via_pypdf(path)
    if text is None:
        return Extracted(
            title=path.stem,
            text=(
                "[PDF — no reader available. Install poppler (pdftotext) or "
                f"`pip install pypdf` to read it.]\nFile: {path}"
            ),
            meta={"file": str(path), "kind": "pdf", "read": False},
        )
    return Extracted(
        title=_title_from_text(text) or path.stem,
        text=text,
        meta={"file": str(path), "kind": "pdf", "read": True, "chars": len(text)},
    )


def _pdf_via_poppler(path: Path) -> str | None:
    import shutil
    import subprocess

    if shutil.which("pdftotext") is None:
        return None
    try:
        proc = subprocess.run(
            ["pdftotext", "-layout", str(path), "-"], capture_output=True, text=True, timeout=120
        )
    except Exception:  # noqa: BLE001
        return None
    return proc.stdout.strip() or None if proc.returncode == 0 else None


def _pdf_via_pypdf(path: Path) -> str | None:
    try:
        from pypdf import PdfReader
    except ImportError:
        return None
    try:
        reader = PdfReader(str(path))
        pages = [page.extract_text() or "" for page in reader.pages[:80]]
    except Exception:  # noqa: BLE001 - encrypted or broken PDFs are not a crash
        return None
    return "\n".join(p.strip() for p in pages if p.strip()) or None


def extract_epub(path: Path) -> Extracted:
    """An EPUB is a zip of HTML. No dependency needed beyond what we already use."""
    try:
        from bs4 import BeautifulSoup
    except ImportError:
        return Extracted(
            title=path.stem,
            text=f"[EPUB — needs beautifulsoup4 to read.]\nFile: {path}",
            meta={"file": str(path), "kind": "epub", "read": False},
        )
    chunks: list[str] = []
    title = ""
    try:
        with zipfile.ZipFile(path) as book:
            names = [n for n in book.namelist() if n.lower().endswith((".xhtml", ".html", ".htm"))]
            for name in names[:60]:
                soup = BeautifulSoup(book.read(name), "html.parser")
                if not title and soup.title and soup.title.string:
                    title = soup.title.string.strip()
                chunks.append(soup.get_text(" ", strip=True))
    except (zipfile.BadZipFile, OSError):
        return Extracted(
            title=path.stem,
            text=f"[EPUB — unreadable file]\nFile: {path}",
            meta={"file": str(path), "kind": "epub", "read": False},
        )
    text = "\n".join(c for c in chunks if c)
    return Extracted(
        title=title or path.stem,
        text=text,
        meta={"file": str(path), "kind": "epub", "read": True, "chars": len(text)},
    )


def _title_from_text(text: str) -> str:
    """The first real line — a screenshot's headline, a memo's first sentence."""
    for line in (text or "").splitlines():
        line = re.sub(r"\s+", " ", line).strip()
        if len(line) >= 12:
            return line[:90]
    return ""
