"""Who said it — and what their record is.

Every other tool treats a source as an address. Smelt treats it as a party with a
history: a channel, a site, an author that has said things before, some of which
turned out to be wrong.

Two numbers, both computed from what the system already stores:

  record   hits and misses. A miss is written when one of this source's claims is
           later contradicted and the contradiction is resolved against it
           (see predictions.py / claims.py), or when it tried to manipulate the
           analyzer (see security.py — that is a permanent mark).

  yield    how much came out of how much went in: usable ideas per 10 minutes of
           material. A 40-minute video with three ideas is a bad trade, and after
           twenty videos the number says so out loud. Nobody ships this, because
           nobody wants to be measured by it.

Neither number is a verdict. Both are context you get BEFORE you read.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit

from .schema import Extracted

_WORDS_PER_MINUTE = 220  # reading speed for text material


def identify_ref(kind: str, canonical: str) -> tuple[str, str]:
    """The source's identity from the URL alone (used for backfilling old rows)."""
    if kind == "file":
        return "you:files", "your own files"
    if kind == "text" or not canonical.startswith(("http://", "https://")):
        return "you:pasted", "pasted by you"
    host = (urlsplit(canonical).hostname or "").lower()
    host = host[4:] if host.startswith("www.") else host
    return f"web:{host}", host


def identify(kind: str, canonical: str, extracted: Extracted) -> tuple[str, str]:
    """The source's identity, using extractor metadata when we have it.

    A channel is a source; the platform is not. `youtube:@3blue1brown` — not
    `web:youtube.com`, which would lump every video on earth into one party.
    """
    meta = extracted.meta or {}
    uploader = str(meta.get("uploader") or "").strip()
    platform = str(meta.get("extractor") or "").strip().lower()

    if uploader:
        handle = re.sub(r"\s+", "", uploader.lower())  # a backslash inside an f-string
        if platform:                                   # breaks on Python < 3.12 — keep it out
            platform = platform.replace(":tab", "").replace("generic", "web")
            return f"{platform}:@{handle}", f"{uploader} ({platform})"
        return f"web:@{handle}", uploader
    return identify_ref(kind, canonical)


def material_minutes(extracted: Extracted) -> float:
    """How much material this actually was — the denominator of `yield`."""
    meta = extracted.meta or {}
    duration = meta.get("duration")
    if isinstance(duration, (int, float)) and duration > 0:
        return round(duration / 60.0, 1)  # a video is as long as it is
    words = len(re.findall(r"\S+", extracted.text or ""))
    return round(max(words / _WORDS_PER_MINUTE, 0.1), 1)


def note_yield(ideas: int, minutes: float) -> float:
    """Usable ideas per 10 minutes of material."""
    if minutes <= 0:
        return 0.0
    return round(ideas / minutes * 10, 2)


@dataclass
class Standing:
    key: str
    label: str
    notes: int
    kept: int
    dropped: int
    minutes: float
    ideas: int
    analyzed: int  # notes an LLM actually read — a yield of 0 is meaningless without this
    hits: int
    misses: int
    hostile: int

    @property
    def yield_per_10min(self) -> float | None:
        """None = never actually analyzed. Absence of evidence is not evidence."""
        if not self.analyzed:
            return None
        return note_yield(self.ideas, self.minutes)

    @property
    def survival(self) -> float:
        """Share of judged notes from this source that you kept."""
        judged = self.kept + self.dropped
        return round(self.kept / judged, 2) if judged else 0.0

    def verdict(self) -> str:
        """One honest line, in the language a human would use."""
        if self.hostile:
            return "tried to manipulate the analyzer — do not trust"
        if self.misses and self.misses > self.hits:
            return f"has been wrong {self.misses}× (right {self.hits}×)"
        if self.hits and not self.misses:
            return f"has held up {self.hits}× so far"
        judged = self.kept + self.dropped
        if judged >= 3 and self.survival <= 0.34:
            return f"you drop most of it ({self.kept}/{judged} kept)"
        if judged >= 3 and self.survival >= 0.75:
            return f"you keep most of it ({self.kept}/{judged} kept)"
        rate = self.yield_per_10min
        if rate is not None and self.analyzed >= 3 and rate < 0.4:
            return f"low yield ({rate}/10min) — a lot of material, little substance"
        if not self.analyzed and self.notes >= 3:
            return "never analyzed (no model configured) — yield unknown"
        return "not enough signal yet"

    def yield_text(self) -> str:
        rate = self.yield_per_10min
        return "yield unknown (not analyzed)" if rate is None else f"{rate}/10min"


def standings(staging_dir: Path, limit: int = 30) -> list[Standing]:
    from .library import source_rows

    return [Standing(**row) for row in source_rows(staging_dir, limit)]
