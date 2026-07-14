"""Staging writer.

The public core writes ONLY into a configurable staging directory. It never
touches any real private structure structure - the private layer picks artifacts up from
here. Two artifacts per intake: a Markdown note and a JSON event.
"""

from __future__ import annotations

from pathlib import Path


def write_artifacts(staging_dir: Path, stem: str, markdown: str, json_event: str) -> tuple[Path, Path]:
    notes_dir = staging_dir / "notes"
    events_dir = staging_dir / "events"
    notes_dir.mkdir(parents=True, exist_ok=True)
    events_dir.mkdir(parents=True, exist_ok=True)

    note_path = notes_dir / f"{stem}.md"
    event_path = events_dir / f"{stem}.json"
    note_path.write_text(markdown, encoding="utf-8")
    event_path.write_text(json_event, encoding="utf-8")
    return note_path, event_path
