"""Time-window queries must respect the actual instant, not a string tiebreak.

Notes store `created_at` as Python's `isoformat()` — `2026-07-13T12:00:00+00:00`,
with a `T` and an offset. SQLite's `datetime('now')` is `2026-07-13 12:00:00` —
a space, no offset. A raw string comparison of the two sorts by the date prefix
and then breaks ties on the separator (`T` > space), so a note created early on
the boundary day was misclassified. The fix compares via `julianday()` on both
sides, which parses either format and reduces to a real UTC instant.
"""

from datetime import datetime, timedelta, timezone

from verivann.config import Config
from verivann.library import _connect, mirror_rows, untouched_notes
from verivann.pipeline import run


def _iso_days_ago(days_ago: float) -> str:
    return (datetime.now(timezone.utc) - timedelta(days=days_ago)).isoformat()


def _stage_backdated(staging_dir, text, created_at) -> str:
    """Stage a real note (all columns valid), then move its clock to `created_at`."""
    event = run("text", ref="text", text=text, config=Config(staging_dir=staging_dir)).event
    con = _connect(staging_dir)
    try:
        con.execute("UPDATE notes SET created_at = ? WHERE id = ?", (created_at, event.id))
        con.commit()
    finally:
        con.close()
    return event.id


def test_mirror_counts_by_the_instant_not_the_calendar_day(tmp_path):
    staging = tmp_path / "s"
    # Both land on (or near) the boundary calendar day; only the time of day differs.
    _stage_backdated(staging, "just inside the 30-day window", _iso_days_ago(29.75))
    _stage_backdated(staging, "just outside the 30-day window", _iso_days_ago(30.25))

    m = mirror_rows(staging, days=30)

    assert m["notes"] == 1  # the 29.75-day-old note counts; the 30.25-day-old one does not


def test_untouched_uses_the_instant_at_the_boundary(tmp_path):
    staging = tmp_path / "s"
    inside = _stage_backdated(staging, "recent, not yet stale", _iso_days_ago(29.75))
    outside = _stage_backdated(staging, "past the threshold, never judged", _iso_days_ago(30.25))

    ids = {row["id"] for row in untouched_notes(staging, days=30)}

    assert outside in ids       # older than 30 days -> surfaced as untouched
    assert inside not in ids     # not yet 30 days old -> left alone


def test_a_clearly_old_note_is_outside_a_short_window(tmp_path):
    staging = tmp_path / "s"
    _stage_backdated(staging, "ancient", _iso_days_ago(90))
    _stage_backdated(staging, "fresh", _iso_days_ago(1))

    assert mirror_rows(staging, days=7)["notes"] == 1
    assert {r["id"] for r in untouched_notes(staging, days=7)}  # the 90-day note is untouched-old
