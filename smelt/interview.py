"""When it does not know, it should ask — once.

The router guesses. It has always guessed: low confidence, pick the best keyword
match, move on, and the note quietly ends up in `inbox` where it dies. But the
person who knows the answer is sitting right there, and the answer costs them one
keystroke.

    smelt clarify

Every note whose routing was genuinely uncertain (confidence below the floor, or
two open questions equally plausible) carries a pending question with 2–4 concrete
options. `clarify` walks them: one keypress each. The answer re-routes the note —
and, more importantly, becomes training signal exactly where it is worth the most,
which is the case the router could not do on its own.

We ask at most one question per note, and never about material you have already
judged. A tool that interrogates you is worse than one that guesses.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

UNSURE_BELOW = 0.4


@dataclass
class Pending:
    note_id: str
    title: str
    reason: str
    options: list[str] = field(default_factory=list)  # domains and/or "question:<id>"
    labels: list[str] = field(default_factory=list)


def uncertain(staging_dir: Path, domains: list[str], questions=None, limit: int = 20) -> list[Pending]:
    """Notes the router could not route with a straight face."""
    from .library import _connect

    con = _connect(staging_dir)
    try:
        rows = con.execute(
            """SELECT n.id, n.title, n.domain, n.confidence
               FROM notes n LEFT JOIN feedback f ON f.note_id = n.id
               WHERE f.note_id IS NULL AND (n.confidence < ? OR n.domain = 'inbox')
               ORDER BY n.created_at DESC LIMIT ?""",
            (UNSURE_BELOW, limit),
        ).fetchall()
    finally:
        con.close()

    pending: list[Pending] = []
    for row in rows:
        options = [d for d in domains if d != "inbox"][:3]
        labels = [f"route to `{d}`" for d in options]
        for q in (questions or [])[:2]:
            options.append(f"question:{q.id}")
            labels.append(f"evidence for “{q.text[:40]}”")
        options.append("drop")
        labels.append("noise — drop it")
        pending.append(
            Pending(
                note_id=row["id"],
                title=row["title"],
                reason=(
                    f"routed to `{row['domain']}` with confidence {row['confidence']} — a guess"
                ),
                options=options,
                labels=labels,
            )
        )
    return pending


def answer(note_id: str, choice: str, staging_dir: Path) -> str:
    """Apply the human's answer. Returns a one-line description of what happened."""
    from .library import _connect, evidence_add, log_event, record_feedback

    if choice == "drop":
        record_feedback(note_id, "dropped", staging_dir, origin="explicit")
        log_event("clarify", note_id, "dropped", staging_dir)
        return "dropped — and the router now knows what that looked like"

    if choice.startswith("question:"):
        question_id = int(choice.split(":", 1)[1])
        evidence_add(question_id, note_id, "advances", "you said so", staging_dir)
        record_feedback(note_id, "kept", staging_dir, origin="explicit")
        log_event("clarify", note_id, f"evidence for question {question_id}", staging_dir)
        return f"filed as evidence for question {question_id}, and kept"

    con = _connect(staging_dir)
    try:
        con.execute("UPDATE notes SET domain = ?, confidence = 1.0 WHERE id = ?", (choice, note_id))
        con.commit()
    finally:
        con.close()
    record_feedback(note_id, "kept", staging_dir, origin="explicit")
    log_event("clarify", note_id, f"routed to {choice}", staging_dir)
    return f"routed to `{choice}` — by you, so with full confidence"
