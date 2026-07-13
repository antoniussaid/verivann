import httpx

from smelt.config import Config, LLMConfig
from smelt.library import source_standing
from smelt.pipeline import run
from smelt.predictions import listing, record, resolve
from smelt.render import render_markdown


class _Resp:
    def __init__(self, content):
        self._c = content

    def raise_for_status(self):
        return None

    def json(self):
        return {"choices": [{"message": {"content": self._c}}]}


def _llm(monkeypatch, content):
    monkeypatch.setattr(httpx, "post", lambda *a, **k: _Resp(content))
    return Config(staging_dir=None, llm=LLMConfig(provider="openai", model="m", base_url="http://x/v1"))


def test_the_llm_prompt_asks_for_dated_predictions(monkeypatch):
    seen = {}

    def fake_post(url, headers=None, json=None, timeout=None):
        seen["system"] = json["messages"][0]["content"]
        return _Resp('{"domain":"finance","action":"note"}')

    monkeypatch.setattr(httpx, "post", fake_post)
    from smelt.analysis.analyzer import analyze
    from smelt.schema import Extracted

    cfg = Config(llm=LLMConfig(provider="openai", model="m", base_url="http://x/v1"))
    analyze(Extracted(title="t", text="x"), cfg)
    assert "Today is" in seen["system"]
    assert "predictions" in seen["system"]


def test_only_judgeable_predictions_survive_parsing(monkeypatch):
    from smelt.analysis.analyzer import analyze
    from smelt.schema import Extracted

    cfg = _llm(
        monkeypatch,
        '{"domain":"finance","action":"note","predictions":['
        '{"text":"Bitcoin reaches 200k","due":"2026-12-31"},'
        '{"text":"things will change","due":"soon"},'          # no date -> dropped
        '{"text":"","due":"2026-01-01"}]}',                     # no claim -> dropped
    )
    cfg.staging_dir = Config().staging_dir
    result = analyze(Extracted(title="t", text="x"), cfg)
    assert result.predictions == [{"text": "Bitcoin reaches 200k", "due": "2026-12-31"}]


def test_a_prediction_lands_on_the_record_and_in_the_note(monkeypatch, tmp_path):
    cfg = _llm(
        monkeypatch,
        '{"domain":"finance","action":"note","summary":"s",'
        '"predictions":[{"text":"The ECB cuts rates","due":"2026-09-01"}]}',
    )
    cfg.staging_dir = tmp_path
    result = run("text", ref="text", text="a confident macro take", config=cfg)

    assert "## On the record (predictions)" in render_markdown(result.event)
    items = listing(tmp_path)
    assert len(items) == 1
    assert items[0].text == "The ECB cuts rates"
    assert items[0].status == "open"


def test_a_missed_prediction_is_written_onto_the_source(tmp_path):
    record("note-1", "youtube:@guru", [{"text": "Bitcoin at 200k", "due": "2026-01-01"}], tmp_path)
    item = listing(tmp_path)[0]
    assert item.is_due  # 2026-01-01 is in the past for this ledger

    resolved = resolve(item.id, "miss", tmp_path)
    assert resolved.status == "miss"

    standing = source_standing("youtube:@guru", tmp_path)
    assert standing["misses"] == 1 and standing["hits"] == 0


def test_void_leaves_the_source_untouched(tmp_path):
    record("note-1", "youtube:@guru", [{"text": "Something vague", "due": "2026-01-01"}], tmp_path)
    item = listing(tmp_path)[0]
    resolve(item.id, "void", tmp_path)

    standing = source_standing("youtube:@guru", tmp_path)
    assert standing["misses"] == 0 and standing["hits"] == 0


def test_reingesting_never_overwrites_a_judged_prediction(tmp_path):
    record("note-1", "youtube:@guru", [{"text": "X happens", "due": "2026-01-01"}], tmp_path)
    resolve(listing(tmp_path)[0].id, "hit", tmp_path)

    record("note-1", "youtube:@guru", [{"text": "X happens", "due": "2026-01-01"}], tmp_path)
    items = listing(tmp_path)
    assert len(items) == 1
    assert items[0].status == "hit"  # the verdict survives a re-read
