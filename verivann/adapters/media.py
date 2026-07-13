"""Media adapter — metadata, description AND existing captions via yt-dlp.

Order of preference (cheap → expensive): fetch a platform's existing
subtitles/auto-captions first (yt-dlp, json3 preferred — clean text). Only if
none exist would local transcription (Whisper) be needed — that is a later
adapter (ROADMAP v0.4). Full visual extraction is v0.6.

yt-dlp runs as a subprocess — optional and swappable — with clean fallbacks.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import uuid
from pathlib import Path

from .. import mediapolicy
from ..schema import Extracted

_MAX_TRANSCRIPT = 20000  # cap stored transcript length


def extract_media(url: str, subs_dir: Path | None = None, ask=None) -> Extracted:
    """`ask` is how an interactive caller (the CLI, the app) answers VERIVANN_MEDIA=ask.

    Without it — a scheduled run, a server, a background job — "ask" means no.
    Silence is never consent.
    """
    if shutil.which("yt-dlp") is None:
        return _fallback(url, "yt-dlp not installed (metadata unavailable)")

    try:
        proc = subprocess.run(
            ["yt-dlp", "--dump-single-json", "--no-warnings", "--skip-download", url],
            capture_output=True,
            text=True,
            timeout=90,
        )
        if proc.returncode != 0:
            return _fallback(url, f"yt-dlp error: {proc.stderr.strip()[:200]}")
        data = json.loads(proc.stdout)
    except Exception as exc:  # noqa: BLE001 - fail soft on any extraction problem
        return _fallback(url, f"yt-dlp failed: {exc}")

    title = data.get("title", "") or url
    description = data.get("description", "") or ""

    # Cheap first: read the captions the platform already published. This touches no
    # media file at all — the words were already there, in text form.
    transcript, tlang, cues = _fetch_subtitles(url, subs_dir)
    source = "captions" if transcript else None

    # Only if there are none: ask the POLICY (mediapolicy.py) whether the audio may be
    # fetched at all. The default is "yes, but only to transcribe it, and delete it at
    # once" — and whatever is decided is written into the note, so there is a record.
    decision = mediapolicy.decide(has_captions=bool(transcript), asked=ask, url=url)
    media_note = decision.note

    if not transcript and decision.allowed:
        from .transcribe import maybe_transcribe

        transcript, tlang = maybe_transcribe(url, subs_dir)
        if transcript:
            source = "whisper"
        else:
            media_note = (
                "No transcript could be produced (local transcription is off — "
                "set VERIVANN_WHISPER_MODEL). Nothing was kept."
            )

    meta = {
        "url": url,
        "extractor": data.get("extractor_key") or data.get("extractor"),
        "uploader": data.get("uploader"),
        "duration": data.get("duration"),
        "upload_date": data.get("upload_date"),
        "view_count": data.get("view_count"),
        "description": description,
        "transcript": tlang,  # language of the transcript, or None
        "transcript_source": source,  # "captions" | "whisper" | None
        "has_transcript": bool(transcript),
        "transcript_text": transcript[:_MAX_TRANSCRIPT] if transcript else None,
        # The record of what was actually done to this source, and under whose rule.
        "media_policy": mediapolicy.mode(),
        "media_note": media_note,
    }

    # Timed transcript: keep the timeline the captions already carry, so the note
    # points back into the video instead of flattening it into a wall of text.
    if cues:
        blocks = group_cues(cues)
        meta["transcript_cues"] = [[t, text] for t, text in blocks][:400]
        meta["transcript_seek"] = seek_template(url)

    if transcript:
        # Description gives context; the transcript is the substance.
        body = f"{description}\n\n--- Transcript ({tlang}) ---\n{transcript}".strip()
    else:
        body = f"{title}\n\n{description}".strip()

    # Opt-in: OCR what's shown on screen (keyframes). Heavy; needs ffmpeg+tesseract.
    from .vision import video_onscreen_text

    onscreen = video_onscreen_text(url, subs_dir)
    if onscreen:
        meta["onscreen_text"] = onscreen[:8000]
        body = f"{body}\n\n--- On-screen text (OCR) ---\n{onscreen}".strip()

    return Extracted(title=title, text=body[:_MAX_TRANSCRIPT], meta=meta)


# ---------- subtitles ----------

def _fetch_subtitles(
    url: str, subs_dir: Path | None
) -> tuple[str | None, str | None, list[tuple[int, str]]]:
    base = Path(subs_dir) if subs_dir else Path("data/.subs")
    work = base / uuid.uuid4().hex
    try:
        work.mkdir(parents=True, exist_ok=True)
    except OSError:
        return None, None, []
    try:
        subprocess.run(
            [
                "yt-dlp", "--skip-download", "--write-subs", "--write-auto-subs",
                "--sub-langs", "en.*,de.*", "--sub-format", "json3/vtt/best",
                "--no-warnings", "-o", str(work / "%(id)s.%(ext)s"), url,
            ],
            capture_output=True,
            text=True,
            timeout=120,
        )
        files = list(work.glob("*.json3")) + list(work.glob("*.vtt"))
        if not files:
            return None, None, []
        path = _pick_subtitle(files)
        raw = path.read_text(encoding="utf-8", errors="ignore")
        cues = _json3_to_cues(raw) if path.suffix == ".json3" else _vtt_to_cues(raw)
        text = "\n".join(line for _, line in cues).strip()
        lang = _lang_from_name(path.name)
        return (text or None), (lang if text else None), (cues if text else [])
    except Exception:  # noqa: BLE001 - captions are best-effort
        return None, None, []
    finally:
        shutil.rmtree(work, ignore_errors=True)


def _pick_subtitle(files: list[Path]) -> Path:
    def score(p: Path) -> tuple[int, int]:
        lang = _lang_from_name(p.name)
        fmt = 0 if p.suffix == ".json3" else 1  # prefer json3 (clean)
        lang_pref = 0 if lang.startswith("en") else 1 if lang.startswith("de") else 2
        return (fmt, lang_pref)

    return sorted(files, key=score)[0]


def _lang_from_name(name: str) -> str:
    # e.g. "abc123.en.json3" -> "en"
    parts = name.split(".")
    return parts[-2] if len(parts) >= 3 else "?"


def _json3_to_cues(raw: str) -> list[tuple[int, str]]:
    """[(second, line)] — json3 carries per-event start times; keep them."""
    try:
        data = json.loads(raw)
    except ValueError:
        return []
    cues: list[tuple[int, str]] = []
    for event in data.get("events", []):
        segs = event.get("segs", []) or []
        line = "".join(seg.get("utf8", "") for seg in segs).replace("\n", " ").strip()
        if line and (not cues or cues[-1][1] != line):  # drop rolling-caption repeats
            cues.append((int(event.get("tStartMs", 0)) // 1000, line))
    return cues


def _vtt_to_cues(raw: str) -> list[tuple[int, str]]:
    cues: list[tuple[int, str]] = []
    current = 0
    for line in raw.splitlines():
        line = line.strip()
        if "-->" in line:
            current = _vtt_seconds(line.split("-->")[0].strip())
            continue
        if (
            not line
            or line == "WEBVTT"
            or line.startswith(("Kind:", "Language:", "NOTE"))
            or re.fullmatch(r"\d+", line)
        ):
            continue
        line = re.sub(r"<[^>]+>", "", line).replace("&nbsp;", " ").strip()
        if line and (not cues or cues[-1][1] != line):
            cues.append((current, line))
    return cues


def _vtt_seconds(stamp: str) -> int:
    match = re.match(r"(?:(\d+):)?(\d{1,2}):(\d{2})(?:[.,](\d{1,3}))?", stamp)
    if not match:
        return 0
    hours, minutes, seconds = match.group(1) or 0, match.group(2), match.group(3)
    return int(hours) * 3600 + int(minutes) * 60 + int(seconds)


def group_cues(cues: list[tuple[int, str]], window: int = 20) -> list[tuple[int, str]]:
    """Merge caption fragments into readable blocks, one per `window` seconds."""
    blocks: list[tuple[int, str]] = []
    start, buffer = None, []
    for t, line in cues:
        if start is None:
            start = t
        buffer.append(line)
        if t - start >= window:
            blocks.append((start, " ".join(buffer).strip()))
            start, buffer = None, []
    if buffer and start is not None:
        blocks.append((start, " ".join(buffer).strip()))
    return blocks


def timestamp(seconds: int) -> str:
    h, rest = divmod(max(0, int(seconds)), 3600)
    m, s = divmod(rest, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m:02d}:{s:02d}"


def seek_template(url: str) -> str | None:
    """A URL pattern that jumps to a second — only where the platform supports it."""
    low = url.lower()
    if "youtube.com" in low or "youtu.be" in low:
        sep = "&" if "?" in url else "?"
        return f"{url}{sep}t={{t}}s"
    return None


def _fallback(url: str, error: str) -> Extracted:
    return Extracted(
        title=url,
        text=f"[Media extraction limited — process manually]\nURL: {url}\nReason: {error}",
        meta={"url": url, "error": error, "fallback": True},
    )
