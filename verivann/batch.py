"""Batch intake - digest a whole playlist / channel at once.

Uses yt-dlp's flat listing to enumerate entries (no download), then runs each
through the normal pipeline. Always bounded by `limit` so a channel with
thousands of videos can never run away.
"""

from __future__ import annotations

import json
import shutil
import subprocess

from .config import Config
from .pipeline import IntakeResult, run


def list_entries(url: str, limit: int = 20) -> list[str]:
    """Enumerate the URLs behind a playlist/channel. Empty on any failure."""
    from .net import check_url  # batch is not behind the pipeline chokepoint

    if shutil.which("yt-dlp") is None or check_url(url):
        return []
    try:
        proc = subprocess.run(
            ["yt-dlp", "--flat-playlist", "--dump-single-json", "--no-warnings",
             "--playlist-end", str(limit), "--", url],
            capture_output=True,
            text=True,
            timeout=180,
        )
        if proc.returncode != 0:
            return []
        data = json.loads(proc.stdout)
    except Exception:  # noqa: BLE001
        return []

    urls: list[str] = []
    for entry in (data.get("entries") or [])[:limit]:
        ref = entry.get("url") or entry.get("webpage_url") or entry.get("id")
        if not ref:
            continue
        ref = str(ref)
        if not ref.startswith("http"):
            ref = f"https://www.youtube.com/watch?v={ref}"
        urls.append(ref)
    return urls


def ingest_batch(url: str, limit: int = 10, config: Config | None = None) -> list[IntakeResult]:
    config = config or Config.load()
    results: list[IntakeResult] = []
    for entry in list_entries(url, limit):
        try:
            results.append(run("url", ref=entry, config=config))
        except Exception:  # noqa: BLE001 - one bad entry must not kill the batch
            continue
    return results
