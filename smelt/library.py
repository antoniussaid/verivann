"""Library — a searchable index of everything Smelt has digested.

A local SQLite database (FTS5 full-text search when available, LIKE fallback
otherwise) over the staged notes. This is the foundation for search, "ask your
intake", connections, and the claim ledger. Local-first; lives next to staging.
"""

from __future__ import annotations

import re
import sqlite3
from dataclasses import dataclass
from pathlib import Path

from .schema import IntakeEvent

_fts_cache: dict[str, bool] = {}

_STOP = {
    "the", "and", "what", "have", "about", "from", "with", "that", "this", "which",
    "was", "wie", "der", "die", "das", "und", "für", "mit", "ich", "hab", "habe",
    "über", "you", "your", "for", "are", "how", "why", "who", "does", "did", "its",
}


def keywords(text: str, max_words: int = 12) -> str:
    """A safe FTS query — significant words OR-ed. Prevents FTS syntax errors."""
    words = [w for w in re.findall(r"[A-Za-zÀ-ÿ0-9]{3,}", text.lower()) if w not in _STOP]
    unique = list(dict.fromkeys(words))[:max_words]
    return " OR ".join(unique)


def _db_path(staging_dir: Path) -> Path:
    return staging_dir / "library.db"


def _fts_available(con: sqlite3.Connection) -> bool:
    key = "fts5"
    if key not in _fts_cache:
        try:
            con.execute("CREATE VIRTUAL TABLE IF NOT EXISTS _fts_probe USING fts5(x)")
            con.execute("DROP TABLE _fts_probe")
            _fts_cache[key] = True
        except sqlite3.OperationalError:
            _fts_cache[key] = False
    return _fts_cache[key]


def _connect(staging_dir: Path) -> sqlite3.Connection:
    staging_dir.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(_db_path(staging_dir))
    con.row_factory = sqlite3.Row
    con.execute(
        """CREATE TABLE IF NOT EXISTS notes (
            id TEXT PRIMARY KEY, created_at TEXT, source_kind TEXT, source_ref TEXT,
            title TEXT, domain TEXT, confidence REAL, action TEXT, text TEXT,
            note_path TEXT, event_path TEXT )"""
    )
    con.execute(
        """CREATE TABLE IF NOT EXISTS claims (
            id INTEGER PRIMARY KEY AUTOINCREMENT, note_id TEXT, claim TEXT, created_at TEXT )"""
    )
    con.execute(
        """CREATE TABLE IF NOT EXISTS feedback (
            note_id TEXT PRIMARY KEY, verdict TEXT, domain TEXT, title TEXT,
            text TEXT, created_at TEXT )"""
    )
    con.execute(
        """CREATE TABLE IF NOT EXISTS sources (
            key TEXT PRIMARY KEY, label TEXT, first_seen TEXT,
            hits INTEGER DEFAULT 0, misses INTEGER DEFAULT 0, hostile INTEGER DEFAULT 0 )"""
    )
    con.execute(
        """CREATE TABLE IF NOT EXISTS predictions (
            id INTEGER PRIMARY KEY AUTOINCREMENT, note_id TEXT, source_key TEXT,
            text TEXT, due TEXT, status TEXT DEFAULT 'open', created_at TEXT )"""
    )
    con.execute(
        "CREATE TABLE IF NOT EXISTS vectors ( note_id TEXT PRIMARY KEY, vec BLOB )"
    )
    con.execute(
        """CREATE TABLE IF NOT EXISTS files (
            path TEXT PRIMARY KEY, fingerprint TEXT, note_id TEXT, seen_at TEXT )"""
    )
    con.execute(
        """CREATE TABLE IF NOT EXISTS feeds (
            url TEXT PRIMARY KEY, title TEXT, added_at TEXT, last_run TEXT,
            seen INTEGER DEFAULT 0, passed INTEGER DEFAULT 0 )"""
    )
    con.execute(
        """CREATE TABLE IF NOT EXISTS feed_items (
            guid TEXT PRIMARY KEY, feed_url TEXT, seen_at TEXT )"""
    )
    con.execute(
        """CREATE TABLE IF NOT EXISTS questions (
            id INTEGER PRIMARY KEY AUTOINCREMENT, text TEXT, status TEXT DEFAULT 'open',
            created_at TEXT )"""
    )
    con.execute(
        """CREATE TABLE IF NOT EXISTS evidence (
            question_id INTEGER, note_id TEXT, stance TEXT, why TEXT, added_at TEXT,
            PRIMARY KEY (question_id, note_id) )"""
    )
    con.execute(
        """CREATE TABLE IF NOT EXISTS watchlist (
            url TEXT PRIMARY KEY, label TEXT, added_at TEXT, last_checked TEXT,
            last_changed TEXT, changes INTEGER DEFAULT 0, digest TEXT, text TEXT )"""
    )
    con.execute(
        """CREATE TABLE IF NOT EXISTS signals (
            id INTEGER PRIMARY KEY AUTOINCREMENT, note_id TEXT, kind TEXT, at TEXT )"""
    )
    con.execute("CREATE TABLE IF NOT EXISTS state ( key TEXT PRIMARY KEY, value TEXT )")
    con.execute(
        """CREATE TABLE IF NOT EXISTS events (
            id INTEGER PRIMARY KEY AUTOINCREMENT, at TEXT, action TEXT,
            subject TEXT, detail TEXT )"""
    )
    con.execute(
        """CREATE TABLE IF NOT EXISTS outbound (
            id INTEGER PRIMARY KEY AUTOINCREMENT, at TEXT, provider TEXT, model TEXT,
            purpose TEXT, chars INTEGER, note_id TEXT, cost REAL )"""
    )
    con.execute(
        """CREATE TABLE IF NOT EXISTS highlights (
            id INTEGER PRIMARY KEY AUTOINCREMENT, note_id TEXT, text TEXT, at TEXT )"""
    )
    # The model bake-off: what each model proposed for the same note. Scored later
    # against the only ground truth there is — the human's verdict.
    con.execute(
        """CREATE TABLE IF NOT EXISTS bakeoff (
            note_id TEXT, model TEXT, proposed TEXT, confidence REAL, at TEXT,
            PRIMARY KEY (note_id, model) )"""
    )
    # A contradiction is an edge between two notes, and it has to be walkable in
    # BOTH directions: the new note says "this clashes with what you had", and the
    # old note deserves to learn that it has been contradicted (refresh.py).
    con.execute(
        """CREATE TABLE IF NOT EXISTS contradictions (
            id INTEGER PRIMARY KEY AUTOINCREMENT, new_note TEXT, old_note TEXT,
            claim TEXT, against TEXT, why TEXT, at TEXT )"""
    )
    if _fts_available(con):
        con.execute(
            "CREATE VIRTUAL TABLE IF NOT EXISTS notes_fts USING fts5(id UNINDEXED, title, text)"
        )
        con.execute(
            "CREATE VIRTUAL TABLE IF NOT EXISTS claims_fts USING fts5(claim, note_id UNINDEXED)"
        )
    # Late columns, added in place. Done here — not lazily on the path that happens
    # to need them — so the schema is never half-built for whoever queries next.
    _ensure_canon(con)  # after every table exists: the backfill writes into `sources`
    _ensure_claim_expiry(con)
    _ensure_feedback_origin(con)
    con.commit()
    return con


