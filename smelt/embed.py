"""Meaning, not words.

FTS5 finds "sovereignty" when you type "sovereignty". It does not find the note
about *not depending on someone else's server*, which is what you were actually
thinking of. Embeddings do.

Provider-neutral, like everything else: any OpenAI-compatible `/embeddings`
endpoint (Ollama, OpenAI, LM Studio, OpenRouter). Vectors are stored as float32
blobs next to the notes; ranking is hybrid — the keyword hit and the meaning hit
both count, because each catches what the other misses.

Off by default. Without `SMELT_EMBED_MODEL` the library falls back to FTS5 and
says so, rather than pretending to understand you.
"""

from __future__ import annotations

import math
import struct
from dataclasses import dataclass

import httpx

from .config import Config

_MAX_CHARS = 4000  # what we hand the embedder per note
_BATCH = 16


def enabled(config: Config) -> bool:
    return bool(config.embed.model and config.embed.base_url)


def embed_texts(texts: list[str], config: Config) -> list[list[float]]:
    """One call per batch. Raises on failure — callers decide whether to care."""
    vectors: list[list[float]] = []
    headers = {"content-type": "application/json"}
    if config.embed.api_key:
        headers["authorization"] = f"Bearer {config.embed.api_key}"

    for start in range(0, len(texts), _BATCH):
        chunk = [t[:_MAX_CHARS] or " " for t in texts[start : start + _BATCH]]
        resp = httpx.post(
            f"{config.embed.base_url.rstrip('/')}/embeddings",
            headers=headers,
            json={"model": config.embed.model, "input": chunk},
            timeout=120.0,
        )
        resp.raise_for_status()
        data = resp.json().get("data", [])
        vectors.extend([item["embedding"] for item in data])
    return vectors


def pack(vector: list[float]) -> bytes:
    return struct.pack(f"{len(vector)}f", *vector)


def unpack(blob: bytes) -> list[float]:
    return list(struct.unpack(f"{len(blob) // 4}f", blob))


def cosine(a: list[float], b: list[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b, strict=True))  # lengths are checked above
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    return dot / (na * nb) if na and nb else 0.0


def index_note(note_id: str, text: str, config: Config) -> bool:
    """Embed one note. Best-effort: a missing embedder must never fail an intake."""
    if not enabled(config):
        return False
    try:
        vector = embed_texts([text], config)[0]
    except Exception:  # noqa: BLE001
        return False
    from .library import store_vector

    store_vector(note_id, pack(vector), config.staging_dir)
    return True


@dataclass
class Scored:
    id: str
    score: float


def semantic_hits(query: str, config: Config, limit: int = 10) -> list[Scored]:
    """Brute-force cosine over the library. A personal library is small; this is fine."""
    if not enabled(config):
        return []
    from .library import all_vectors

    rows = all_vectors(config.staging_dir)
    if not rows:
        return []
    try:
        target = embed_texts([query], config)[0]
    except Exception:  # noqa: BLE001
        return []

    scored = [Scored(note_id, cosine(target, unpack(blob))) for note_id, blob in rows]
    scored.sort(key=lambda s: s.score, reverse=True)
    return [s for s in scored if s.score > 0.2][:limit]


def reindex(config: Config) -> int:
    """Embed everything that has no vector yet."""
    if not enabled(config):
        return 0
    from .library import notes_without_vectors, store_vector

    pending = notes_without_vectors(config.staging_dir)
    done = 0
    for start in range(0, len(pending), _BATCH):
        batch = pending[start : start + _BATCH]
        try:
            vectors = embed_texts([f"{t}\n{x}" for _, t, x in batch], config)
        except Exception:  # noqa: BLE001
            break
        # strict=False on purpose: a provider that returns fewer vectors than we asked
        # for should cost us those notes, not raise in the middle of a reindex.
        for (note_id, _, _), vector in zip(batch, vectors, strict=False):
            store_vector(note_id, pack(vector), config.staging_dir)
            done += 1
    return done
