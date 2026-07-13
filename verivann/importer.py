"""Bring in what you already have — and judge it.

Verivann had no migration path at all, which is an adoption blocker and a wasted
opportunity at the same time. The best possible first day with a tool like this is
not "start saving things"; it is **point it at the pile you already have and let it
tell you something about yourself**: which of your sources have contradicted each
other, what you have been reading for a year and never used, whose predictions
never came true.

    verivann import urls <file>          a Pocket / Raindrop / Instapaper export, or any list
    verivann import obsidian <vault>     every note you have already written
    verivann import history              the pages you actually came back to

Everything is bounded (`--limit`), resumable (the same source is never digested
twice — canonical identity, see canonical.py), and reversible in the only sense
that matters: **nothing you import is modified.** Your vault, your export file and
your browser stay exactly as they were.

Browser history deserves a note: a page you visited five times is a page that
mattered to you, and that is a relevance signal no bookmark can give. We read the
history file — a copy of it, because the browser holds a lock — and never write to it.
"""

from __future__ import annotations

import re
import shutil
import sqlite3
import tempfile
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .canonical import canonical_url
from .config import Config

_URL = re.compile(r"https?://[^\s\"'<>,;)\]]+")
_CHROME_EPOCH = datetime(1601, 1, 1, tzinfo=timezone.utc)

_HISTORY_PATHS = (
    r"%LOCALAPPDATA%\Google\Chrome\User Data\Default\History",
    r"%LOCALAPPDATA%\Microsoft\Edge\User Data\Default\History",
    r"%LOCALAPPDATA%\BraveSoftware\Brave-Browser\User Data\Default\History",
    "~/Library/Application Support/Google/Chrome/Default/History",
    "~/.config/google-chrome/Default/History",
    "~/.config/chromium/Default/History",
)

# Nobody wants their bank, their mail and their own localhost in a knowledge base.
_SKIP_HOSTS = (
    "localhost", "127.0.0.1", "mail.google.com", "outlook", "bank", "paypal", "amazon.",
    "netflix", "youtube.com/watch?v=&", "accounts.google.com", "login.", "signin",
)


@dataclass
class Candidate:
    ref: str
    kind: str  # "url" | "youtube" | "file"
    title: str = ""
    hint: str = ""  # why it is worth importing (visits, folder, …)


@dataclass
class Outcome:
    imported: int = 0
    skipped: int = 0
    failed: int = 0
    domains: dict[str, int] | None = None


# ---------- sources of candidates ----------

def from_urls(path: Path) -> list[Candidate]:
    """Any text or CSV export: we take the URLs and ignore the rest of the schema."""
    text = path.read_text(encoding="utf-8", errors="ignore")
    seen: set[str] = set()
    out: list[Candidate] = []
    for match in _URL.finditer(text):
        url = canonical_url(match.group(0).rstrip(",;"))
        if url in seen:
            continue
        seen.add(url)
        kind = "youtube" if ("youtube.com" in url or "youtu.be" in url) else "url"
        out.append(Candidate(ref=url, kind=kind, hint="from export"))
    return out


def from_obsidian(vault: Path) -> list[Candidate]:
    """Every markdown note in a vault. The vault is read, never touched."""
    return [
        Candidate(ref=str(p), kind="file", title=p.stem, hint=str(p.parent.name))
        for p in sorted(vault.rglob("*.md"))
        if not any(part.startswith(".") for part in p.parts)
    ]


def from_history(days: int = 60, min_visits: int = 2, browser_db: Path | None = None) -> list[Candidate]:
    """The pages you came back to. A revisit is a verdict nobody had to type."""
    source = browser_db or _find_history()
    if source is None or not source.is_file():
        return []

    # The browser holds a lock on its own history — work on a copy, and never write.
    with tempfile.TemporaryDirectory() as tmp:
        copy = Path(tmp) / "history.db"
        try:
            shutil.copy2(source, copy)
        except OSError:
            return []
        con = sqlite3.connect(f"file:{copy}?mode=ro", uri=True)
        con.row_factory = sqlite3.Row
        try:
            cutoff = int((datetime.now(timezone.utc) - timedelta(days=days) - _CHROME_EPOCH).total_seconds() * 1e6)
            rows = con.execute(
                """SELECT url, title, visit_count FROM urls
                   WHERE visit_count >= ? AND last_visit_time >= ?
                   ORDER BY visit_count DESC""",
                (min_visits, cutoff),
            ).fetchall()
        except sqlite3.DatabaseError:
            return []
        finally:
            con.close()

    seen: set[str] = set()
    out: list[Candidate] = []
    for row in rows:
        url = canonical_url(row["url"])
        low = url.lower()
        if url in seen or any(skip in low for skip in _SKIP_HOSTS):
            continue
        seen.add(url)
        kind = "youtube" if ("youtube.com" in low or "youtu.be" in low) else "url"
        out.append(
            Candidate(ref=url, kind=kind, title=row["title"] or "", hint=f"{row['visit_count']} visits")
        )
    return out


def _find_history() -> Path | None:
    import os

    for raw in _HISTORY_PATHS:
        path = Path(os.path.expandvars(os.path.expanduser(raw)))
        if path.is_file():
            return path
    return None


# ---------- the import itself ----------

def already_known(candidate: Candidate, config: Config) -> bool:
    from .library import find_by_ref

    if candidate.kind == "file":
        return False  # a local file has no canonical URL; the folder tracker handles repeats
    return find_by_ref(candidate.ref, config.staging_dir) is not None


def ingest(
    candidates: list[Candidate],
    config: Config | None = None,
    limit: int = 50,
    lens: str | None = None,
    on_item=None,
) -> Outcome:
    """Digest the candidates, bounded and resumable. Nothing imported is modified."""
    config = config or Config.load()
    from .library import log_event
    from .pipeline import run

    outcome = Outcome(domains={})
    for candidate in candidates:
        if outcome.imported >= limit:
            break
        if already_known(candidate, config):
            outcome.skipped += 1
            continue
        try:
            result = run(candidate.kind, ref=candidate.ref, config=config, lens=lens)
        except Exception:  # noqa: BLE001 - one broken link must not stop a migration
            outcome.failed += 1
            continue
        outcome.imported += 1
        domain = result.event.routing.domain
        outcome.domains[domain] = outcome.domains.get(domain, 0) + 1
        if on_item:
            on_item(candidate, result)
    log_event("import", "", f"{outcome.imported} imported, {outcome.skipped} known", config.staging_dir)
    return outcome