_LATE_COLUMNS = {
    "canon": "TEXT",  # the source's canonical identity (see canonical.py)
    "source_key": "TEXT",  # WHO published it (see sources.py)
    "minutes": "REAL",  # how much material it was
    "ideas": "INTEGER",  # how much came out of it
    "engine": "TEXT",  # who read it — a yield of 0 means nothing if nobody read it
    "lens": "TEXT",  # with what intent it was read (calibration compares lenses)
    "sensitivity": "TEXT",  # public | sensitive  (privacy.py)
}


def _ensure_canon(con: sqlite3.Connection) -> None:
    """Columns added after the first release — created and backfilled in place.

    Notes indexed before canonicalization carried raw refs (the same video under
    `?t=78s` looked like a different source); notes indexed before source identity
    existed knew nothing about who published them. Backfilling makes an old library
    behave like a fresh one, so `dedupe()` and `smelt sources` see the whole record.
    """
    from .canonical import canonical_url

    columns = {r["name"] for r in con.execute("PRAGMA table_info(notes)")}
    for name, coltype in _LATE_COLUMNS.items():
        if name not in columns:
            con.execute(f"ALTER TABLE notes ADD COLUMN {name} {coltype}")

    stale = con.execute(
        """SELECT id, source_kind, source_ref, event_path, text
           FROM notes WHERE canon IS NULL OR source_key IS NULL"""
    ).fetchall()
    for row in stale:
        canon = canonical_url(row["source_ref"] or "")
        key, label, minutes = _identity_from_event(row, canon)
        con.execute(
            "UPDATE notes SET canon = ?, source_key = ?, minutes = ? WHERE id = ?",
            (canon, key, minutes, row["id"]),
        )
        con.execute(
            """INSERT INTO sources (key, label, first_seen) VALUES (?,?,datetime('now'))
               ON CONFLICT(key) DO NOTHING""",
            (key, label),
        )
    if stale:
        con.commit()


def _identity_from_event(row: sqlite3.Row, canon: str) -> tuple[str, str, float]:
    """Recover a source's real identity from the staged event, not just its URL.

    The URL alone says `youtube.com`; the event says `@3blue1brown`. An old library
    deserves the same identity a fresh intake would get.
    """
    import json

    from .schema import Extracted
    from .sources import identify, identify_ref, material_minutes

    kind = row["source_kind"] or ""
    try:
        data = json.loads(Path(row["event_path"]).read_text(encoding="utf-8"))
        extracted = Extracted(**data["extracted"])
    except Exception:  # noqa: BLE001 - the event file may be gone; fall back to the URL
        key, label = identify_ref(kind, canon)
        return key, label, 0.0
    key, label = identify(kind, canon, extracted)
    return key, label, material_minutes(extracted)


@dataclass
class Hit:
    id: str
    title: str
    domain: str
    created_at: str
    source_ref: str
    note_path: str
    snippet: str
    text: str = ""


