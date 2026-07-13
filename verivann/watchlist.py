"""Sources change after you read them. Nobody tells you.

A news site corrects a number, a company deletes a paragraph, a price moves, a
promise disappears. The archive tools keep snapshots — but a snapshot only helps
if you already suspected something. Verivann does the suspecting for you: it re-reads
what you told it to watch and shows you **what changed**, in the words that
changed.

    verivann watch add <url>     put a source under observation
    verivann watch run           re-read them all; changed ones produce a fresh note
    verivann watch list          what is being watched, and when it last moved

A changed source is digested again — same note (canonical identity), new content,
plus a **Changed since you read it** section carrying the diff. What the source
now says is what your library now holds; what it *used* to say is in the diff.
"""

from __future__ import annotations

import difflib
import hashlib
from dataclasses import dataclass

from .canonical import canonical_url
from .config import Config

_MAX_DIFF_LINES = 40


@dataclass
class Watched:
    url: str
    label: str
    added_at: str
    last_checked: str
    last_changed: str
    changes: int


def _digest(text: str) -> str:
    return hashlib.sha256((text or "").strip().encode("utf-8")).hexdigest()


def add(url: str, config: Config | None = None) -> Watched:
    """Put a source under observation, taking its current text as the baseline."""
    config = config or Config.load()
    from .adapters import extract_webpage
    from .library import watch_upsert

    canon = canonical_url(url)
    extracted = extract_webpage(canon)
    row = watch_upsert(
        canon,
        label=extracted.title or canon,
        text=extracted.text,
        digest=_digest(extracted.text),
        staging_dir=config.staging_dir,
    )
    return Watched(**row)


def remove(url: str, config: Config | None = None) -> bool:
    from .library import watch_remove

    config = config or Config.load()
    return watch_remove(canonical_url(url), config.staging_dir)


def watched(config: Config | None = None) -> list[Watched]:
    from .library import watch_rows

    config = config or Config.load()
    return [Watched(**row) for row in watch_rows(config.staging_dir)]


def run(config: Config | None = None, lens: str | None = None) -> list[tuple[str, str, int]]:
    """Re-read every watched source. Returns [(url, diff, changed_lines)] for the movers."""
    config = config or Config.load()
    from .adapters import extract_webpage
    from .library import watch_mark, watch_state
    from .pipeline import run as digest

    moved: list[tuple[str, str, int]] = []
    for entry in watched(config):
        state = watch_state(entry.url, config.staging_dir)
        if state is None:
            continue
        fresh = extract_webpage(entry.url)
        if not fresh.text.strip() or fresh.meta.get("fallback"):
            continue  # a failed fetch is not a change — never cry wolf
        new_digest = _digest(fresh.text)
        if new_digest == state["digest"]:
            watch_mark(entry.url, digest=new_digest, changed=False, staging_dir=config.staging_dir)
            continue

        patch, changed_lines = diff(state["text"] or "", fresh.text)
        watch_mark(
            entry.url,
            digest=new_digest,
            changed=True,
            staging_dir=config.staging_dir,
            text=fresh.text,
        )
        digest(  # the note now holds what the source NOW says — plus what it used to
            "url",
            ref=entry.url,
            config=config,
            lens=lens,
            extra_meta={"changed": {"diff": patch, "lines": changed_lines}},
        )
        moved.append((entry.url, patch, changed_lines))
    return moved


def diff(old: str, new: str) -> tuple[str, int]:
    """A readable unified diff of what the source used to say and says now."""
    old_lines = [line for line in (old or "").splitlines() if line.strip()]
    new_lines = [line for line in (new or "").splitlines() if line.strip()]
    delta = [
        line
        for line in difflib.unified_diff(old_lines, new_lines, lineterm="", n=0)
        if line.startswith(("+", "-")) and not line.startswith(("+++", "---"))
    ]
    changed = len(delta)
    if changed > _MAX_DIFF_LINES:
        delta = delta[:_MAX_DIFF_LINES] + [f"… {changed - _MAX_DIFF_LINES} more changed line(s)"]
    return "\n".join(delta), changed
