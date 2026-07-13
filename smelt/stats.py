"""The mirror.

Every tool in this space is built to make you feel productive: look how much you
saved, look at your beautiful graph. None of them will tell you the one number
that matters — **how much of what you consumed survived contact with your own
judgment.**

    smelt mirror     hours in, notes out, how many you kept, where the time went
    smelt slag       everything you dropped (the anti-library)

There is no encouragement here and no streak counter. Just the ledger. If it says
you spent eleven hours on a channel and kept nothing, that is not a bug in the
report.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class Mirror:
    days: int
    notes: int = 0
    minutes: float = 0.0
    kept: int = 0
    dropped: int = 0
    unjudged: int = 0
    analyzed: int = 0
    ideas: int = 0
    tasks: int = 0  # actions proposed
    hostile: int = 0
    by_kind: dict[str, int] = field(default_factory=dict)
    time_sinks: list[tuple[str, float, int]] = field(default_factory=list)  # (source, minutes, kept)

    @property
    def hours(self) -> float:
        return round(self.minutes / 60, 1)

    @property
    def judged(self) -> int:
        return self.kept + self.dropped

    @property
    def survival(self) -> float | None:
        """Of what you actually judged, how much did you keep?"""
        return round(self.kept / self.judged, 2) if self.judged else None

    def verdict(self) -> str:
        """One sentence. It is allowed to be unpleasant."""
        if not self.notes:
            return "Nothing digested in this period."
        if not self.judged:
            return (
                f"{self.hours} h of material became {self.notes} notes — and you have judged "
                "none of them. Nothing has been kept, nothing dropped: the library is a pile."
            )
        if self.kept == 0:
            return (
                f"{self.hours} h in, {self.judged} notes judged, {self.kept} kept. "
                "You kept nothing. That is the honest yield of this period."
            )
        share = int((self.survival or 0) * 100)
        return (
            f"{self.hours} h of material → {self.notes} notes → {self.kept} kept "
            f"({share}% of what you judged). {self.unjudged} note(s) you never looked at again."
        )


def mirror(staging_dir: Path, days: int = 30) -> Mirror:
    from .library import mirror_rows

    data = mirror_rows(staging_dir, days)
    return Mirror(days=days, **data)


@dataclass
class Slag:
    id: str
    title: str
    source: str
    domain: str
    reason: str
    created_at: str


def slag(staging_dir: Path, limit: int = 30) -> list[Slag]:
    """The anti-library: what you decided was not worth keeping."""
    from .library import dropped_rows

    return [Slag(**row) for row in dropped_rows(staging_dir, limit)]
