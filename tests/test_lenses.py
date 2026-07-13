import httpx

from verivann.analysis.analyzer import analyze
from verivann.analysis.lenses import DEFAULT_LENS, get_lens, lens_names
from verivann.config import Config, LLMConfig
from verivann.schema import Extracted


class _FakeResp:
    def __init__(self, payload):
        self._p = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self._p


def test_unknown_lens_falls_back_to_default():
    assert get_lens("does-not-exist").name == DEFAULT_LENS
    assert get_lens(None).name == DEFAULT_LENS
    assert "critique" in lens_names()


def test_lens_reaches_the_llm_system_prompt(monkeypatch):
    seen = {}

    def fake_post(url, headers=None, json=None, timeout=None):
        seen["system"] = json["messages"][0]["content"]
        return _FakeResp({"choices": [{"message": {"content": '{"domain":"research","action":"note"}'}}]})

    monkeypatch.setattr(httpx, "post", fake_post)
    cfg = Config(llm=LLMConfig(provider="openai", model="m", base_url="http://x/v1"))
    result = analyze(Extracted(title="t", text="some material about agents"), cfg, lens="critique")

    assert result.lens == "critique"
    assert "critique" in seen["system"]
    assert "adversarially" in seen["system"].lower()


def test_lens_is_recorded_even_without_an_llm():
    result = analyze(Extracted(title="t", text="an automation pipeline for local-first agents"), Config(), lens="study")
    assert result.engine == "heuristic"
    assert result.lens == "study"


def test_lens_headings_rename_the_note_sections():
    from verivann.analysis.analyzer import Analysis
    from verivann.render import render_markdown
    from verivann.schema import Decision, IntakeEvent, Provenance, Routing, Source

    event = IntakeEvent(
        id="x", created_at="2026-01-01T00:00:00Z",
        source=Source(kind="text", ref="text"),
        extracted=Extracted(title="t", text="body"),
        routing=Routing(domain="research", confidence=0.5, reason="r"),
        decision=Decision(action="note", target="t.md"),
        provenance=Provenance(tool="verivann", version="0", public_demo=True),
    )
    analysis = Analysis("research", 0.5, "r", "note", useful_ideas=["i"], lens="wisdom")
    note = render_markdown(event, analysis)

    assert "## Insights" in note
    assert "## Useful ideas" not in note
    assert "lens: wisdom" in note
