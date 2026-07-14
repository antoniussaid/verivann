"""Health of the external tools Verivann orchestrates but never bundles.

yt-dlp is the one that rots: video sites change constantly, so an old copy silently
returns empty transcripts. `vv doctor` reporting a bare "yes" hid that - a six-month-old
yt-dlp looked identical to a fresh one. This reports the version and its age, so the
single largest predicted support case ("my transcripts are empty") answers itself.
"""

from __future__ import annotations

import re
import shutil
import subprocess
from datetime import date

_STALE_AFTER_DAYS = 90  # yt-dlp ships often; older than a quarter is worth a nudge
_VERSION_RE = re.compile(r"(\d{4})\.(\d{2})\.(\d{2})")  # yt-dlp versions are dates


def ytdlp_version() -> str | None:
    """The installed yt-dlp version string, or None if it isn't on PATH / won't run."""
    if shutil.which("yt-dlp") is None:
        return None
    try:
        proc = subprocess.run(
            ["yt-dlp", "--version"], capture_output=True, text=True, timeout=15
        )
    except Exception:  # noqa: BLE001 - a tool that won't answer is treated as absent
        return None
    return proc.stdout.strip() if proc.returncode == 0 else None


def staleness_days(version: str, today: date) -> int | None:
    """How many days old a date-based version is, or None if it isn't a date version."""
    m = _VERSION_RE.search(version or "")
    if not m:
        return None
    try:
        released = date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    except ValueError:
        return None
    return max(0, (today - released).days)


def ytdlp_health(today: date, version: str | None = None) -> str:
    """One line for `vv doctor`: absent, fresh, or stale-with-a-fix."""
    if version is None:
        version = ytdlp_version()
    if version is None:
        return "no (youtube falls back)"
    age = staleness_days(version, today)
    if age is not None and age > _STALE_AFTER_DAYS:
        return f"{version} - {age} days old, run `yt-dlp -U` (stale versions return empty transcripts)"
    return version
