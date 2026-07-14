"""What is due.

Thirty commands is a toolbox, not a product. This is the one screen a person can
be expected to look at: what came due, what is rotting, what your silence has
already decided, and what the tool itself got wrong.

    verivann          → the cockpit

It is deliberately capped. If it does not fit on one screen it is just another
report nobody reads, and the whole point was to stop building those.

"Since you last looked" is real: the timestamp is stored (`state.last_seen`), so
the cockpit can distinguish between the world and the news.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone

from .config import Config

_LAST_SEEN = "cockpit.last_seen"


@dataclass
class Cockpit:
    due_predictions: list = field(default_factory=list)
    unjudged: int = 0
    implied_drops: int = 0
    stale_claims: int = 0
    questions_moved: list = field(default_factory=list)
    hostile_sources: list = field(default_factory=list)
    changed_sources: list = field(default_factory=list)
    calibration: str = ""
    unanalyzed: int = 0
    last_seen: str = ""

    @property
    def quiet(self) -> bool:
        return not (
            self.due_predictions
            or self.implied_drops
            or self.stale_claims
            or self.questions_moved
            or self.hostile_sources
            or self.changed_sources
        )

    def headline(self) -> str:
        """The one line. Ordered by what is URGENT, not by what is embarrassing.

        A prediction that came due is time-bound; a missing model is merely a
        standing shame, and it will still be there tomorrow.
        """
        if self.due_predictions:
            n = len(self.due_predictions)
            return f"{n} prediction(s) have come due. Somebody said something would happen. Did it?"
        if self.hostile_sources:
            return f"{len(self.hostile_sources)} source(s) tried to give your analyzer orders."
        if self.changed_sources:
            return f"{len(self.changed_sources)} source(s) changed after you read them."
        if self.unanalyzed and self.unanalyzed == self.unjudged and self.unjudged:
            return (
                f"{self.unjudged} note(s) sit unread and unjudged. No model is configured, "
                "so nothing has actually been read - set VERIVANN_LLM before building more."
            )
        if self.implied_drops:
            return (
                f"{self.implied_drops} note(s) you have ignored for a month. "
                "Your silence has judged them; confirm it with `verivann review`."
            )
        if self.stale_claims:
            return f"{self.stale_claims} claim(s) are past their shelf life - what you believe may be old."
        if self.unjudged:
            return f"{self.unjudged} note(s) never judged. The router learns from nothing else."
        return "Nothing is due. The ledger is clean."


def load(config: Config | None = None) -> Cockpit:
    config = config or Config.load()
    staging = config.staging_dir

    from .library import get_state, source_rows, stale_claims, watch_rows
    from .predictions import listing as predictions
    from .questions import listing as questions
    from .signals import implied_drops

    view = Cockpit(last_seen=get_state(_LAST_SEEN, staging))

    view.due_predictions = [p for p in predictions(staging) if p.is_due]
    view.stale_claims = len(stale_claims(staging, limit=200))
    view.implied_drops = len(implied_drops(staging))
    view.questions_moved = [q for q in questions(config) if q.evidence or q.against]
    view.hostile_sources = [s for s in source_rows(staging, limit=200) if s["hostile"]]
    view.changed_sources = [w for w in watch_rows(staging) if w["changes"]]

    _counts(view, staging)
    view.calibration = _calibration_line(staging)
    return view


def _counts(view: Cockpit, staging) -> None:
    from .library import _connect  # the cockpit is allowed to look inside its own house

    con = _connect(staging)
    try:
        view.unjudged = con.execute(
            """SELECT COUNT(*) FROM notes n LEFT JOIN feedback f ON f.note_id = n.id
               WHERE f.note_id IS NULL"""
        ).fetchone()[0]
        view.unanalyzed = con.execute(
            "SELECT COUNT(*) FROM notes WHERE engine IS NULL OR engine NOT LIKE 'llm:%'"
        ).fetchone()[0]
    finally:
        con.close()


def _calibration_line(staging) -> str:
    from .calibrate import calibrate

    report = calibrate(staging)
    return report.headline() if report.enough else ""


def mark_seen(config: Config | None = None) -> None:
    config = config or Config.load()
    from .library import set_state

    set_state(_LAST_SEEN, datetime.now(timezone.utc).isoformat(), config.staging_dir)
