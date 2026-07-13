"""Local transcription fallback (Whisper) — opt-in, provider-neutral.

Runs ONLY when captions are absent AND `SMELT_WHISPER_MODEL` is set. Downloads
the audio via yt-dlp and transcribes it. Two backends, tried in order:
  - faster-whisper (MIT, pip) if importable
  - whisper.cpp binary (MIT) via SMELT_WHISPER_CPP + SMELT_WHISPER_CPP_MODEL

Heavy and slow on weak hardware — that's why it is opt-in. Any failure returns
(None, None) so the pipeline degrades cleanly.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import uuid
from pathlib import Path


def _model_name() -> str:
    return os.environ.get("SMELT_WHISPER_MODEL", "").strip()


def enabled() -> bool:
    return bool(_model_name())


def maybe_transcribe(url: str, work_base: Path | None) -> tuple[str | None, str | None]:
    if not enabled() or shutil.which("yt-dlp") is None:
        return None, None
    base = Path(work_base) if work_base else Path("data/.subs")
    work = base / ("stt-" + uuid.uuid4().hex)
    try:
        work.mkdir(parents=True, exist_ok=True)
    except OSError:
        return None, None
    try:
        audio = _download_audio(url, work)
        if audio is None:
            return None, None
        return _transcribe(audio)
    except Exception:  # noqa: BLE001 - transcription is best-effort
        return None, None
    finally:
        shutil.rmtree(work, ignore_errors=True)


def _download_audio(url: str, work: Path) -> Path | None:
    proc = subprocess.run(
        ["yt-dlp", "-f", "bestaudio/best", "--no-warnings", "-o", str(work / "audio.%(ext)s"), url],
        capture_output=True,
        text=True,
        timeout=300,
    )
    if proc.returncode != 0:
        return None
    files = [p for p in work.iterdir() if p.is_file()]
    return files[0] if files else None


def transcribe_file(audio: Path) -> tuple[str | None, str | None]:
    """Transcribe a local file — a voice memo, a recorded call, a lecture."""
    if not enabled() or not audio.is_file():
        return None, None
    try:
        return _transcribe(audio)
    except Exception:  # noqa: BLE001 - transcription is best-effort, always
        return None, None


def _transcribe(audio: Path) -> tuple[str | None, str | None]:
    text, lang = _via_faster_whisper(audio)
    if text is not None:
        return text, lang
    return _via_whisper_cpp(audio)


def _via_faster_whisper(audio: Path) -> tuple[str | None, str | None]:
    try:
        from faster_whisper import WhisperModel
    except ImportError:
        return None, None
    try:
        model = WhisperModel(_model_name(), device="cpu", compute_type="int8")
        segments, info = model.transcribe(str(audio))
        text = " ".join(seg.text.strip() for seg in segments).strip()
        return (text or None), getattr(info, "language", None)
    except Exception:  # noqa: BLE001
        return None, None


def _via_whisper_cpp(audio: Path) -> tuple[str | None, str | None]:
    binary = os.environ.get("SMELT_WHISPER_CPP", "").strip()
    model = os.environ.get("SMELT_WHISPER_CPP_MODEL", "").strip()
    if not binary or not model or shutil.which(binary) is None:
        return None, None
    out = audio.with_suffix("")  # whisper.cpp writes <out>.txt with -otxt
    proc = subprocess.run(
        [binary, "-m", model, "-f", str(audio), "-otxt", "-of", str(out), "-nt"],
        capture_output=True,
        text=True,
        timeout=1800,
    )
    txt = out.with_suffix(".txt")
    if proc.returncode != 0 or not txt.is_file():
        return None, None
    return (txt.read_text(encoding="utf-8", errors="ignore").strip() or None), None
