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
