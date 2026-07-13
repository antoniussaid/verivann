from smelt.config import Config
from smelt.library import mark_source, record_feedback, source_standing
from smelt.pipeline import run
from smelt.schema import Extracted
from smelt.sources import identify, material_minutes, note_yield, standings


def test_a_channel_is_the_source_not_the_platform():
    video = Extracted(title="t", text="x", meta={"uploader": "3Blue1Brown", "extractor": "Youtube"})
    key, label = identify("youtube", "https://youtube.com/watch?v=abc", video)
    assert key == "youtube:@3blue1brown"
    assert "3Blue1Brown" in label


def test_a_website_is_identified_by_host():
    key, _ = identify("url", "https://orf.at/stories/1", Extracted(title="t", text="x"))
    assert key == "web:orf.at"


def test_material_is_measured_in_minutes():
    video = Extracted(title="t", text="", meta={"duration": 1620})  # 27 min
    assert material_minutes(video) == 27.0
    article = Extracted(title="t", text=" ".join(["word"] * 440))  # ~2 min of reading
    assert 1.9 <= material_minutes(article) <= 2.1


def test_yield_is_ideas_per_ten_minutes():
    assert note_yield(3, 30) == 1.0
    assert note_yield(0, 40) == 0.0


def test_the_record_accumulates_across_notes(tmp_path):
    config = Config(staging_dir=tmp_path)
    first = run("text", ref="text", text="a local-first automation pipeline for agents", config=config)
    run("text", ref="text", text="another note about self-hosted agent architecture", config=config)
    record_feedback(first.event.id, "kept", tmp_path)

    standing = source_standing("you:pasted", tmp_path)
    assert standing["notes"] == 2
    assert standing["kept"] == 1


def test_hits_and_misses_shape_the_verdict(tmp_path):
    config = Config(staging_dir=tmp_path)
    run("text", ref="text", text="a claim-heavy piece about automation and agents", config=config)
    mark_source("you:pasted", "misses", tmp_path)
    mark_source("you:pasted", "misses", tmp_path)

    standing = standings(tmp_path)[0]
    assert standing.misses == 2
    assert "wrong 2" in standing.verdict()


def test_yield_is_unknown_when_nothing_ever_read_it(tmp_path):
    """A heuristic run extracts no ideas. That is OUR failure, not the source's."""
    config = Config(staging_dir=tmp_path)  # no LLM
    for i in range(3):
        run("text", ref="text", text=f"filler {i} " + "waffle " * 900, config=config)

    standing = standings(tmp_path)[0]
    assert standing.minutes > 10
    assert standing.analyzed == 0
    assert standing.yield_per_10min is None
    assert "yield unknown" in standing.verdict()


def test_a_low_yield_source_is_called_out_once_it_was_actually_read(tmp_path, monkeypatch):
    import httpx

    from smelt.config import LLMConfig

    class _Resp:
        def raise_for_status(self):
            return None

        def json(self):
            return {"choices": [{"message": {"content": '{"domain":"media","action":"note","useful_ideas":[]}'}}]}

    monkeypatch.setattr(httpx, "post", lambda *a, **k: _Resp())
    config = Config(staging_dir=tmp_path, llm=LLMConfig(provider="openai", model="m", base_url="http://x/v1"))
    for i in range(3):
        run("text", ref="text", text=f"filler {i} " + "waffle " * 900, config=config)

    standing = standings(tmp_path)[0]
    assert standing.analyzed == 3
    assert standing.yield_per_10min == 0.0
    assert "low yield" in standing.verdict()
