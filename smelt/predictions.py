"""The scoreboard.

The internet is full of confident people predicting things, and none of them are
ever checked, because nobody writes the prediction down with a date on it.

Smelt does. When a source says something about the future that could be judged
later, it goes on the record: the claim, the date it comes due, and who said it.
When the date arrives, Smelt asks you. Your verdict is written straight onto that
source's permanent record (sources.py).

Nothing here is automatic. Smelt does not decide who was right — that is a
judgment, and judgments belong to the human. What Smelt does is make forgetting
impossible.

    smelt predictions            what is open, what came due
    smelt resolve <id> --miss    "he was wrong"  → the source carries it forever
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path

_STATUS = ("open", "hit", "miss", "void")


@dataclass
class Prediction:
    id: int
    text: str
    due: str
    status: str
    note_id: str
    source_key: str
    source_label: str
    created_at: str

    @property
    def days_left(self) -> int:
        try:
            return (date.fromisoformat(self.due) - datetime.now(timezone.utc).date()).days
        except ValueError:
            return 0

    @property
    def is_due(self) -> bool:
        return self.status == "open" and self.days_left <= 0

    def line(self) -> str:
        when = (
            f"due {self.due} — {abs(self.days_left)} day(s) overdue"
            if self.is_due
            else f"due {self.due} (in {self.days_left} day(s))"
            if self.status == "open"
            else f"{self.status.upper()} · {self.due}"
        )
        return f"[{self.id}] {self.text}\n      {self.source_label} · {when}"


def record(
    note_id: str, source_key: str, predictions: list[dict], staging_dir: Path
) -> int:
    """Put a note's predictions on the record. Re-ingesting a source replaces them."""
    from .library import replace_predictions

    rows = [(p["text"], p["due"]) for p in predictions if p.get("text") and p.get("due")]
    return replace_predictions(note_id, source_key, rows, staging_dir)


def listing(staging_dir: Path, status: str = "", due_only: bool = False) -> list[Prediction]:
    from .library import prediction_rows

    items = [Prediction(**row) for row in prediction_rows(staging_dir)]
    if status:
        items = [p for p in items if p.status == status]
    if due_only:
        items = [p for p in items if p.is_due]
    # Due first, then by deadline.
    return sorted(items, key=lambda p: (not p.is_due, p.days_left))


def resolve(prediction_id: int, verdict: str, staging_dir: Path) -> Prediction | None:
    """Judge a prediction. hit/miss writes onto the source's record; void does not.

    A prediction that never came true is not a rounding error — it is the whole
    point of keeping the ledger.
    """
    if verdict not in ("hit", "miss", "void"):
        raise ValueError("verdict must be hit, miss or void")

    from .library import mark_source, set_prediction_status

    item = set_prediction_status(prediction_id, verdict, staging_dir)
    if item is None:
        return None
    prediction = Prediction(**item)
    if verdict in ("hit", "miss") and prediction.source_key:
        mark_source(prediction.source_key, "hits" if verdict == "hit" else "misses", staging_dir)
    return prediction