def index_event(
    event: IntakeEvent,
    note_path: str,
    event_path: str,
    staging_dir: Path,
    ideas: int = 0,
    engine: str = "heuristic",
    lens: str = "digest",
    sensitivity: str = "public",
) -> None:
    from .canonical import canonical_url
    from .sources import identify, material_minutes

    con = _connect(staging_dir)
    try:
        e = event
        canon = canonical_url(e.source.ref)
        key, label = identify(e.source.kind, canon, e.extracted)
        con.execute(
            """INSERT INTO sources (key, label, first_seen) VALUES (?,?,datetime('now'))
               ON CONFLICT(key) DO UPDATE SET label = excluded.label""",
            (key, label),
        )
        con.execute(
            """INSERT OR REPLACE INTO notes
               (id, created_at, source_kind, source_ref, title, domain, confidence,
                action, text, note_path, event_path, canon, source_key, minutes, ideas,
                engine, lens, sensitivity)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (e.id, e.created_at, e.source.kind, e.source.ref, e.extracted.title,
             e.routing.domain, e.routing.confidence, e.decision.action,
             e.extracted.text, note_path, event_path, canon, key,
             material_minutes(e.extracted), ideas, engine, lens, sensitivity),
        )
        if _fts_available(con):
            con.execute("DELETE FROM notes_fts WHERE id = ?", (e.id,))
            con.execute(
                "INSERT INTO notes_fts (id, title, text) VALUES (?,?,?)",
                (e.id, e.extracted.title, e.extracted.text),
            )
        con.commit()
    finally:
        con.close()


def _row_to_hit(r: sqlite3.Row) -> Hit:
    return Hit(
        id=r["id"], title=r["title"], domain=r["domain"], created_at=r["created_at"],
        source_ref=r["source_ref"], note_path=r["note_path"],
        snippet=(r["snip"] or "").strip(),
        # `.keys()` is required: `in` on a sqlite3.Row iterates its VALUES, not its
        # column names, so dropping it would silently test the wrong thing.
        text=(r["txt"] if "txt" in r.keys() else "") or "",  # noqa: SIM118
    )


def search(query: str, staging_dir: Path, limit: int = 10) -> list[Hit]:
    con = _connect(staging_dir)
    try:
        if _fts_available(con):
            rows = con.execute(
                """SELECT n.id, n.title, n.domain, n.created_at, n.source_ref, n.note_path, n.text AS txt,
                          snippet(notes_fts, 2, '[', ']', '…', 12) AS snip
                   FROM notes_fts f JOIN notes n ON n.id = f.id
                   WHERE notes_fts MATCH ? ORDER BY rank LIMIT ?""",
                (query, limit),
            ).fetchall()
        else:
            like = f"%{query}%"
            rows = con.execute(
                """SELECT id, title, domain, created_at, source_ref, note_path, text AS txt,
                          substr(text, 1, 180) AS snip
                   FROM notes WHERE title LIKE ? OR text LIKE ?
                   ORDER BY created_at DESC LIMIT ?""",
                (like, like, limit),
            ).fetchall()
        return [_row_to_hit(r) for r in rows]
    finally:
        con.close()


def recent(staging_dir: Path, limit: int = 15) -> list[Hit]:
    con = _connect(staging_dir)
    try:
        rows = con.execute(
            """SELECT id, title, domain, created_at, source_ref, note_path, text AS txt,
                      substr(text, 1, 180) AS snip
               FROM notes ORDER BY created_at DESC LIMIT ?""",
            (limit,),
        ).fetchall()
        return [_row_to_hit(r) for r in rows]
    finally:
        con.close()


def find_by_ref(source_ref: str, staging_dir: Path) -> str | None:
    """The id of the note already made from this source, if any (idempotency).

    Matches on canonical identity, so `?t=78s`, `?si=…` and the `youtu.be` short
    form all resolve to the note that already exists.
    """
    from .canonical import canonical_url

    if not source_ref or source_ref == "text":
        return None  # pasted text has no stable identity
    con = _connect(staging_dir)
    try:
        row = con.execute(
            "SELECT id FROM notes WHERE canon = ? ORDER BY created_at ASC LIMIT 1",
            (canonical_url(source_ref),),
        ).fetchone()
        return row["id"] if row else None
    finally:
        con.close()


def dedupe(staging_dir: Path) -> list[tuple[str, int]]:
    """Collapse rows that are the same source under different URLs.

    Returns [(title, rows_merged)]. The OLDEST note of a group survives (its id is
    what keep/drop verdicts point at); claims and verdicts from the duplicates are
    re-pointed onto it. Note files on disk are never touched.
    """
    con = _connect(staging_dir)
    merged: list[tuple[str, int]] = []
    try:
        groups = con.execute(
            """SELECT canon, COUNT(*) AS n FROM notes
               WHERE canon IS NOT NULL AND canon != '' AND source_kind != 'text'
               GROUP BY canon HAVING n > 1"""
        ).fetchall()
        for group in groups:
            rows = con.execute(
                "SELECT id, title FROM notes WHERE canon = ? ORDER BY created_at ASC",
                (group["canon"],),
            ).fetchall()
            keeper, dupes = rows[0], rows[1:]
            for dupe in dupes:
                con.execute("UPDATE OR IGNORE claims SET note_id = ? WHERE note_id = ?", (keeper["id"], dupe["id"]))
                con.execute("UPDATE OR IGNORE feedback SET note_id = ? WHERE note_id = ?", (keeper["id"], dupe["id"]))
                con.execute("DELETE FROM notes WHERE id = ?", (dupe["id"],))
                if _fts_available(con):
                    con.execute("DELETE FROM notes_fts WHERE id = ?", (dupe["id"],))
                    con.execute("UPDATE claims_fts SET note_id = ? WHERE note_id = ?", (keeper["id"], dupe["id"]))
            merged.append((keeper["title"], len(dupes)))
        con.commit()
        return merged
    finally:
        con.close()


def find_related(text: str, staging_dir: Path, exclude_ref: str = "", limit: int = 3) -> list[Hit]:
    """Notes already in the library that relate to this material."""
    query = keywords(text)
    if not query:
        return []
    hits = search(query, staging_dir, limit=limit + 4)
    return [h for h in hits if h.source_ref != exclude_ref][:limit]


# ---------- claim ledger ----------

def index_claims(
    note_id: str, claims: list[str], staging_dir: Path, shelf_life_days: int = 0
) -> None:
    """Record a note's claims — each with the date it should be re-checked.

    A stock price is stale tomorrow; a mathematical fact is not stale in a decade.
    `shelf_life_days` (estimated by the analyzer) turns the ledger from a pile into
    something with a sense of time (`smelt stale`).
    """
    if not claims:
        return
    con = _connect(staging_dir)
    try:
        _ensure_claim_expiry(con)
        # Re-ingesting the same source replaces its claims — never stacks them.
        con.execute("DELETE FROM claims WHERE note_id = ?", (note_id,))
        if _fts_available(con):
            con.execute("DELETE FROM claims_fts WHERE note_id = ?", (note_id,))
        expires = (
            f"datetime('now', '{int(shelf_life_days):+d} days')" if shelf_life_days else "NULL"
        )
        for claim in claims:
            con.execute(
                f"""INSERT INTO claims (note_id, claim, created_at, expires_at)
                    VALUES (?,?,datetime('now'), {expires})""",
                (note_id, claim),
            )
            if _fts_available(con):
                con.execute("INSERT INTO claims_fts (claim, note_id) VALUES (?,?)", (claim, note_id))
        con.commit()
    finally:
        con.close()


def _ensure_claim_expiry(con: sqlite3.Connection) -> None:
    columns = {r["name"] for r in con.execute("PRAGMA table_info(claims)")}
    if "expires_at" not in columns:
        con.execute("ALTER TABLE claims ADD COLUMN expires_at TEXT")


def stale_claims(staging_dir: Path, limit: int = 40) -> list[dict]:
    """Claims whose shelf life has run out — they should be checked again."""
    con = _connect(staging_dir)
    try:
        _ensure_claim_expiry(con)
        rows = con.execute(
            """SELECT c.claim AS claim, c.expires_at AS expires_at,
                      COALESCE(n.title, c.note_id) AS title,
                      COALESCE(s.label, n.source_key, '?') AS source
               FROM claims c
               LEFT JOIN notes n ON n.id = c.note_id
               LEFT JOIN sources s ON s.key = n.source_key
               WHERE c.expires_at IS NOT NULL AND c.expires_at <= datetime('now')
               ORDER BY c.expires_at ASC LIMIT ?""",
            (limit,),
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        con.close()


def find_related_claims(
    claim: str, staging_dir: Path, exclude_note: str = "", limit: int = 3
) -> list[tuple[str, str]]:
    """Past claims that touch the same subject — the raw material for contradiction checks."""
    query = keywords(claim)
    if not query:
        return []
    con = _connect(staging_dir)
    try:
        if _fts_available(con):
            rows = con.execute(
                "SELECT claim, note_id FROM claims_fts WHERE claims_fts MATCH ? LIMIT ?",
                (query, limit + 4),
            ).fetchall()
        else:
            rows = con.execute(
                "SELECT claim, note_id FROM claims WHERE claim LIKE ? LIMIT ?",
                (f"%{claim[:40]}%", limit + 4),
            ).fetchall()
        return [(r["claim"], r["note_id"]) for r in rows if r["note_id"] != exclude_note][:limit]
    finally:
        con.close()


def claim_origin(claim_text: str, staging_dir: Path) -> dict | None:
    """Where a claim came from — and whether you KEPT that note.

    A source contradicting a source is noise. A source contradicting something you
    decided to keep is you contradicting yourself, and that deserves a louder line.
    """
    con = _connect(staging_dir)
    try:
        row = con.execute(
            """SELECT c.note_id AS note_id, n.title AS title, COALESCE(f.verdict, '') AS verdict,
                      COALESCE(s.label, n.source_key, '?') AS source
               FROM claims c
               LEFT JOIN notes n ON n.id = c.note_id
               LEFT JOIN feedback f ON f.note_id = c.note_id
               LEFT JOIN sources s ON s.key = n.source_key
               WHERE c.claim = ? LIMIT 1""",
            (claim_text,),
        ).fetchone()
        return dict(row) if row and row["title"] else None
    finally:
        con.close()


def record_contradiction(
    new_note: str, old_note: str, claim: str, against: str, why: str, staging_dir: Path
) -> None:
    con = _connect(staging_dir)
    try:
        con.execute(
            """INSERT INTO contradictions (new_note, old_note, claim, against, why, at)
               VALUES (?,?,?,?,?,datetime('now'))""",
            (new_note, old_note, claim, against, why),
        )
        con.commit()
    finally:
        con.close()


def contradictions_against(note_id: str, staging_dir: Path) -> list[dict]:
    """What has been said SINCE, that cuts against this note."""
    con = _connect(staging_dir)
    try:
        rows = con.execute(
            """SELECT c.claim AS claim, c.against AS against, c.why AS why, c.at AS at,
                      COALESCE(n.title, '?') AS by_title,
                      COALESCE(s.label, n.source_key, '?') AS by_source
               FROM contradictions c
               LEFT JOIN notes n ON n.id = c.new_note
               LEFT JOIN sources s ON s.key = n.source_key
               WHERE c.old_note = ? ORDER BY c.at DESC""",
            (note_id,),
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        con.close()


def expired_claims_of(note_id: str, staging_dir: Path) -> list[str]:
    con = _connect(staging_dir)
    try:
        _ensure_claim_expiry(con)
        rows = con.execute(
            """SELECT claim FROM claims
               WHERE note_id = ? AND expires_at IS NOT NULL AND expires_at <= datetime('now')""",
            (note_id,),
        ).fetchall()
        return [r["claim"] for r in rows]
    finally:
        con.close()


def missed_predictions_of(note_id: str, staging_dir: Path) -> list[str]:
    con = _connect(staging_dir)
    try:
        rows = con.execute(
            "SELECT text FROM predictions WHERE note_id = ? AND status = 'miss'", (note_id,)
        ).fetchall()
        return [r["text"] for r in rows]
    finally:
        con.close()


def notes_with_history(staging_dir: Path, limit: int = 500) -> list[dict]:
    """Every note that something has happened to since it was written."""
    con = _connect(staging_dir)
    try:
        rows = con.execute(
            """SELECT DISTINCT n.id AS id, n.title AS title, n.note_path AS note_path,
                      COALESCE(n.source_key, '') AS source_key
               FROM notes n
               LEFT JOIN contradictions c ON c.old_note = n.id
               LEFT JOIN claims cl ON cl.note_id = n.id
               LEFT JOIN predictions p ON p.note_id = n.id
               LEFT JOIN sources s ON s.key = n.source_key
               WHERE c.id IS NOT NULL
                  OR (cl.expires_at IS NOT NULL AND cl.expires_at <= datetime('now'))
                  OR p.status = 'miss'
                  OR s.hostile > 0 OR s.misses > 0
               LIMIT ?""",
            (limit,),
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        con.close()


def claims_of(note_id: str, staging_dir: Path) -> list[str]:
    con = _connect(staging_dir)
    try:
        rows = con.execute("SELECT claim FROM claims WHERE note_id = ?", (note_id,)).fetchall()
        return [r["claim"] for r in rows]
    finally:
        con.close()


def all_claims(staging_dir: Path, limit: int = 50) -> list[tuple[str, str]]:
    con = _connect(staging_dir)
    try:
        rows = con.execute(
            """SELECT c.claim AS claim, COALESCE(n.title, c.note_id) AS src
               FROM claims c LEFT JOIN notes n ON n.id = c.note_id
               ORDER BY c.id DESC LIMIT ?""",
            (limit,),
        ).fetchall()
        return [(r["claim"], r["src"]) for r in rows]
    finally:
        con.close()


# ---------- sources (the record of who said it) ----------

def source_rows(staging_dir: Path, limit: int = 30) -> list[dict]:
    con = _connect(staging_dir)
    try:
        rows = con.execute(
            """SELECT s.key AS key,
                      COALESCE(s.label, s.key) AS label,
                      COUNT(n.id) AS notes,
                      SUM(CASE WHEN f.verdict = 'kept' THEN 1 ELSE 0 END) AS kept,
                      SUM(CASE WHEN f.verdict = 'dropped' THEN 1 ELSE 0 END) AS dropped,
                      COALESCE(SUM(n.minutes), 0) AS minutes,
                      COALESCE(SUM(n.ideas), 0) AS ideas,
                      SUM(CASE WHEN n.engine LIKE 'llm:%' THEN 1 ELSE 0 END) AS analyzed,
                      s.hits AS hits, s.misses AS misses, s.hostile AS hostile
               FROM sources s
               LEFT JOIN notes n ON n.source_key = s.key
               LEFT JOIN feedback f ON f.note_id = n.id
               GROUP BY s.key
               ORDER BY notes DESC, minutes DESC
               LIMIT ?""",
            (limit,),
        ).fetchall()
        return [
            {
                "key": r["key"], "label": r["label"], "notes": r["notes"] or 0,
                "kept": r["kept"] or 0, "dropped": r["dropped"] or 0,
                "minutes": round(r["minutes"] or 0.0, 1), "ideas": r["ideas"] or 0,
                "analyzed": r["analyzed"] or 0,
                "hits": r["hits"] or 0, "misses": r["misses"] or 0, "hostile": r["hostile"] or 0,
            }
            for r in rows
        ]
    finally:
        con.close()


def source_of(note_id: str, staging_dir: Path) -> str:
    con = _connect(staging_dir)
    try:
        row = con.execute("SELECT source_key FROM notes WHERE id = ?", (note_id,)).fetchone()
        return (row["source_key"] or "") if row else ""
    finally:
        con.close()


def mark_source(key: str, field: str, staging_dir: Path, amount: int = 1) -> None:
    """Write a hit / miss / hostile mark onto a source's permanent record."""
    if field not in ("hits", "misses", "hostile"):
        raise ValueError("field must be hits, misses or hostile")
    con = _connect(staging_dir)
    try:
        con.execute(
            f"""INSERT INTO sources (key, label, first_seen, {field})
                VALUES (?, ?, datetime('now'), ?)
                ON CONFLICT(key) DO UPDATE SET {field} = {field} + ?""",
            (key, key, amount, amount),
        )
        con.commit()
    finally:
        con.close()


def source_standing(key: str, staging_dir: Path) -> dict | None:
    for row in source_rows(staging_dir, limit=500):
        if row["key"] == key:
            return row
    return None


# ---------- predictions (the scoreboard) ----------

def replace_predictions(
    note_id: str, source_key: str, rows: list[tuple[str, str]], staging_dir: Path
) -> int:
    """Set this note's predictions. Judged ones are never silently overwritten."""
    con = _connect(staging_dir)
    try:
        # A party that makes predictions has a record, even before it is judged.
        con.execute(
            """INSERT INTO sources (key, label, first_seen) VALUES (?,?,datetime('now'))
               ON CONFLICT(key) DO NOTHING""",
            (source_key, source_key),
        )
        con.execute("DELETE FROM predictions WHERE note_id = ? AND status = 'open'", (note_id,))
        for text, due in rows:
            existing = con.execute(
                "SELECT id FROM predictions WHERE note_id = ? AND text = ?", (note_id, text)
            ).fetchone()
            if existing:
                continue  # already on the record (possibly already judged)
            con.execute(
                """INSERT INTO predictions (note_id, source_key, text, due, status, created_at)
                   VALUES (?,?,?,?, 'open', datetime('now'))""",
                (note_id, source_key, text, due),
            )
        con.commit()
        return len(rows)
    finally:
        con.close()


def prediction_rows(staging_dir: Path) -> list[dict]:
    con = _connect(staging_dir)
    try:
        rows = con.execute(
            """SELECT p.id, p.text, p.due, p.status, p.note_id, p.created_at,
                      COALESCE(p.source_key, '') AS source_key,
                      COALESCE(s.label, p.source_key, '?') AS source_label
               FROM predictions p LEFT JOIN sources s ON s.key = p.source_key
               ORDER BY p.due ASC"""
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        con.close()


def set_prediction_status(prediction_id: int, status: str, staging_dir: Path) -> dict | None:
    con = _connect(staging_dir)
    try:
        con.execute("UPDATE predictions SET status = ? WHERE id = ?", (status, prediction_id))
        con.commit()
        row = con.execute(
            """SELECT p.id, p.text, p.due, p.status, p.note_id, p.created_at,
                      COALESCE(p.source_key, '') AS source_key,
                      COALESCE(s.label, p.source_key, '?') AS source_label
               FROM predictions p LEFT JOIN sources s ON s.key = p.source_key
               WHERE p.id = ?""",
            (prediction_id,),
        ).fetchone()
        return dict(row) if row else None
    finally:
        con.close()


# ---------- vectors (meaning) ----------

def store_vector(note_id: str, blob: bytes, staging_dir: Path) -> None:
    con = _connect(staging_dir)
    try:
        con.execute("INSERT OR REPLACE INTO vectors (note_id, vec) VALUES (?,?)", (note_id, blob))
        con.commit()
    finally:
        con.close()


def all_vectors(staging_dir: Path) -> list[tuple[str, bytes]]:
    con = _connect(staging_dir)
    try:
        rows = con.execute("SELECT note_id, vec FROM vectors").fetchall()
        return [(r["note_id"], r["vec"]) for r in rows]
    finally:
        con.close()


def notes_without_vectors(staging_dir: Path) -> list[tuple[str, str, str]]:
    con = _connect(staging_dir)
    try:
        rows = con.execute(
            """SELECT n.id, n.title, n.text FROM notes n
               LEFT JOIN vectors v ON v.note_id = n.id WHERE v.note_id IS NULL"""
        ).fetchall()
        return [(r["id"], r["title"], r["text"] or "") for r in rows]
    finally:
        con.close()


def note_row(note_id: str, staging_dir: Path) -> dict | None:
    """A staged note by id (a prefix is enough)."""
    con = _connect(staging_dir)
    try:
        row = con.execute(
            "SELECT * FROM notes WHERE id = ? OR id LIKE ? LIMIT 1", (note_id, f"{note_id}%")
        ).fetchone()
        return dict(row) if row else None
    finally:
        con.close()


def hits_by_id(ids: list[str], staging_dir: Path) -> dict[str, Hit]:
    if not ids:
        return {}
    con = _connect(staging_dir)
    try:
        marks = ",".join("?" for _ in ids)
        rows = con.execute(
            f"""SELECT id, title, domain, created_at, source_ref, note_path, text AS txt,
                       substr(text, 1, 180) AS snip
                FROM notes WHERE id IN ({marks})""",
            ids,
        ).fetchall()
        return {r["id"]: _row_to_hit(r) for r in rows}
    finally:
        con.close()


# ---------- the mirror ----------

def mirror_rows(staging_dir: Path, days: int = 30) -> dict:
    """The honest ledger for a period: material in, notes out, verdicts given."""
    con = _connect(staging_dir)
    window = f"-{max(1, int(days))} days"
    try:
        totals = con.execute(
            """SELECT COUNT(*) AS notes,
                      COALESCE(SUM(n.minutes), 0) AS minutes,
                      COALESCE(SUM(n.ideas), 0) AS ideas,
                      SUM(CASE WHEN n.engine LIKE 'llm:%' THEN 1 ELSE 0 END) AS analyzed,
                      SUM(CASE WHEN n.action = 'task' THEN 1 ELSE 0 END) AS tasks,
                      SUM(CASE WHEN f.verdict = 'kept' THEN 1 ELSE 0 END) AS kept,
                      SUM(CASE WHEN f.verdict = 'dropped' THEN 1 ELSE 0 END) AS dropped,
                      SUM(CASE WHEN f.verdict IS NULL THEN 1 ELSE 0 END) AS unjudged
               FROM notes n LEFT JOIN feedback f ON f.note_id = n.id
               WHERE n.created_at >= datetime('now', ?)""",
            (window,),
        ).fetchone()

        kinds = con.execute(
            """SELECT source_kind AS kind, COUNT(*) AS n FROM notes
               WHERE created_at >= datetime('now', ?) GROUP BY source_kind""",
            (window,),
        ).fetchall()

        sinks = con.execute(
            """SELECT COALESCE(s.label, n.source_key, '?') AS source,
                      COALESCE(SUM(n.minutes), 0) AS minutes,
                      SUM(CASE WHEN f.verdict = 'kept' THEN 1 ELSE 0 END) AS kept
               FROM notes n
               LEFT JOIN sources s ON s.key = n.source_key
               LEFT JOIN feedback f ON f.note_id = n.id
               WHERE n.created_at >= datetime('now', ?)
               GROUP BY n.source_key ORDER BY minutes DESC LIMIT 5""",
            (window,),
        ).fetchall()

        hostile = con.execute("SELECT COALESCE(SUM(hostile), 0) AS n FROM sources").fetchone()

        return {
            "notes": totals["notes"] or 0,
            "minutes": round(totals["minutes"] or 0.0, 1),
            "ideas": totals["ideas"] or 0,
            "analyzed": totals["analyzed"] or 0,
            "tasks": totals["tasks"] or 0,
            "kept": totals["kept"] or 0,
            "dropped": totals["dropped"] or 0,
            "unjudged": totals["unjudged"] or 0,
            "hostile": hostile["n"] or 0,
            "by_kind": {r["kind"]: r["n"] for r in kinds},
            "time_sinks": [
                (r["source"], round(r["minutes"] or 0.0, 1), r["kept"] or 0) for r in sinks
            ],
        }
    finally:
        con.close()


def kept_hits(query: str, staging_dir: Path, limit: int = 12) -> list[dict]:
    """Notes on a topic that you KEPT — the material your opinion actually rests on."""
    con = _connect(staging_dir)
    try:
        if _fts_available(con):
            rows = con.execute(
                """SELECT n.id, n.title, n.text, COALESCE(n.source_key, '') AS source_key,
                          COALESCE(s.label, n.source_key, '?') AS source
                   FROM notes_fts f
                   JOIN notes n ON n.id = f.id
                   JOIN feedback fb ON fb.note_id = n.id AND fb.verdict = 'kept'
                   LEFT JOIN sources s ON s.key = n.source_key
                   WHERE notes_fts MATCH ? ORDER BY rank LIMIT ?""",
                (query, limit),
            ).fetchall()
        else:
            like = f"%{query}%"
            rows = con.execute(
                """SELECT n.id, n.title, n.text, COALESCE(n.source_key, '') AS source_key,
                          COALESCE(s.label, n.source_key, '?') AS source
                   FROM notes n
                   JOIN feedback fb ON fb.note_id = n.id AND fb.verdict = 'kept'
                   LEFT JOIN sources s ON s.key = n.source_key
                   WHERE n.title LIKE ? OR n.text LIKE ? LIMIT ?""",
                (like, like, limit),
            ).fetchall()
        return [dict(r) for r in rows]
    finally:
        con.close()


def kept_rows(staging_dir: Path, limit: int = 50, since_days: int | None = None) -> list[dict]:
    con = _connect(staging_dir)
    try:
        window = "AND f.created_at >= datetime('now', ?)" if since_days else ""
        params: list = []
        if since_days:
            params.append(f"-{int(since_days)} days")
        params.append(limit)
        rows = con.execute(
            f"""SELECT n.id AS id, n.title AS title, n.domain AS domain, n.note_path AS note_path,
                       n.created_at AS created_at,
                       COALESCE(s.label, n.source_key, '?') AS source
                FROM feedback f
                JOIN notes n ON n.id = f.note_id
                LEFT JOIN sources s ON s.key = n.source_key
                WHERE f.verdict = 'kept' {window}
                ORDER BY f.created_at DESC LIMIT ?""",
            params,
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        con.close()


def dropped_rows(staging_dir: Path, limit: int = 30) -> list[dict]:
    con = _connect(staging_dir)
    try:
        rows = con.execute(
            """SELECT n.id AS id, n.title AS title, n.domain AS domain,
                      n.created_at AS created_at,
                      COALESCE(s.label, n.source_key, '?') AS source,
                      '' AS reason
               FROM feedback f
               JOIN notes n ON n.id = f.note_id
               LEFT JOIN sources s ON s.key = n.source_key
               WHERE f.verdict = 'dropped'
               ORDER BY f.created_at DESC LIMIT ?""",
            (limit,),
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        con.close()


# ---------- questions (the real routing target) ----------

_QUESTION_SELECT = """
    SELECT q.id AS id, q.text AS text, q.status AS status, q.created_at AS created_at,
           SUM(CASE WHEN e.stance = 'advances' THEN 1 ELSE 0 END) AS evidence,
           SUM(CASE WHEN e.stance = 'contradicts' THEN 1 ELSE 0 END) AS against
    FROM questions q LEFT JOIN evidence e ON e.question_id = q.id
"""


def question_add(text: str, staging_dir: Path) -> dict:
    con = _connect(staging_dir)
    try:
        cursor = con.execute(
            "INSERT INTO questions (text, status, created_at) VALUES (?, 'open', datetime('now'))",
            (text,),
        )
        con.commit()
        row = con.execute(
            f"{_QUESTION_SELECT} WHERE q.id = ? GROUP BY q.id", (cursor.lastrowid,)
        ).fetchone()
        return _question_dict(row)
    finally:
        con.close()


def question_rows(staging_dir: Path) -> list[dict]:
    con = _connect(staging_dir)
    try:
        rows = con.execute(f"{_QUESTION_SELECT} GROUP BY q.id ORDER BY q.id ASC").fetchall()
        return [_question_dict(r) for r in rows]
    finally:
        con.close()


def question_row(question_id: int, staging_dir: Path) -> dict | None:
    con = _connect(staging_dir)
    try:
        row = con.execute(
            f"{_QUESTION_SELECT} WHERE q.id = ? GROUP BY q.id", (question_id,)
        ).fetchone()
        return _question_dict(row) if row and row["text"] else None
    finally:
        con.close()


def _question_dict(row: sqlite3.Row) -> dict:
    return {
        "id": row["id"], "text": row["text"], "status": row["status"],
        "created_at": row["created_at"], "evidence": row["evidence"] or 0,
        "against": row["against"] or 0,
    }


def question_remove(question_id: int, staging_dir: Path) -> bool:
    con = _connect(staging_dir)
    try:
        cursor = con.execute("DELETE FROM questions WHERE id = ?", (question_id,))
        con.execute("DELETE FROM evidence WHERE question_id = ?", (question_id,))
        con.commit()
        return cursor.rowcount > 0
    finally:
        con.close()


def question_close(question_id: int, staging_dir: Path) -> bool:
    con = _connect(staging_dir)
    try:
        cursor = con.execute(
            "UPDATE questions SET status = 'answered' WHERE id = ?", (question_id,)
        )
        con.commit()
        return cursor.rowcount > 0
    finally:
        con.close()


def evidence_add(question_id: int, note_id: str, stance: str, why: str, staging_dir: Path) -> None:
    con = _connect(staging_dir)
    try:
        con.execute(
            """INSERT OR REPLACE INTO evidence (question_id, note_id, stance, why, added_at)
               VALUES (?,?,?,?,datetime('now'))""",
            (question_id, note_id, stance, why),
        )
        con.commit()
    finally:
        con.close()


def evidence_for(question_id: int, staging_dir: Path) -> list[dict]:
    con = _connect(staging_dir)
    try:
        rows = con.execute(
            """SELECT e.stance AS stance, e.why AS why, n.title AS title, n.text AS text,
                      COALESCE(s.label, n.source_key, '?') AS source
               FROM evidence e
               JOIN notes n ON n.id = e.note_id
               LEFT JOIN sources s ON s.key = n.source_key
               WHERE e.question_id = ? ORDER BY e.added_at ASC""",
            (question_id,),
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        con.close()


# ---------- the model bake-off ----------

def bakeoff_record(
    note_id: str, model: str, proposed: str, confidence: float, staging_dir: Path
) -> None:
    con = _connect(staging_dir)
    try:
        con.execute(
            """INSERT OR REPLACE INTO bakeoff (note_id, model, proposed, confidence, at)
               VALUES (?,?,?,?,datetime('now'))""",
            (note_id, model, proposed, float(confidence)),
        )
        con.commit()
    finally:
        con.close()


def bakeoff_rows(staging_dir: Path) -> list[dict]:
    """Each model's proposal, joined to what the human actually decided afterwards."""
    con = _connect(staging_dir)
    try:
        rows = con.execute(
            """SELECT b.note_id, b.model, b.proposed, b.confidence,
                      COALESCE(f.verdict, '') AS verdict
               FROM bakeoff b LEFT JOIN feedback f ON f.note_id = b.note_id"""
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        con.close()


# ---------- the outbound ledger (what left this machine, and what it cost) ----------

def record_outbound(
    provider: str, model: str, purpose: str, chars: int, note_id: str, cost: float, staging_dir: Path
) -> None:
    con = _connect(staging_dir)
    try:
        con.execute(
            """INSERT INTO outbound (at, provider, model, purpose, chars, note_id, cost)
               VALUES (datetime('now'),?,?,?,?,?,?)""",
            (provider, model, purpose, int(chars), note_id, float(cost)),
        )
        con.commit()
    finally:
        con.close()


def outbound_rows(staging_dir: Path, days: int = 30) -> list[dict]:
    con = _connect(staging_dir)
    try:
        rows = con.execute(
            """SELECT provider, model, purpose, COUNT(*) AS calls,
                      SUM(chars) AS chars, SUM(cost) AS cost
               FROM outbound WHERE at >= datetime('now', ?)
               GROUP BY provider, model, purpose ORDER BY chars DESC""",
            (f"-{int(days)} days",),
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        con.close()


def outbound_total(staging_dir: Path, days: int = 30) -> tuple[int, float]:
    con = _connect(staging_dir)
    try:
        row = con.execute(
            "SELECT COALESCE(SUM(chars),0) AS chars, COALESCE(SUM(cost),0) AS cost "
            "FROM outbound WHERE at >= datetime('now', ?)",
            (f"-{int(days)} days",),
        ).fetchone()
        return int(row["chars"]), float(row["cost"])
    finally:
        con.close()


# ---------- signals, state, the furnace log ----------

def add_highlight(note_id: str, text: str, staging_dir: Path) -> None:
    """What YOU marked — as opposed to what the source claimed. Not the same thing."""
    con = _connect(staging_dir)
    try:
        con.execute(
            "INSERT INTO highlights (note_id, text, at) VALUES (?,?,datetime('now'))",
            (note_id, text.strip()),
        )
        con.commit()
    finally:
        con.close()


def highlights_of(note_id: str, staging_dir: Path) -> list[str]:
    con = _connect(staging_dir)
    try:
        rows = con.execute(
            "SELECT text FROM highlights WHERE note_id = ? ORDER BY id ASC", (note_id,)
        ).fetchall()
        return [r["text"] for r in rows]
    finally:
        con.close()


def add_signal(note_id: str, kind: str, staging_dir: Path) -> None:
    """A thing you did to a note. Behaviour is a verdict you did not have to type."""
    con = _connect(staging_dir)
    try:
        con.execute(
            "INSERT INTO signals (note_id, kind, at) VALUES (?,?,datetime('now'))", (note_id, kind)
        )
        con.commit()
    finally:
        con.close()


def signal_counts(staging_dir: Path) -> dict[str, dict[str, int]]:
    con = _connect(staging_dir)
    try:
        rows = con.execute(
            "SELECT note_id, kind, COUNT(*) AS n FROM signals GROUP BY note_id, kind"
        ).fetchall()
        out: dict[str, dict[str, int]] = {}
        for r in rows:
            out.setdefault(r["note_id"], {})[r["kind"]] = r["n"]
        return out
    finally:
        con.close()


def untouched_notes(staging_dir: Path, days: int, limit: int = 200) -> list[dict]:
    """Notes older than `days` that you never judged and never touched again.

    Silence is data. Not a loud verdict — a quiet one.
    """
    con = _connect(staging_dir)
    try:
        rows = con.execute(
            """SELECT n.id AS id, n.title AS title, n.domain AS domain, n.created_at AS created_at,
                      COALESCE(s.label, n.source_key, '?') AS source
               FROM notes n
               LEFT JOIN feedback f ON f.note_id = n.id
               LEFT JOIN signals g ON g.note_id = n.id
               LEFT JOIN sources s ON s.key = n.source_key
               WHERE f.note_id IS NULL AND g.note_id IS NULL
                 AND n.created_at <= datetime('now', ?)
               GROUP BY n.id ORDER BY n.created_at ASC LIMIT ?""",
            (f"-{int(days)} days", limit),
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        con.close()


def get_state(key: str, staging_dir: Path, default: str = "") -> str:
    con = _connect(staging_dir)
    try:
        row = con.execute("SELECT value FROM state WHERE key = ?", (key,)).fetchone()
        return row["value"] if row else default
    finally:
        con.close()


def set_state(key: str, value: str, staging_dir: Path) -> None:
    con = _connect(staging_dir)
    try:
        con.execute("INSERT OR REPLACE INTO state (key, value) VALUES (?,?)", (key, value))
        con.commit()
    finally:
        con.close()


def log_event(action: str, subject: str, detail: str, staging_dir: Path) -> None:
    """The furnace log: every act, appended, never rewritten."""
    con = _connect(staging_dir)
    try:
        con.execute(
            "INSERT INTO events (at, action, subject, detail) VALUES (datetime('now'),?,?,?)",
            (action, subject, detail),
        )
        con.commit()
    finally:
        con.close()


def event_rows(staging_dir: Path, limit: int = 40) -> list[dict]:
    con = _connect(staging_dir)
    try:
        rows = con.execute(
            "SELECT at, action, subject, detail FROM events ORDER BY id DESC LIMIT ?", (limit,)
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        con.close()


# ---------- local files (the folder that empties itself) ----------

def seen_file(path: str, fingerprint: str, staging_dir: Path) -> bool:
    con = _connect(staging_dir)
    try:
        row = con.execute("SELECT fingerprint FROM files WHERE path = ?", (path,)).fetchone()
        return bool(row) and row["fingerprint"] == fingerprint
    finally:
        con.close()


def mark_file_seen(path: str, fingerprint: str, note_id: str, staging_dir: Path) -> None:
    con = _connect(staging_dir)
    try:
        con.execute(
            """INSERT OR REPLACE INTO files (path, fingerprint, note_id, seen_at)
               VALUES (?,?,?,datetime('now'))""",
            (path, fingerprint, note_id),
        )
        con.commit()
    finally:
        con.close()


# ---------- feeds (the editor) ----------

def feed_add(url: str, title: str, staging_dir: Path) -> None:
    con = _connect(staging_dir)
    try:
        con.execute(
            """INSERT INTO feeds (url, title, added_at, last_run) VALUES (?,?,datetime('now'),'')
               ON CONFLICT(url) DO UPDATE SET title = excluded.title""",
            (url, title),
        )
        con.commit()
    finally:
        con.close()


def feed_rows(staging_dir: Path) -> list[dict]:
    con = _connect(staging_dir)
    try:
        rows = con.execute("SELECT * FROM feeds ORDER BY added_at ASC").fetchall()
        return [dict(r) for r in rows]
    finally:
        con.close()


def feed_remove(url: str, staging_dir: Path) -> bool:
    con = _connect(staging_dir)
    try:
        cursor = con.execute("DELETE FROM feeds WHERE url = ?", (url,))
        con.commit()
        return cursor.rowcount > 0
    finally:
        con.close()


def feed_item_seen(guid: str, staging_dir: Path) -> bool:
    con = _connect(staging_dir)
    try:
        return con.execute("SELECT 1 FROM feed_items WHERE guid = ?", (guid,)).fetchone() is not None
    finally:
        con.close()


def feed_item_mark(guid: str, feed_url: str, staging_dir: Path) -> None:
    con = _connect(staging_dir)
    try:
        con.execute(
            "INSERT OR IGNORE INTO feed_items (guid, feed_url, seen_at) VALUES (?,?,datetime('now'))",
            (guid, feed_url),
        )
        con.commit()
    finally:
        con.close()


def feed_tally(url: str, seen: int, passed: int, staging_dir: Path) -> None:
    con = _connect(staging_dir)
    try:
        con.execute(
            """UPDATE feeds SET last_run = datetime('now'), seen = seen + ?, passed = passed + ?
               WHERE url = ?""",
            (seen, passed, url),
        )
        con.commit()
    finally:
        con.close()


# ---------- watchlist (sources that move after you read them) ----------

_WATCH_FIELDS = "url, label, added_at, last_checked, last_changed, changes"


def watch_upsert(url: str, label: str, text: str, digest: str, staging_dir: Path) -> dict:
    con = _connect(staging_dir)
    try:
        con.execute(
            """INSERT INTO watchlist (url, label, added_at, last_checked, last_changed, changes, digest, text)
               VALUES (?,?,datetime('now'),datetime('now'),'',0,?,?)
               ON CONFLICT(url) DO UPDATE SET label = excluded.label""",
            (url, label, digest, text),
        )
        con.commit()
        row = con.execute(f"SELECT {_WATCH_FIELDS} FROM watchlist WHERE url = ?", (url,)).fetchone()
        return dict(row)
    finally:
        con.close()


def watch_rows(staging_dir: Path) -> list[dict]:
    con = _connect(staging_dir)
    try:
        rows = con.execute(f"SELECT {_WATCH_FIELDS} FROM watchlist ORDER BY added_at ASC").fetchall()
        return [dict(r) for r in rows]
    finally:
        con.close()


def watch_state(url: str, staging_dir: Path) -> dict | None:
    con = _connect(staging_dir)
    try:
        row = con.execute("SELECT digest, text FROM watchlist WHERE url = ?", (url,)).fetchone()
        return dict(row) if row else None
    finally:
        con.close()


def watch_mark(
    url: str, digest: str, changed: bool, staging_dir: Path, text: str | None = None
) -> None:
    con = _connect(staging_dir)
    try:
        if changed:
            con.execute(
                """UPDATE watchlist SET digest = ?, text = ?, last_checked = datetime('now'),
                       last_changed = datetime('now'), changes = changes + 1 WHERE url = ?""",
                (digest, text or "", url),
            )
        else:
            con.execute(
                "UPDATE watchlist SET last_checked = datetime('now') WHERE url = ?", (url,)
            )
        con.commit()
    finally:
        con.close()


def watch_remove(url: str, staging_dir: Path) -> bool:
    con = _connect(staging_dir)
    try:
        cursor = con.execute("DELETE FROM watchlist WHERE url = ?", (url,))
        con.commit()
        return cursor.rowcount > 0
    finally:
        con.close()


# ---------- feedback (learned relevance) ----------

def _ensure_feedback_origin(con: sqlite3.Connection) -> None:
    columns = {r["name"] for r in con.execute("PRAGMA table_info(feedback)")}
    if "origin" not in columns:
        con.execute("ALTER TABLE feedback ADD COLUMN origin TEXT DEFAULT 'explicit'")
    if "weight" not in columns:
        con.execute("ALTER TABLE feedback ADD COLUMN weight REAL DEFAULT 1.0")


def record_feedback(
    note_id: str,
    verdict: str,
    staging_dir: Path,
    origin: str = "explicit",
    weight: float = 1.0,
) -> Hit | None:
    """Mark a staged note as kept or dropped. Returns the note, or None if unknown.

    A prefix of the id is enough (uuids are long); the first match wins.

    `origin` records WHERE the verdict came from — you said so (`explicit`), you
    accepted the note into a real folder (`accept`), or your behaviour implied it
    (`implicit`, see signals.py). An inferred verdict NEVER overwrites one you
    actually gave: guessing is allowed to fill a silence, never to contradict you.
    """
    if verdict not in ("kept", "dropped"):
        raise ValueError("verdict must be 'kept' or 'dropped'")
    con = _connect(staging_dir)
    try:
        _ensure_feedback_origin(con)
        row = con.execute(
            """SELECT id, title, domain, created_at, source_ref, note_path, text AS txt,
                      substr(text, 1, 180) AS snip
               FROM notes WHERE id = ? OR id LIKE ? LIMIT 1""",
            (note_id, f"{note_id}%"),
        ).fetchone()
        if row is None:
            return None

        if origin == "implicit":
            existing = con.execute(
                "SELECT origin FROM feedback WHERE note_id = ?", (row["id"],)
            ).fetchone()
            if existing and existing["origin"] != "implicit":
                return _row_to_hit(row)  # you already decided; we do not argue

        con.execute(
            """INSERT OR REPLACE INTO feedback
               (note_id, verdict, domain, title, text, created_at, origin, weight)
               VALUES (?,?,?,?,?,datetime('now'),?,?)""",
            (row["id"], verdict, row["domain"], row["title"], row["txt"], origin, float(weight)),
        )
        con.commit()
        return _row_to_hit(row)
    finally:
        con.close()


def feedback_rows(staging_dir: Path) -> list[tuple[str, str, str, str, float]]:
    """(verdict, domain, title, text, weight) for every judged note."""
    con = _connect(staging_dir)
    try:
        _ensure_feedback_origin(con)
        rows = con.execute(
            """SELECT verdict, domain, title, text, COALESCE(weight, 1.0) AS weight
               FROM feedback ORDER BY created_at DESC LIMIT 500"""
        ).fetchall()
        return [
            (r["verdict"], r["domain"], r["title"], r["text"] or "", float(r["weight"]))
            for r in rows
        ]
    except sqlite3.OperationalError:
        return []
    finally:
        con.close()


def verdict_of(note_id: str, staging_dir: Path) -> str:
    con = _connect(staging_dir)
    try:
        row = con.execute("SELECT verdict FROM feedback WHERE note_id = ?", (note_id,)).fetchone()
        return row["verdict"] if row else ""
    finally:
        con.close()


def judged_rows(staging_dir: Path, limit: int = 1000) -> list[dict]:
    """Everything the human (or their behaviour) has ruled on — the ground truth.

    This is what calibration (calibrate.py) measures the ROUTER against: for every
    note, what we proposed, how sure we were, who read it — and what actually
    happened to it.
    """
    con = _connect(staging_dir)
    try:
        _ensure_feedback_origin(con)
        rows = con.execute(
            """SELECT n.id AS id, n.title AS title, n.domain AS domain, n.action AS proposed,
                      n.confidence AS confidence, COALESCE(n.engine, 'heuristic') AS engine,
                      COALESCE(n.lens, 'digest') AS lens,
                      f.verdict AS verdict, COALESCE(f.origin, 'explicit') AS origin,
                      COALESCE(f.weight, 1.0) AS weight
               FROM feedback f JOIN notes n ON n.id = f.note_id
               ORDER BY f.created_at DESC LIMIT ?""",
            (limit,),
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        con.close()


def count(staging_dir: Path) -> int:
    con = _connect(staging_dir)
    try:
        return con.execute("SELECT COUNT(*) FROM notes").fetchone()[0]
    finally:
        con.close()
