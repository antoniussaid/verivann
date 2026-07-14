"""Notes that are still alive after you wrote them.

An Obsidian note is a dead file: whatever it claimed on the day you saved it, it
claims forever, with the same confidence, long after the world moved on. Verivann has
a ledger - claims with a shelf life, predictions with a due date, sources with a
record - so its notes have no excuse for being dead too.

`verivann refresh` walks every note something has happened to, and writes what
happened at the top of it:

    > **Since you read this**
    > - A later source contradicts it: "…" (from *X*, 2026-08-01)
    > - 2 claim(s) in it are past their shelf life
    > - A prediction it carried did not come true
    > - Its source has since been wrong 3× / tried to manipulate the analyzer

The banner sits between two markers, so refreshing is idempotent: it is replaced,
never stacked. The file stays plain Markdown - no database magic, no lock-in. If
you delete Verivann tomorrow, the warning is still legible in your vault.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from .config import Config

_START = "<!-- verivann:since -->"
_END = "<!-- /verivann:since -->"
_BLOCK = re.compile(re.escape(_START) + r".*?" + re.escape(_END) + r"\n*", re.DOTALL)


@dataclass
class Alerts:
    note_id: str
    title: str
    note_path: str
    contradicted: list[dict] = field(default_factory=list)
    expired: list[str] = field(default_factory=list)
    missed: list[str] = field(default_factory=list)
    source_note: str = ""

    @property
    def any(self) -> bool:
        return bool(self.contradicted or self.expired or self.missed or self.source_note)

    def banner(self) -> str:
        lines = [_START, "> **Since you read this**", ">"]
        for c in self.contradicted:
            lines.append(
                f"> - **Contradicted.** A later source says: “{c['claim'][:110]}”  "
                f"_(from {c['by_source']}, {c['at'][:10]} - {c['why'][:70]})_"
            )
        if self.expired:
            lines.append(
                f"> - **{len(self.expired)} claim(s) past their shelf life.** "
                f"e.g. “{self.expired[0][:100]}”"
            )
        for m in self.missed:
            lines.append(f"> - **A prediction here did not come true:** “{m[:110]}”")
        if self.source_note:
            lines.append(f"> - **The source's record has changed:** {self.source_note}")
        lines += [">", "> _This note was not rewritten - only this box was._", _END, ""]
        return "\n".join(lines)


def alerts_for(note: dict, staging_dir: Path) -> Alerts:
    from .library import (
        contradictions_against,
        expired_claims_of,
        missed_predictions_of,
        source_standing,
    )

    item = Alerts(note_id=note["id"], title=note["title"], note_path=note["note_path"] or "")
    item.contradicted = contradictions_against(note["id"], staging_dir)
    item.expired = expired_claims_of(note["id"], staging_dir)
    item.missed = missed_predictions_of(note["id"], staging_dir)

    standing = source_standing(note.get("source_key", ""), staging_dir) if note.get("source_key") else None
    if standing:
        marks = []
        if standing["hostile"]:
            marks.append(f"caught trying to manipulate the analyzer {standing['hostile']}×")
        if standing["misses"]:
            marks.append(f"wrong {standing['misses']}× since (right {standing['hits']}×)")
        item.source_note = "; ".join(marks)
    return item


def refresh(config: Config | None = None) -> list[Alerts]:
    """Rewrite the banner on every note something has happened to. Returns the movers."""
    config = config or Config.load()
    from .library import notes_with_history

    changed: list[Alerts] = []
    for note in notes_with_history(config.staging_dir):
        item = alerts_for(note, config.staging_dir)
        if not item.any or not item.note_path:
            continue
        if _write_banner(Path(item.note_path), item.banner()):
            changed.append(item)
    return changed


def _write_banner(path: Path, banner: str) -> bool:
    """Insert (or replace) the banner directly under the frontmatter. Idempotent."""
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return False

    stripped = _BLOCK.sub("", text)
    if banner.strip() in text:
        return False  # nothing new to say

    # After the frontmatter block, before everything else.
    parts = stripped.split("---", 2)
    if text.startswith("---") and len(parts) >= 3:
        updated = f"---{parts[1]}---\n\n{banner}\n{parts[2].lstrip()}"
    else:
        updated = f"{banner}\n{stripped}"
    path.write_text(updated, encoding="utf-8")
    return True


def clear(path: Path) -> None:
    """Remove the banner (used when the alerts are gone)."""
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return
    path.write_text(_BLOCK.sub("", text), encoding="utf-8")
