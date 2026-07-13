"""Behaviour is a verdict you did not have to type.

We killed the friction at capture and then re-introduced it at judgment: `keep` /
`drop` on every note is exactly the chore that makes people abandon tools like
this. So Smelt watches what you actually do instead.

    accept     you copied it into a real folder      → kept,   weight 1.00
    highlight  you marked a passage in it            → kept,   weight 1.00
    open       you opened it again, later            → kept,   weight 0.40
    click      you searched, and clicked this one    → kept,   weight 0.30
    ignored    30+ days: never judged, never touched → dropped, weight 0.25

Two rules keep this honest:

1. **An inferred verdict never overwrites one you gave.** Guessing may fill a
   silence; it may not contradict you (enforced in `library.record_feedback`).
2. **Silence is weak evidence, and is weighted like it.** A note you ignored for a
   month counts a quarter of a note you explicitly threw away. The learned profile
   (relevance.py) sums weights, so a hundred silences never shout down one verdict.

`smelt review` shows the implied drops and lets you overrule them in one pass —
the cheapest judgment loop we can build.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

# What a signal means, and how much of a verdict it is worth.
WEIGHTS: dict[str, tuple[str, float]] = {
    "accept": ("kept", 1.0),
    "highlight": ("kept", 1.0),
    "open": ("kept", 0.4),
    "click": ("kept", 0.3),
    "ignored": ("dropped", 0.25),
}

IGNORED_AFTER_DAYS = 30


def observe(note_id: str, kind: str, staging_dir: Path) -> None:
    """Record something the human did — and let it speak, quietly, as a verdict."""
    if kind not in WEIGHTS:
        return
    from .library import add_signal, record_feedback

    add_signal(note_id, kind, staging_dir)
    verdict, weight = WEIGHTS[kind]
    origin = "accept" if kind in ("accept", "highlight") else "implicit"
    record_feedback(note_id, verdict, staging_dir, origin=origin, weight=weight)


@dataclass
class Implied:
    id: str
    title: str
    source: str
    domain: str
    created_at: str
    days: int


def implied_drops(staging_dir: Path, days: int = IGNORED_AFTER_DAYS) -> list[Implied]:
    """Notes your silence has already judged — offered back for confirmation."""
    from datetime import date, datetime, timezone

    from .library import untouched_notes

    today = datetime.now(timezone.utc).date()
    out: list[Implied] = []
    for row in untouched_notes(staging_dir, days):
        try:
            age = (today - date.fromisoformat(row["created_at"][:10])).days
        except ValueError:
            age = days
        out.append(
            Implied(
                id=row["id"], title=row["title"], source=row["source"],
                domain=row["domain"], created_at=row["created_at"], days=age,
            )
        )
    return out


def sweep(staging_dir: Path, days: int = IGNORED_AFTER_DAYS) -> int:
    """Write the quiet verdict for everything you have ignored long enough.

    Called by `smelt review --sweep` and by the cockpit — never silently at intake,
    because a tool that judges your notes behind your back is not a tool you can trust.
    """
    from .library import record_feedback

    count = 0
    for item in implied_drops(staging_dir, days):
        verdict, weight = WEIGHTS["ignored"]
        if record_feedback(item.id, verdict, staging_dir, origin="implicit", weight=weight):
            count += 1
    return count
