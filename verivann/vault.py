"""Data sovereignty: back it all up, export the readable notes, or erase it all.

Verivann keeps everything in one folder you own. These three make that ownership
real - a single portable archive you can move or keep, a plain folder of Markdown
with no database in the way, and a clean, total erase for when you want to walk away
and leave nothing behind. Nothing here talks to a network; it is all your machine.
"""

from __future__ import annotations

import shutil
import zipfile
from pathlib import Path

_TRANSIENT = ".subs"  # scratch working dirs - never worth keeping


def backup(staging_dir: Path, out_path: Path) -> Path:
    """Zip the whole library (db + notes + events + raw archives) into one file."""
    from .library import checkpoint

    checkpoint(staging_dir)  # fold the WAL in first, so the db copy is whole
    if out_path.suffix != ".zip":
        out_path = out_path.with_name(out_path.name + ".zip")
    out_path.parent.mkdir(parents=True, exist_ok=True)

    with zipfile.ZipFile(out_path, "w", zipfile.ZIP_DEFLATED) as archive:
        if staging_dir.exists():
            for path in sorted(staging_dir.rglob("*")):
                if not path.is_file():
                    continue
                rel = path.relative_to(staging_dir)
                if rel.parts and rel.parts[0] == _TRANSIENT:
                    continue
                if path.name.endswith(("-wal", "-shm")):  # sidecars folded in already
                    continue
                archive.write(path, rel.as_posix())
    return out_path


def export_notes(staging_dir: Path, out_dir: Path) -> int:
    """Copy every note's Markdown into a plain folder - no database, no lock-in."""
    notes = sorted((staging_dir / "notes").glob("*.md")) if (staging_dir / "notes").is_dir() else []
    out_dir.mkdir(parents=True, exist_ok=True)
    for note in notes:
        shutil.copy2(note, out_dir / note.name)
    return len(notes)


def erase(staging_dir: Path) -> dict:
    """Delete the entire library. The next run starts from an empty slate."""
    if not staging_dir.exists():
        return {"notes": 0, "files": 0}
    notes = len(list((staging_dir / "notes").glob("*.md"))) if (staging_dir / "notes").is_dir() else 0
    files = sum(1 for p in staging_dir.rglob("*") if p.is_file())
    shutil.rmtree(staging_dir, ignore_errors=True)
    return {"notes": notes, "files": files}
