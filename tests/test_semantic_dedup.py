"""PC-4 - the one guard that protects the credibility metric.

Near-identical content re-posted under different URLs would otherwise inflate a
source's apparent corroboration. Same-source reposts merge; cross-source echoes are
surfaced, never collapsed (two sources agreeing IS corroboration, not a duplicate).
"""

from verivann.config import Config, EmbedConfig
from verivann.embed import pack, semantic_dupes
from verivann.library import _connect, count, merge_notes, store_vector, vectors_with_meta
from verivann.pipeline import run


def _cfg(staging):
    # An embed model + base_url is all `enabled()` checks; we never actually call it,
    # we store the vectors ourselves so the cosine is deterministic.
    return Config(staging_dir=staging, embed=EmbedConfig(model="m", base_url="http://x"))


def _stage(staging, text):
    return run("text", ref="text", text=text, config=Config(staging_dir=staging)).event.id


def _set(staging, note_id, canon, source_key, vector):
    con = _connect(staging)
    try:
        con.execute("UPDATE notes SET canon = ?, source_key = ? WHERE id = ?", (canon, source_key, note_id))
        con.commit()
    finally:
        con.close()
    store_vector(note_id, pack(vector), staging)


def test_vectors_with_meta_returns_embedded_notes(tmp_path):
    staging = tmp_path / "s"
    a = _stage(staging, "A piece about local-first software.")
    _set(staging, a, "urlA", "src:one", [1.0, 0.0, 0.0])
    rows = vectors_with_meta(staging)
    assert len(rows) == 1 and rows[0]["id"] == a and rows[0]["source_key"] == "src:one"


def test_a_same_source_repost_is_flagged_mergeable(tmp_path):
    staging = tmp_path / "s"
    a = _stage(staging, "The original post about winnowing signal from noise.")
    b = _stage(staging, "The very same post, re-hosted on the creator's other site.")
    _set(staging, a, "urlA", "src:creator", [1.0, 0.0, 0.0])
    _set(staging, b, "urlB", "src:creator", [0.99, 0.02, 0.0])  # near-identical direction

    dupes = semantic_dupes(_cfg(staging))

    assert len(dupes) == 1
    assert dupes[0].same_source is True
    assert dupes[0].score >= 0.94


def test_a_cross_source_echo_is_flagged_but_not_mergeable(tmp_path):
    staging = tmp_path / "s"
    a = _stage(staging, "A wire story.")
    b = _stage(staging, "The same wire story, reprinted by another outlet.")
    _set(staging, a, "urlA", "src:outletA", [1.0, 0.0, 0.0])
    _set(staging, b, "urlB", "src:outletB", [0.995, 0.01, 0.0])

    dupes = semantic_dupes(_cfg(staging))

    assert len(dupes) == 1
    assert dupes[0].same_source is False  # different sources -> corroboration, not a dupe


def test_distinct_notes_are_not_paired(tmp_path):
    staging = tmp_path / "s"
    a = _stage(staging, "About databases.")
    b = _stage(staging, "About gardening.")
    _set(staging, a, "urlA", "src:one", [1.0, 0.0, 0.0])
    _set(staging, b, "urlB", "src:two", [0.0, 1.0, 0.0])  # orthogonal -> cosine 0

    assert semantic_dupes(_cfg(staging)) == []


def test_pairs_already_unified_by_canon_are_skipped(tmp_path):
    staging = tmp_path / "s"
    a = _stage(staging, "One url of a thing.")
    b = _stage(staging, "Another url of the same thing.")
    _set(staging, a, "same-canon", "src:one", [1.0, 0.0, 0.0])
    _set(staging, b, "same-canon", "src:one", [1.0, 0.0, 0.0])  # identical AND same canon

    assert semantic_dupes(_cfg(staging)) == []  # URL dedup owns this pair


def test_semantic_dedup_is_off_without_an_embedder(tmp_path):
    staging = tmp_path / "s"
    a = _stage(staging, "x")
    _set(staging, a, "urlA", "src:one", [1.0, 0.0, 0.0])
    # A Config with no embed model -> enabled() is False -> no work, no crash.
    assert semantic_dupes(Config(staging_dir=staging)) == []


def test_merge_notes_collapses_a_repost_and_reclaims_its_vector(tmp_path):
    staging = tmp_path / "s"
    keeper = _stage(staging, "keeper")
    dupe = _stage(staging, "dupe")
    _set(staging, keeper, "urlA", "src:one", [1.0, 0.0, 0.0])
    _set(staging, dupe, "urlB", "src:one", [1.0, 0.0, 0.0])
    assert count(staging) == 2

    merge_notes(keeper, dupe, staging)

    assert count(staging) == 1
    ids = {r["id"] for r in vectors_with_meta(staging)}
    assert dupe not in ids and keeper in ids  # dupe's orphaned vector is gone too
