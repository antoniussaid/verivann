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

    target_dir.mkdir(parents=True, exist_ok=True)
    target = target_dir / source.name
    target.write_text(_resolve(source.read_text(encoding="utf-8")), encoding="utf-8")

    # Accepting is the strongest possible "keep" — the router should learn from it,
    # and nobody should have to press a second button to say so.
    observe(row["id"], "accept", config.staging_dir)
    log_event("accept", row["id"], str(target), config.staging_dir)
    return Accepted(note_id=row["id"], title=row["title"], source=source, target=target)


def _resolve(markdown: str) -> str:
    """Turn the proposal in the frontmatter into a decision a human made."""
    today = datetime.now(timezone.utc).date().isoformat()
    out = re.sub(r"^proposed_action:\s*(\w+)", r"action: \1", markdown, count=1, flags=re.MULTILINE)
    out = re.sub(
        r"^(action: \w+)$",
        rf"\1\naccepted_at: {today}\naccepted_by: human",
        out,
        count=1,
        flags=re.MULTILINE,
    )
    return out.replace(
        "_(proposal only — never committed here)_",
        f"_(accepted by you on {today})_",
    )


def accept_all(note_ids: list[str], target_dir: Path, config: Config | None = None) -> list[Accepted]:
    return [a for a in (accept(i, target_dir, config) for i in note_ids) if a]


def default_target() -> Path | None:
    """`VERIVANN_ACCEPT_DIR` — so `verivann accept <id>` needs no flag in daily use."""
    value = os.environ.get("VERIVANN_ACCEPT_DIR", "").strip()
    return Path(value) if value else None
