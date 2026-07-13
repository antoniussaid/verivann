"""Reading it again, properly, once you finally have a model.

Twenty-two notes sat in the library with `engine: heuristic` — which means nobody
had actually *read* them. They were fetched, routed by keyword count, and filed.
And there was no way to fix that: the only path to an analysis went through a fresh
fetch, and a fetch can fail, rate-limit, or return something different than it did
in March.

    verivann reanalyze              everything a model never read
    verivann reanalyze --all        everything, e.g. after switching to a better model
    verivann reanalyze --lens critique

So the material is judged again from what we already stored — the staged JSON event
holds the extraction verbatim. Nothing is re-fetched, no source is touched, and the
note keeps its id, which means its verdicts, its highlights and its place in every
ledger survive.

This is also how a model bake-off becomes possible: the same material, read twice
by two different models, and your own keep/drop verdicts decide which one was right.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from .config import Config
from .schema import Extracted


@dataclass
class Redone:
    note_id: str
    title: str
    was: str  # the engine that read it before
    now: str  # the engine that read it this time
    domain: str
    action: str
    ideas: int


def pending(config: Config, everything: bool = False) -> list[dict]:
    """Notes no model has ever read (or all of them, if you are switching models)."""
    from .library import _connect

    con = _connect(config.staging_dir)
    try:
        where = "" if everything else "WHERE engine IS NULL OR engine NOT LIKE 'llm:%'"
        rows = con.execute(
            f"""SELECT id, source_kind, source_ref, title, event_path,
                       COALESCE(engine, 'heuristic') AS engine
                FROM notes {where} ORDER BY created_at ASC"""
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        con.close()


def reanalyze(
    config: Config | None = None,
    everything: bool = False,
    lens: str | None = None,
    limit: int = 200,
    on_item=None,
) -> list[Redone]:
    """Judge stored material again, with whatever model is configured now."""
    config = config or Config.load()
    if not config.llm.enabled and not config.local_llm.enabled:
        return []  # nothing to gain: the heuristic would just repeat itself

    from .library import log_event
    from .pipeline import judge

    done: list[Redone] = []
    for row in pending(config, everything)[:limit]:
        extracted = _restore(row["event_path"])
        if extracted is None:
            continue
        result = judge(
            row["source_kind"] or "text",
            row["source_ref"] or "text",
            extracted,
            config,
            lens=lens,
            note_id=row["id"],  # the SAME note — verdicts and highlights must survive
        )
        item = Redone(
            note_id=row["id"],
            title=result.event.extracted.title,
            was=row["engine"],
            now=_engine_of(result.event.id, config),
            domain=result.event.routing.domain,
            action=result.event.decision.action,
            ideas=len((result.event.extracted.meta or {}).get("useful_ideas", []) or []),
        )
        done.append(item)
        if on_item:
            on_item(item)
    log_event("reanalyze", "", f"{len(done)} note(s) re-read", config.staging_dir)
    return done


def _restore(event_path: str | None) -> Extracted | None:
    """The extraction, verbatim, as it was when we fetched it. No network involved."""
    if not event_path:
        return None
    try:
        data = json.loads(Path(event_path).read_text(encoding="utf-8"))
        return Extracted(**data["extracted"])
    except (OSError, ValueError, KeyError, TypeError):
        return None


def _engine_of(note_id: str, config: Config) -> str:
    """Which model actually answered — the chain may have fallen through to another."""
    from .library import note_row

    row = note_row(note_id, config.staging_dir)
    return (row or {}).get("engine", "?") or "?"
