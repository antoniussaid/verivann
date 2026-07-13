"""The one place a proposal becomes a commitment — and a human does it.

Everything in Verivann is a proposal. The router proposes a domain, the analyzer
proposes an action, the profile proposes a drop. Nothing is ever written into a
knowledge base, because deciding what enters your memory is not a job you delegate
to a keyword count or a language model.

`verivann accept <id> --to <dir>` is where you decide. It copies the staged note into
a plain folder — an Obsidian vault, a git repo, whatever reads Markdown — with the
proposal resolved into a fact:

    proposed_action: note      ->     action: note
    (nothing)                  ->     accepted_at: 2026-07-12
                                      accepted_by: human

The note is also marked `kept`, because accepting a note is the strongest possible
statement that you wanted it (relevance.py learns from exactly that).

No lock-in: the destination is a folder of Markdown files. Verivann does not own it,
cannot read it back, and will not touch it again.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from .config import Config


@dataclass
class Accepted:
    note_id: str
    title: str
    source: Path
    target: Path


def accept(note_id: str, target_dir: Path, config: Config | None = None) -> Accepted | None:
    """Copy a staged note into a real folder, resolving the proposal into a decision."""
    config = config or Config.load()
    from .library import log_event, note_row
    from .signals import observe

    row = note_row(note_id, config.staging_dir)
    if row is None:
        return None
    source = Path(row["note_path"])
    if not source.is_file():
        return None

    content = _resolve(source.read_text(encoding="utf-8"))
    target_dir.mkdir(parents=True, exist_ok=True)
    # A commit gate must never destroy what is already in the user's vault: a name
    # collision with a *different* note gets its own file; re-accepting the *same*
    # note (matched by id) updates in place. If no safe path can be found at all, we
    # refuse rather than overwrite someone else's note.
    target = _unclobbered(target_dir / source.name, content)
    if target is None:
        return None
    target.write_text(content, encoding="utf-8")

    # Accepting is the strongest possible "keep" — the router should learn from it,
    # and nobody should have to press a second button to say so.
    observe(row["id"], "accept", config.staging_dir)
    log_event("accept", row["id"], str(target), config.staging_dir)
    return Accepted(note_id=row["id"], title=row["title"], source=source, target=target)


_FRONTMATTER = re.compile(r"\A(---\n)(.*?)(\n---)", re.DOTALL)


def _resolve(markdown: str) -> str:
    """Turn the proposal in the frontmatter into a decision a human made.

    Scoped to the frontmatter block, so a stray `action:` line in the note body can
    never be mistaken for the decision field. Acceptance is always stamped — even a
    note that never carried a `proposed_action` leaves this gate marked accepted by a
    human, because recording *who committed it* is the whole job of the gate.
    """
    today = datetime.now(timezone.utc).date().isoformat()
    marked = markdown.replace(
        "_(proposal only — never committed here)_",
        f"_(accepted by you on {today})_",
    )

    m = _FRONTMATTER.search(marked)
    if not m:  # no frontmatter — prepend one so the human decision is still recorded
        return f"---\naction: note\naccepted_at: {today}\naccepted_by: human\n---\n\n{marked}"

    block = m.group(2)
    block = re.sub(r"^proposed_action:\s*(\S+)\s*$", r"action: \1", block, count=1, flags=re.MULTILINE)
    if not re.search(r"^action:\s*\S+\s*$", block, flags=re.MULTILINE):
        block += "\naction: note"  # nothing to resolve, but still a kept note
    if not re.search(r"^accepted_by:", block, flags=re.MULTILINE):  # idempotent
        block += f"\naccepted_at: {today}\naccepted_by: human"
    return marked[: m.start(2)] + block + marked[m.end(2) :]


def _note_id_of(text: str) -> str:
    m = re.search(r"^id:\s*(\S+)", text, flags=re.MULTILINE)
    return m.group(1) if m else ""


def _unclobbered(target: Path, content: str) -> Path | None:
    """A free path that never overwrites a *different* note already in the vault.

    Re-accepting the same note (same `id`, even on a later day) reuses its file;
    a real filename collision with another note gets a numeric suffix instead of
    silently destroying it. Returns None if no safe path exists (so the caller
    refuses rather than clobbering) — fail closed, never fail open.
    """
    new_id = _note_id_of(content)

    def same_note(path: Path) -> bool:
        try:
            return bool(new_id) and _note_id_of(path.read_text(encoding="utf-8")) == new_id
        except OSError:
            return False

    if not target.exists() or same_note(target):
        return target
    for n in range(2, 1000):
        candidate = target.with_name(f"{target.stem}-{n}{target.suffix}")
        if not candidate.exists() or same_note(candidate):
            return candidate
    return None  # 1000 same-named different notes: refuse, don't overwrite one of them


def accept_all(note_ids: list[str], target_dir: Path, config: Config | None = None) -> list[Accepted]:
    return [a for a in (accept(i, target_dir, config) for i in note_ids) if a]


def default_target() -> Path | None:
    """`VERIVANN_ACCEPT_DIR` — so `verivann accept <id>` needs no flag in daily use."""
    value = os.environ.get("VERIVANN_ACCEPT_DIR", "").strip()
    return Path(value) if value else None
