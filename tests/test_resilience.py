import httpx
import pytest

from verivann.analysis.llm import AllModelsFailed, call
from verivann.config import Config, LLMConfig
from verivann.library import verdict_of
from verivann.pipeline import run
from verivann.reanalyze import pending, reanalyze
from verivann.redact import redact
from verivann.render import render_markdown


class _Resp:
    def __init__(self, content="ok"):
        self._c = content

    def raise_for_status(self):
        return None

    def json(self):
        return {"choices": [{"message": {"content": self._c}}]}


def _rate_limited(retry_after: str = "0"):
    request = httpx.Request("POST", "https://x/v1/chat/completions")
    response = httpx.Response(429, headers={"retry-after": retry_after}, request=request)
    return httpx.HTTPStatusError("429", request=request, response=response)


@pytest.fixture(autouse=True)
def _fast(monkeypatch):
    monkeypatch.setattr("verivann.analysis.llm.time.sleep", lambda s: None)
    monkeypatch.delenv("VERIVANN_REDACT", raising=False)
    monkeypatch.delenv("VERIVANN_PRIVACY", raising=False)


# ---------- retry, backoff, fallback ----------

def test_a_rate_limit_is_retried_not_fatal(monkeypatch):
    calls = {"n": 0}

    def flaky(*a, **k):
        calls["n"] += 1
        if calls["n"] < 3:
            raise _rate_limited()
        return _Resp("answer")

    monkeypatch.setattr(httpx, "post", flaky)
    reply, model = call(LLMConfig(provider="groq", model="a", base_url="http://x/v1"), "s", "u")

    assert reply == "answer"
    assert calls["n"] == 3  # two 429s, then through


def test_a_dead_model_falls_through_to_the_next_one(monkeypatch):
    seen = []

    def by_model(url, headers=None, json=None, timeout=None):
        seen.append(json["model"])
        if json["model"] == "big":
            raise _rate_limited()
        return _Resp("from the small one")

    monkeypatch.setattr(httpx, "post", by_model)
    llm = LLMConfig(provider="groq", model="big", models=["small"], base_url="http://x/v1")
    reply, model = call(llm, "s", "u")

    assert reply == "from the small one"
    assert model == "small"  # …and the note will record who ACTUALLY answered
    assert seen.count("big") == 3  # exhausted its retries first


def test_a_whole_other_provider_catches_the_fall(monkeypatch):
    def by_host(url, headers=None, json=None, timeout=None):
        if "groq" in url:
            raise _rate_limited()
        return _Resp("from the fallback")

    monkeypatch.setattr(httpx, "post", by_host)
    llm = LLMConfig(
        provider="groq", model="a", base_url="https://groq/v1",
        fallback=LLMConfig(provider="gemini", model="b", base_url="https://gemini/v1"),
    )
    reply, model = call(llm, "s", "u")
    assert reply == "from the fallback"
    assert model == "b"


def test_an_auth_error_is_not_retried(monkeypatch):
    calls = {"n": 0}

    def unauthorized(*a, **k):
        calls["n"] += 1
        request = httpx.Request("POST", "https://x/v1")
        raise httpx.HTTPStatusError(
            "401", request=request, response=httpx.Response(401, request=request)
        )

    monkeypatch.setattr(httpx, "post", unauthorized)
    with pytest.raises(AllModelsFailed):
        call(LLMConfig(provider="groq", model="a", base_url="http://x/v1"), "s", "u")
    assert calls["n"] == 1  # a wrong key will not become right by asking again


def test_when_everything_refuses_the_intake_still_produces_a_note(monkeypatch, tmp_path):
    monkeypatch.setattr(httpx, "post", lambda *a, **k: (_ for _ in ()).throw(_rate_limited()))
    config = Config(
        staging_dir=tmp_path,
        llm=LLMConfig(provider="groq", model="a", base_url="http://x/v1"),
    )
    result = run("text", ref="text", text="a local-first automation pipeline", config=config)

    assert result.event.routing.domain == "research"  # the heuristic carried it
    assert "LLM unavailable" in result.event.routing.reason


# ---------- redaction ----------

def test_identity_is_replaced_but_meaning_survives():
    text = "Herr Anton Said, IBAN AT61 1904 3002 3457 3201, zahlte €1.234,56 am 03.04.1990."
    result = redact(text)

    assert "AT61" not in result.text
    assert "Anton Said" not in result.text
    assert "[IBAN_1]" in result.text and "[PERSON_1]" in result.text
    assert "zahlte" in result.text  # the sentence still says what happened
    assert result.restore(result.text) == text  # …and it comes back, locally


def test_the_same_person_gets_the_same_placeholder():
    result = redact("Herr Anton Said schrieb an Herr Anton Said.")
    assert result.text.count("[PERSON_1]") == 2
    assert result.counts["PERSON"] == 1


