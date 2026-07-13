from verivann.library import count, index_event, search
from verivann.schema import Decision, Extracted, IntakeEvent, Provenance, Routing, Source


def _ev(id_: str, title: str, text: str, domain: str = "research") -> IntakeEvent:
    return IntakeEvent(
        id=id_,
        created_at="2026-07-11T00:00:00",
        source=Source(kind="text", ref="text"),
        extracted=Extracted(title=title, text=text),
        routing=Routing(domain=domain, confidence=0.5, reason="r"),
        decision=Decision(action="note", target="p"),
        provenance=Provenance(version="0.1.0"),
    )


def test_index_and_search(tmp_path):
    index_event(_ev("a", "AI memory", "local-first ai memory and automation"), "n.md", "e.json", tmp_path)
    index_event(_ev("b", "Broker fees", "compare etf costs and tax", "finance"), "n2.md", "e2.json", tmp_path)
    assert count(tmp_path) == 2
    assert any(h.id == "a" for h in search("automation", tmp_path))
    assert any(h.id == "b" for h in search("etf", tmp_path))


def test_reindex_is_idempotent(tmp_path):
    index_event(_ev("a", "First", "hello world one"), "n.md", "e.json", tmp_path)
    index_event(_ev("a", "First v2", "hello world two"), "n.md", "e.json", tmp_path)
    assert count(tmp_path) == 1  # INSERT OR REPLACE keeps one row per id


# --- Storage hygiene: concurrency-friendly PRAGMAs + indexes on the hot columns. ---

def test_connection_uses_wal_and_a_busy_timeout(tmp_path):
    from verivann.library import _connect

    con = _connect(tmp_path)
    try:
        assert con.execute("PRAGMA journal_mode").fetchone()[0].lower() == "wal"
        assert con.execute("PRAGMA busy_timeout").fetchone()[0] >= 5000
    finally:
        con.close()


def test_the_hot_columns_are_indexed(tmp_path):
    from verivann.library import _INDEXES, _connect

    con = _connect(tmp_path)
    try:
        names = {r["name"] for r in con.execute("PRAGMA index_list(notes)")}
        # notes' own reporting/dedupe columns are covered...
        assert {"idx_notes_created_at", "idx_notes_canon", "idx_notes_source_key"} <= names
        # ...and every declared index exists somewhere in the schema.
        declared = {stmt.split(" idx_")[1].split(" ")[0] for stmt in _INDEXES}
        present = {r[1] for r in con.execute(
            "SELECT type, name FROM sqlite_master WHERE type='index'"
        )}
        assert {f"idx_{d}" for d in declared} <= present
    finally:
        con.close()


def test_a_query_on_created_at_uses_its_index(tmp_path):
    from verivann.library import _connect

    index_event(_ev("a", "t", "some body text"), "n.md", "e.json", tmp_path)
    con = _connect(tmp_path)
    try:
        plan = con.execute(
            "EXPLAIN QUERY PLAN SELECT id FROM notes ORDER BY created_at DESC LIMIT 5"
        ).fetchall()
        detail = " ".join(str(r[-1]) for r in plan)
        assert "idx_notes_created_at" in detail  # the ORDER BY rides the index, no scan+sort
    finally:
        con.close()
