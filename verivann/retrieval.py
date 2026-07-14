"""Hybrid retrieval - the one search everything else calls.

Keyword search knows what you typed. Vector search knows what you meant. Neither
is enough on its own: FTS5 misses the note that never used your word, embeddings
miss the exact identifier you are hunting for.

So both run, and the ranks are fused (reciprocal rank fusion - no score
calibration to get wrong, and a note that both methods like rises above one that
only one of them likes). With no embedder configured, this degrades to exactly
what it was before: FTS5, honestly labeled.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .config import Config
from .library import Hit, hits_by_id, keywords, search

_RRF_K = 60  # the standard damping constant: rank 1 is worth 1/61, rank 10 is worth 1/70


@dataclass
class Retrieval:
    hits: list[Hit]
    engine: str  # "fts" | "hybrid"


def retrieve(query: str, config: Config, limit: int = 10) -> Retrieval:
    keyword_hits = search(keywords(query) or query, config.staging_dir, limit=limit)

    from .embed import enabled, semantic_hits

    if not enabled(config):
        return Retrieval(keyword_hits, "fts")

    meaning = semantic_hits(query, config, limit=limit)
    if not meaning:
        return Retrieval(keyword_hits, "fts")

    fused: dict[str, float] = {}
    for rank, hit in enumerate(keyword_hits):
        fused[hit.id] = fused.get(hit.id, 0.0) + 1 / (_RRF_K + rank + 1)
    for rank, scored in enumerate(meaning):
        fused[scored.id] = fused.get(scored.id, 0.0) + 1 / (_RRF_K + rank + 1)

    known = {h.id: h for h in keyword_hits}
    missing = [note_id for note_id in fused if note_id not in known]
    known.update(hits_by_id(missing, config.staging_dir))

    ordered = sorted(fused, key=lambda note_id: fused[note_id], reverse=True)
    return Retrieval([known[i] for i in ordered if i in known][:limit], "hybrid")


def related(text: str, config: Config, exclude_ref: str = "", limit: int = 3) -> list[Hit]:
    """What in the library relates to this material (used at intake)."""
    result = retrieve(text[:1500], config, limit=limit + 4)
    return [h for h in result.hits if h.source_ref != exclude_ref][:limit]


def staging_of(config: Config) -> Path:
    return config.staging_dir
