import httpx

from verivann.config import Config, LLMConfig
from verivann.pipeline import run
from verivann.questions import add, answer, close, listing, match
from verivann.render import render_markdown
from verivann.schema import Extracted


class _Resp:
    def __init__(self, content):
        self._c = content

    def raise_for_status(self):
        return None

    def json(self):
        return {"choices": [{"message": {"content": self._c}}]}


def _cfg(tmp_path, content=None):
    cfg = Config(staging_dir=tmp_path)
    if content is not None:
        cfg.llm = LLMConfig(provider="openai", model="m", base_url="http://x/v1")
    return cfg


def test_a_question_starts_empty(tmp_path):
    config = _cfg(tmp_path)
    q = add("Which broker is cheapest for ETFs in Austria?", config)
    assert q.id == 1 and q.evidence == 0 and q.status == "open"
    assert listing(config)[0].text.startswith("Which broker")


def test_material_is_matched_against_the_register(monkeypatch, tmp_path):
    config = _cfg(tmp_path, content="")
    add("Which broker is cheapest for ETFs in Austria?", config)
    add("How do I run agents without the cloud?", config)

    monkeypatch.setattr(
        httpx, "post",
        lambda *a, **k: _Resp('{"matches":[{"id":1,"stance":"advances","why":"lists actual fees"}]}'),
    )
    matches = match(
        Extracted(title="Broker fees compared", text="fees, spreads, custody costs"),
        "note-1", config,
    )
    assert len(matches) == 1
    assert matches[0]["stance"] == "advances"
    assert listing(config)[0].evidence == 1


def test_material_that_answers_nothing_says_so(monkeypatch, tmp_path):
    config = _cfg(tmp_path, content="")
    add("How do I run agents without the cloud?", config)
    monkeypatch.setattr(httpx, "post", lambda *a, **k: _Resp('{"matches": []}'))

    result = run("text", ref="text", text="A recipe for sourdough bread.", config=config)
    note = render_markdown(result.event)

    assert "## Your open questions" in note
    assert "advances none of them" in note


def test_an_advancing_source_is_named_in_the_note(monkeypatch, tmp_path):
    config = _cfg(tmp_path, content="")
    add("How do I run agents without the cloud?", config)
    monkeypatch.setattr(
        httpx, "post",
        lambda *a, **k: _Resp(
            '{"domain":"research","action":"note","summary":"s",'
            '"matches":[{"id":1,"stance":"advances","why":"names three local runtimes"}]}'
        ),
    )
    result = run("text", ref="text", text="Ollama, llama.cpp and vLLM all run locally.", config=config)
    note = render_markdown(result.event)

    assert "**advances** [1] How do I run agents without the cloud?" in note
    assert "names three local runtimes" in note


def test_an_unknown_question_id_from_the_model_is_ignored(monkeypatch, tmp_path):
    config = _cfg(tmp_path, content="")
    add("A real question", config)
    monkeypatch.setattr(
        httpx, "post",
        lambda *a, **k: _Resp('{"matches":[{"id":99,"stance":"advances","why":"hallucinated"}]}'),
    )
    assert match(Extracted(title="t", text="x"), "note-1", config) == []


def test_the_synthesis_reads_the_evidence_back(monkeypatch, tmp_path):
    config = _cfg(tmp_path, content="")
    add("Which broker is cheapest?", config)

    monkeypatch.setattr(
        httpx, "post",
        lambda *a, **k: _Resp(
            '{"domain":"finance","action":"note","summary":"s",'
            '"matches":[{"id":1,"stance":"advances","why":"names fees"}]}'
        ),
    )
    run("text", ref="text", text="Broker A charges 0.1%, broker B charges 1%.", config=config)

    monkeypatch.setattr(httpx, "post", lambda *a, **k: _Resp("Broker A is cheaper [1]. Missing: custody fees."))
    result = answer(1, config)

    assert "Broker A is cheaper" in result.answer
    assert len(result.sources) == 1


def test_evidence_without_an_llm_is_still_listed(tmp_path):
    config = _cfg(tmp_path)
    add("A question", config)
    result = answer(1, config)
    assert result.answer == ""
    assert result.engine == "evidence-only"


def test_closing_a_question_takes_it_out_of_the_register(tmp_path):
    config = _cfg(tmp_path)
    add("A question", config)
    assert close(1, config) is True
    assert listing(config) == []
    assert len(listing(config, include_answered=True)) == 1
