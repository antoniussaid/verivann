from pathlib import Path

import httpx
import pytest

from verivann.adapters import search as search_adapter
from verivann.alloy import alloy
from verivann.config import Config, LLMConfig
from verivann.counter import counter
from verivann.interview import UNSURE_BELOW, answer, uncertain
from verivann.library import index_claims, verdict_of
from verivann.pipeline import run
from verivann.schema import Extracted


class _Resp:
    def __init__(self, content):
        self._c = content

    def raise_for_status(self):
        return None

    def json(self):
        return {"choices": [{"message": {"content": self._c}}]}


@pytest.fixture(autouse=True)
def _no_search(monkeypatch):
    monkeypatch.delenv("VERIVANN_SEARCH_URL", raising=False)
    monkeypatch.delenv("VERIVANN_SEARCH_KEY", raising=False)


# ---------- counter-search ----------

def test_without_a_backend_it_returns_honest_emptiness(tmp_path):
    config = Config(staging_dir=tmp_path)
    note = run("text", ref="text", text="a confident claim about agents", config=config)

    result = counter(note.event.id, config)
    assert result.fetched == []
    assert "not the same as the claim being right" in result.verdict()


def test_it_never_asks_the_accused_for_an_alibi(monkeypatch, tmp_path):
    monkeypatch.setenv("VERIVANN_SEARCH_URL", "http://localhost:8888")
    config = Config(staging_dir=tmp_path)

    monkeypatch.setattr(
        "verivann.pipeline.extract_webpage",
        lambda url: Extracted(title=f"page {url}", text="a rebuttal about automation", meta={}),
    )
    note = run("url", ref="https://guru.example.com/post", config=config)
    index_claims(note.event.id, ["Local agents always beat the cloud."], tmp_path)

    monkeypatch.setattr(
        search_adapter, "search",
        lambda q, limit=5: [
            search_adapter.Result("Same site", "https://guru.example.com/other", ""),  # skipped
            search_adapter.Result("A rebuttal", "https://critic.example.org/x", ""),
        ],
    )
    result = counter(note.event.id, config)

    urls = [f["url"] for f in result.fetched]
    assert urls == ["https://critic.example.org/x"]  # the accused was not consulted


def test_a_fetched_source_that_contradicts_announces_itself(monkeypatch, tmp_path):
    monkeypatch.setenv("VERIVANN_SEARCH_URL", "http://localhost:8888")
    config = Config(staging_dir=tmp_path, llm=LLMConfig(provider="openai", model="m", base_url="http://x/v1"))

    monkeypatch.setattr(
        "verivann.pipeline.extract_webpage",
        lambda url: Extracted(title="Original piece", text="whisper needs a gpu", meta={}),
    )
    note = run("url", ref="https://guru.example.com/post", config=config)
    index_claims(note.event.id, ["Whisper needs a GPU."], tmp_path)

    monkeypatch.setattr(
        search_adapter, "search",
        lambda q, limit=5: [search_adapter.Result("CPU is enough", "https://critic.example.org/x", "")],
    )
    monkeypatch.setattr(
        "verivann.pipeline.extract_webpage",
        lambda url: Extracted(title="CPU is enough", text="whisper runs fine on cpu", meta={}),
    )

    calls = {"n": 0}

    def responses(*a, **k):
        calls["n"] += 1
        body = k.get("json", {}).get("messages", [{}])[0].get("content", "")
        if "search queries" in body.lower() or "queries" in body.lower():
            return _Resp('{"queries": ["whisper cpu benchmark"]}')
        if "contradict" in body.lower() or "compare factual claims" in body.lower():
            return _Resp('{"conflict": true, "with": "Whisper needs a GPU.", "why": "CPU suffices."}')
        return _Resp('{"domain":"research","action":"note","claims_to_verify":["Whisper runs fine on CPU."]}')

    monkeypatch.setattr(httpx, "post", responses)
    result = counter(note.event.id, config)

    assert result.fetched
    assert result.contradicting
    assert "contradict this note" in result.verdict()


# ---------- the interview ----------

def test_only_genuinely_uncertain_notes_are_asked_about(tmp_path):
    config = Config(staging_dir=tmp_path)
    run("text", ref="text", text="x y", config=config)  # too short -> inbox, confidence 0.1
    run("text", ref="text", text="a local-first automation pipeline for agents", config=config)  # confident

    pending = uncertain(tmp_path, config.domains)
    assert len(pending) == 1
    assert "a guess" in pending[0].reason
    assert "drop" in pending[0].options


def test_an_answer_routes_the_note_and_teaches_the_router(tmp_path):
    config = Config(staging_dir=tmp_path)
    note = run("text", ref="text", text="x y", config=config)

    line = answer(note.event.id, "finance", tmp_path)
    assert "routed to" in line
    assert verdict_of(note.event.id, tmp_path) == "kept"

    from verivann.library import note_row

    assert note_row(note.event.id, tmp_path)["domain"] == "finance"
    assert note_row(note.event.id, tmp_path)["confidence"] == 1.0  # you are not a guess


def test_answering_drop_is_a_full_verdict(tmp_path):
    config = Config(staging_dir=tmp_path)
    note = run("text", ref="text", text="x y", config=config)
    answer(note.event.id, "drop", tmp_path)
    assert verdict_of(note.event.id, tmp_path) == "dropped"


def test_a_judged_note_is_never_interrogated_again(tmp_path):
    config = Config(staging_dir=tmp_path)
    note = run("text", ref="text", text="x y", config=config)
    answer(note.event.id, "drop", tmp_path)
    assert uncertain(tmp_path, config.domains) == []
    assert UNSURE_BELOW == 0.4


# ---------- the alloy ----------

def test_an_alloy_needs_at_least_two_sources(tmp_path):
    config = Config(staging_dir=tmp_path)
    note = run("text", ref="text", text="one source about agents", config=config)
    assert alloy([note.event.id], config=config) is None


def test_without_a_model_it_assembles_and_says_so(tmp_path):
    config = Config(staging_dir=tmp_path)
    a = run("text", ref="text", text="broker A charges 0.1% for ETFs", config=config)
    b = run("text", ref="text", text="broker B charges 1% for ETFs", config=config)

    result = alloy([a.event.id, b.event.id], "ETF costs", config)
    assert result.engine == "assembly"
    text = Path(result.note_path).read_text(encoding="utf-8")
    assert "not synthesized" in text
    assert "broker A charges" in text and "broker B charges" in text


def test_with_a_model_it_synthesizes_and_cites(monkeypatch, tmp_path):
    monkeypatch.setattr(httpx, "post", lambda *a, **k: _Resp("Broker A is cheaper [1]; [2] disagrees on custody."))
    config = Config(staging_dir=tmp_path, llm=LLMConfig(provider="openai", model="m", base_url="http://x/v1"))
    a = run("text", ref="text", text="broker A charges 0.1%", config=config)
    b = run("text", ref="text", text="broker B charges 1%", config=config)

    result = alloy([a.event.id, b.event.id], "ETF costs", config)
    text = Path(result.note_path).read_text(encoding="utf-8")

    assert result.engine == "llm:m"
    assert "Broker A is cheaper [1]" in text
    assert "**Melted from:**" in text
    assert verdict_of(result.id, tmp_path) == "kept"  # you made it; you meant it