def test_redaction_is_honest_about_being_incomplete():
    result = redact("IBAN AT61 1904 3002 3457 3201")
    assert "not a guarantee" in result.summary()


def test_a_sensitive_file_is_uploaded_only_after_redaction(monkeypatch, tmp_path):
    monkeypatch.setenv("VERIVANN_REDACT", "1")
    sent = {}

    def capture(url, headers=None, json=None, timeout=None):
        sent["body"] = json["messages"][1]["content"]
        return _Resp('{"domain":"finance","action":"note","summary":"[PERSON_1] paid [AMOUNT_1]."}')

    monkeypatch.setattr(httpx, "post", capture)
    monkeypatch.setattr("verivann.adapters.vision.ocr_available", lambda: True)
    monkeypatch.setattr(
        "verivann.adapters.vision.ocr_image",
        lambda p: "Kontoauszug: Herr Anton Said, IBAN AT61 1904 3002 3457 3201, €1.234,56",
    )
    shot = tmp_path / "shot.png"
    shot.write_bytes(b"\x89PNG")
    config = Config(
        staging_dir=tmp_path,
        llm=LLMConfig(provider="openai", model="m", base_url="https://api.openai.com/v1"),
    )

    result = run("file", ref=str(shot), config=config)
    note = render_markdown(result.event)

    # What the model saw: no name, no IBAN.
    assert "Anton Said" not in sent["body"]
    assert "AT61" not in sent["body"]
    assert "[IBAN_1]" in sent["body"]
    # What YOU see: the truth, restored locally.
    assert "Anton Said paid" in note or "Anton Said" in note
    assert "after local redaction" in note
    assert result.event.extracted.meta["privacy_mode"] == "redacted"


def test_without_redaction_a_sensitive_file_is_simply_not_uploaded(monkeypatch, tmp_path):
    def explode(*a, **k):
        raise AssertionError("sensitive material reached a hosted model")

    monkeypatch.setattr(httpx, "post", explode)
    monkeypatch.setattr("verivann.adapters.vision.ocr_available", lambda: True)
    monkeypatch.setattr("verivann.adapters.vision.ocr_image", lambda p: "IBAN AT61 1904 3002 3457 3201")
    shot = tmp_path / "shot.png"
    shot.write_bytes(b"\x89PNG")

    config = Config(
        staging_dir=tmp_path,
        llm=LLMConfig(provider="openai", model="m", base_url="https://api.openai.com/v1"),
    )
    result = run("file", ref=str(shot), config=config)
    assert result.event.extracted.meta["privacy_mode"] == "withheld"
    assert "never properly read" in render_markdown(result.event)


# ---------- reanalyze ----------

def test_notes_no_model_ever_read_are_found(tmp_path):
    config = Config(staging_dir=tmp_path)
    run("text", ref="text", text="a local-first automation pipeline for agents", config=config)

    todo = pending(config)
    assert len(todo) == 1
    assert todo[0]["engine"] == "heuristic"
    assert reanalyze(config) == []  # no model -> re-reading would repeat the heuristic


def test_reanalysis_keeps_the_note_and_its_verdicts(monkeypatch, tmp_path):
    config = Config(staging_dir=tmp_path)
    first = run("text", ref="text", text="a local-first automation pipeline for agents", config=config)
    from verivann.library import record_feedback

    record_feedback(first.event.id, "kept", tmp_path)

    monkeypatch.setattr(
        httpx, "post",
        lambda *a, **k: _Resp('{"domain":"research","action":"task","summary":"read properly",'
                              '"useful_ideas":["orchestrate, do not rebuild"]}'),
    )
    config.llm = LLMConfig(provider="groq", model="big", base_url="http://x/v1")
    done = reanalyze(config)

    assert len(done) == 1
    assert done[0].note_id == first.event.id       # the SAME note
    assert done[0].was == "heuristic"
    assert done[0].now == "llm:big"
    assert verdict_of(first.event.id, tmp_path) == "kept"  # your verdict survived
    assert pending(config) == []                    # nothing left unread


def test_reanalysis_never_touches_the_source(monkeypatch, tmp_path):
    config = Config(staging_dir=tmp_path)
    from verivann.schema import Extracted

    monkeypatch.setattr(
        "verivann.pipeline.extract_webpage",
        lambda url: Extracted(title="Fetched once", text="an automation pipeline", meta={}),
    )
    run("url", ref="https://example.com/a", config=config)

    def never(url):
        raise AssertionError("reanalysis went back to the network")

    monkeypatch.setattr("verivann.pipeline.extract_webpage", never)
    monkeypatch.setattr(httpx, "post", lambda *a, **k: _Resp('{"domain":"research","action":"note"}'))
    config.llm = LLMConfig(provider="groq", model="m", base_url="http://x/v1")

    done = reanalyze(config)
    assert len(done) == 1  # judged from what we stored, not from the web
