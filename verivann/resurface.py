"""What you saved, forgot, and need right now.

A library only pays you back if it interrupts you. Yours does not: it waits to be
searched, which means it only ever gives you what you already remembered you had.

`verivann resurface` goes the other way. It takes what you are working on *now* — your
open questions, and the material you have digested this week — and looks for notes
you **kept months ago** that speak to it. Not "related notes"; forgotten ones. A
note you saw yesterday is not a discovery.

Nothing here needs a model: it is retrieval (hybrid when an embedder is configured)
plus one rule that most tools are too polite to apply — *recent things do not count*.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timezone

from .config import Config

FORGOTTEN_AFTER_DAYS = 30


@dataclass
class Resurfaced:
    id: str
    title: str
    source: str
    age_days: int
    because: str  # the question or the recent note that pulled it back up

    def line(self) -> str:
        months = self.age_days // 30
        when = f"{months} month(s) ago" if months else f"{self.age_days} days ago"
        return f"{self.title[:60]}  _(kept {when}, {self.source[:24]})_"


def resurface(config: Config | None = None, limit: int = 5) -> list[Resurfaced]:
    config = config or Config.load()
    from .library import kept_rows, recent
    from .questions import listing as questions
    from .retrieval import retrieve

    kept = {row["id"]: row for row in kept_rows(config.staging_dir, limit=500)}
    if not kept:
        return []

    today = datetime.now(timezone.utc).date()
    prompts: list[tuple[str, str]] = [(q.text, f"your question “{q.text[:44]}”") for q in questions(config)]
    prompts += [
        (f"{h.title} {h.text[:400]}", f"what you digested recently: “{h.title[:40]}”")
        for h in recent(config.staging_dir, limit=3)
    ]

    seen: set[str] = set()
    out: list[Resurfaced] = []
    for query, because in prompts:
        for hit in retrieve(query, config, limit=6).hits:
            row = kept.get(hit.id)
            if row is None or hit.id in seen:
                continue
            age = _age(row["created_at"], today)
            if age < FORGOTTEN_AFTER_DAYS:
                continue  # you saw it last week. That is not a discovery.
            seen.add(hit.id)
            out.append(
                Resurfaced(
                    id=hit.id, title=row["title"], source=row["source"],
                    age_days=age, because=because,
                )
            )
            if len(out) >= limit:
                return out
    return out


def _age(created_at: str, today: date) -> int:
    try:
        return (today - date.fromisoformat(created_at[:10])).days
    except ValueError:
        return 0
