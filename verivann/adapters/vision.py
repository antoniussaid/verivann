"""Visual extraction — OCR of images and video keyframes via external tools.

- `ocr_image`: tesseract (Apache-2.0) on an image → on-screen text.
- `video_onscreen_text`: ffmpeg samples keyframes from a video, each is OCR'd.
  Opt-in (`VERIVANN_VISUAL`) because sampling + OCR per video is heavy.

Both are external CLIs (never bundled/imported). Any failure returns "" so the
pipeline never breaks.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import uuid
from pathlib import Path

_IMG_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp", ".tiff"}


def ocr_available() -> bool:
    return shutil.which("tesseract") is not None


def ocr_image(path: Path) -> str:
    if not ocr_available():
        return ""
    try:
        proc = subprocess.run(["tesseract", str(path), "stdout"], capture_output=True, text=True, timeout=60)
    except Exception:  # noqa: BLE001
        return ""
    return proc.stdout.strip() if proc.returncode == 0 else ""


def visual_enabled() -> bool:
    return os.environ.get("VERIVANN_VISUAL", "").strip().lower() in ("1", "true", "yes", "on")


def video_onscreen_text(url: str, work_base: Path | None, max_frames: int = 6) -> str:
    """Sample keyframes from a video and OCR them. Opt-in + tools required."""
    if (
        not visual_enabled()
        or not ocr_available()
        or shutil.which("ffmpeg") is None
        or shutil.which("yt-dlp") is None
    ):
        return ""
    base = Path(work_base) if work_base else Path("data/.subs")
    work = base / ("vis-" + uuid.uuid4().hex)
    try:
        work.mkdir(parents=True, exist_ok=True)
    except OSError:
        return ""
    try:
        video = _download_video(url, work)
        if video is None:
            return ""
        frames = _keyframes(video, work, max_frames)
        seen: set[str] = set()
        out: list[str] = []
        for frame in frames:
            text = ocr_image(frame)
            key = text[:60]
            if text and key not in seen:
                seen.add(key)
                out.append(text)
        return "\n".join(out).strip()
    except Exception:  # noqa: BLE001
        return ""
    finally:
        shutil.rmtree(work, ignore_errors=True)


def _download_video(url: str, work: Path) -> Path | None:
    proc = subprocess.run(
        ["yt-dlp", "-f", "worst[ext=mp4]/worst", "--no-warnings", "-o", str(work / "v.%(ext)s"), "--", url],
        capture_output=True,
        text=True,
        timeout=300,
    )
    if proc.returncode != 0:
        return None
    vids = [p for p in work.iterdir() if p.is_file()]
    return vids[0] if vids else None


def _keyframes(video: Path, work: Path, n: int) -> list[Path]:
    subprocess.run(
        ["ffmpeg", "-i", str(video), "-vf", "fps=1/8,scale=640:-1", "-frames:v", str(n),
         str(work / "f%03d.png"), "-y"],
        capture_output=True,
        text=True,
        timeout=240,
    )
    return sorted(work.glob("f*.png"))[:n]
