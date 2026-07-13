"""The folder that empties itself.

Point Verivann at your screenshots folder, your voice-memo folder, your downloads.
It reads what is new, routes it, and remembers what it has already seen — so
running it again is cheap and never produces a duplicate.

    verivann folder ~/Pictures/Screenshots          once
    verivann folder ~/Pictures/Screenshots --watch  keep watching (poll)

It never deletes, moves, or modifies a single file it reads. The folder is the
source; the note is the output; the two never touch.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path

from .adapters.local import SUPPORTED
from .config import Config

_POLL_SECONDS = 20


@dataclass
class Digested:
    path: Path
    title: str
    domain: str
    action: str
    note_id: str


def scan(folder: Path, recursive: bool = False) -> list[Path]:
    pattern = "**/*" if recursive else "*"
    return sorted(
        p for p in folder.glob(pattern)
        if p.is_file() and p.suffix.lower() in SUPPORTED and not p.name.startswith(".")
    )


def run_once(
    folder: Path, config: Config | None = None, recursive: bool = False, lens: str | None = None
) -> list[Digested]:
    """Digest every file in the folder that has not been digested yet."""
    config = config or Config.load()
    from .library import mark_file_seen, seen_file
    from .pipeline import run

    digested: list[Digested] = []
    for path in scan(folder, recursive):
        stat = path.stat()
        fingerprint = f"{stat.st_size}:{int(stat.st_mtime)}"
        if seen_file(str(path), fingerprint, config.staging_dir):
            continue  # already read, and unchanged since
        result = run("file", ref=str(path), config=config, lens=lens)
        mark_file_seen(str(path), fingerprint, result.event.id, config.staging_dir)
        digested.append(
            Digested(
                path=path,
                title=result.event.extracted.title,
                domain=result.event.routing.domain,
                action=result.event.decision.action,
                note_id=result.event.id,
            )
        )
    return digested


def watch(
    folder: Path,
    config: Config | None = None,
    recursive: bool = False,
    lens: str | None = None,
    on_batch=None,
    poll: int = _POLL_SECONDS,
) -> None:
    """Poll forever. Deliberately dumb: no OS file-watch APIs, no daemon, no state."""
    while True:
        batch = run_once(folder, config, recursive, lens)
        if batch and on_batch:
            on_batch(batch)
        time.sleep(poll)
