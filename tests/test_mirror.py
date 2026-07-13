import httpx

from smelt.bias import bias
from smelt.config import Config, LLMConfig
from smelt.library import index_event, mark_source, record_feedback
from smelt.pipeline import run
from smelt.schema import Decision, Extracted, IntakeEvent, Provenance, Routing, Source
from smelt.stats import mirror, slag


class _Resp:
    def __init__(self, content):
        self._c = content

    def raise_for_status(self):
        return None

    def json(self):
        return {"choices": [{"message": {"content": self._c}}]}


def _indexed(note_id, title, text, staging, source_key="youtube:@guru", minutes=30.0):
    event = IntakeEvent(
        id=note_id, created_at="2026-07-10T00:00:00Z",
        source=Source(kind="youtube", ref=f"https://youtube.com/watch?v={note_id}"),
        extracted=Extracted(title=title, text=text, meta={"duration": minutes * 60, "uploader": "Guru",
                                                          "extractor": "Youtube"}),
        routing=Routing(domain="finance", confidence=0.5, reason="r"),
        decision=Decision(action="note", target="t.md"),
        provenance=Provenance(tool="smelt", version="0", public_demo=True),
    )
    index_event(event, "n.md", "e.json", staging)
    return event


def test_an_empty_period_says_so(tmp_path):
    assert mirror(tmp_path).verdict() == "Nothing digested in this period."


def test_the_mirror_counts_hours_in_and_notes_kept(tmp_path):
    config = Config(staging_dir=tmp_path)
    a = run("text", ref="text", text="local-first agent architecture " * 200, config=config)
    run("text", ref="text", text="another automation piece " * 200, config=config)
    record_feedback(a.event.id, "kept", tmp_path)

    m = mirror(tmp_path)
    assert m.notes == 2
    assert m.kept == 1 and m.unjudged == 1
    assert m.minutes > 0
    assert "kept" in m.verdict()


def test_an_unjudged_library_is_called_a_pile(tmp_path):
    config = Config(staging_dir=tmp_path)
    run("text", ref="text", text="something about automation and agents", config=config)
    assert "the library is a pile" in mirror(tmp_path).verdict()


def test_keeping_nothing_is_stated_plainly(tmp_path):
    config = Config(staging_dir=tmp_path)
    result = run("text", ref="text", text="an automation pipeline for local agents", config=config)
    record_feedback(result.event.id, "dropped", tmp_path)
    assert "You kept nothing." in mirror(tmp_path).verdict()


def test_time_sinks_name_the_channel_that_ate_the_hours(tmp_path):
    _indexed("n1", "Long video", "waffle", tmp_path, minutes=60)
    _indexed("n2", "Longer video", "waffle", tmp_path, minutes=90)

    m = mirror(tmp_path)
    source, minutes, kept = m.time_sinks[0]
    assert "Guru" in source
    assert minutes == 150.0
    assert kept == 0


def test_the_anti_library_holds_what_you_threw_away(tmp_path):
    config = Config(staging_dir=tmp_path)
    result = run("text", ref="text", text="crypto memecoin pump hype guaranteed", config=config)
    record_feedback(result.event.id, "dropped", tmp_path)

    rows = slag(tmp_path)
    assert len(rows) == 1
    assert "crypto" in rows[0].title.lower()


def test_a_library_that_only_agrees_with_itself_is_named(tmp_path):
    for i in range(3):
        event = _indexed(f"n{i}", f"Local-first is the future {i}", "local-first agents win", tmp_path)
        record_feedback(event.id, "kept", tmp_path)

    split = bias("local-first", Config(staging_dir=tmp_path))  # no LLM -> inventory
    assert split.total == 3
    assert not split.dissent
    assert "that is a sample you selected" in split.verdict()


def test_dissenters_with_the_better_record_are_flagged(monkeypatch, tmp_path):
    for i in range(2):
        event = _indexed(f"s{i}", f"Cloud is fine {i}", "cloud automation is fine", tmp_path,
                         source_key="youtube:@guru")
        record_feedback(event.id, "kept", tmp_path)
    dissenter = _indexed("d1", "Cloud will fail you", "cloud automation is fine but lock-in is real",
                         tmp_path)
    record_feedback(dissenter.id, "kept", tmp_path)

    # The dissenting note comes from a different channel with a good record.
    from smelt.library import _connect

    con = _connect(tmp_path)
    con.execute("UPDATE notes SET source_key = 'youtube:@skeptic' WHERE id = 'd1'")
    con.execute("INSERT OR IGNORE INTO sources (key, label, first_seen) VALUES ('youtube:@skeptic','Skeptic','x')")
    con.commit()
    con.close()
    mark_source("youtube:@skeptic", "hits", tmp_path)
    mark_source("youtube:@guru", "misses", tmp_path)

    monkeypatch.setattr(
        httpx, "post",
        lambda *a, **k: _Resp(
            '{"thesis":"Cloud automation is fine","blind_spot":"nobody discusses lock-in",'
            '"verdicts":[{"n":1,"stance":"support"},{"n":2,"stance":"support"},'
            '{"n":3,"stance":"dissent"}]}'
        ),
    )
    config = Config(staging_dir=tmp_path, llm=LLMConfig(provider="openai", model="m", base_url="http://x/v1"))
    split = bias("cloud automation", config)

    assert len(split.support) == 2 and len(split.dissent) == 1
    assert split.blind_spot
    assert "the side that has been right" in split.verdict()
