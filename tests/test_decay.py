import httpx

from smelt.claims import check_contradictions
from smelt.config import Config, LLMConfig
from smelt.library import index_claims, index_event, record_feedback, stale_claims
from smelt.render import render_markdown
from smelt.schema import Decision, Extracted, IntakeEvent, Provenance, Routing, Source


class _Resp:
    def __init__(self, content):
        self._c = content

    def raise_for_status(self):
        return None

    def json(self):
        return {"choices": [{"message": {"content": self._c}}]}


def _note(note_id: str, title: str, staging) -> IntakeEvent:
    event = IntakeEvent(
        id=note_id, created_at="2026-01-01T00:00:00Z",
        source=Source(kind="text", ref="text"),
        extracted=Extracted(title=title, text="body"),
        routing=Routing(domain="research", confidence=0.5, reason="r"),
        decision=Decision(action="note", target="t.md"),
        provenance=Provenance(tool="smelt", version="0", public_demo=True),
    )
    index_event(event, "n.md", "e.json", staging)
    return event


def test_a_claim_with_a_short_shelf_life_goes_stale(tmp_path):
    index_claims("note-1", ["The ECB rate is 2%."], tmp_path, shelf_life_days=0)
    assert stale_claims(tmp_path) == []  # no shelf life -> never nags

    index_claims("note-2", ["Bitcoin trades at 90k."], tmp_path, shelf_life_days=-1)  # already expired
    rows = stale_claims(tmp_path)
    assert len(rows) == 1
    assert "Bitcoin" in rows[0]["claim"]


def test_a_long_lived_claim_does_not_go_stale(tmp_path):
    index_claims("note-1", ["Water boils at 100°C at sea level."], tmp_path, shelf_life_days=3650)
    assert stale_claims(tmp_path) == []


def test_contradicting_a_note_you_kept_is_you_contradicting_yourself(monkeypatch, tmp_path):
    kept = _note("note-kept", "Whisper needs a GPU", tmp_path)
    index_claims(kept.id, ["Whisper needs a GPU."], tmp_path)
    record_feedback(kept.id, "kept", tmp_path)

    monkeypatch.setattr(
        httpx, "post",
        lambda *a, **k: _Resp('{"conflict": true, "with": "Whisper needs a GPU.", "why": "CPU suffices."}'),
    )
    cfg = Config(staging_dir=tmp_path, llm=LLMConfig(provider="openai", model="m", base_url="http://x/v1"))
    conflicts = check_contradictions(["Whisper runs fine on CPU."], cfg, tmp_path, exclude_note="note-new")

    assert conflicts[0]["yourself"] is True
    assert conflicts[0]["against"] == "Whisper needs a GPU"


def test_contradicting_an_unjudged_note_is_not_your_fault(monkeypatch, tmp_path):
    other = _note("note-other", "Some blog", tmp_path)
    index_claims(other.id, ["Whisper needs a GPU."], tmp_path)  # never judged

    monkeypatch.setattr(
        httpx, "post",
        lambda *a, **k: _Resp('{"conflict": true, "with": "Whisper needs a GPU.", "why": "CPU suffices."}'),
    )
    cfg = Config(staging_dir=tmp_path, llm=LLMConfig(provider="openai", model="m", base_url="http://x/v1"))
    conflicts = check_contradictions(["Whisper runs fine on CPU."], cfg, tmp_path, exclude_note="note-new")

    assert conflicts[0]["yourself"] is False


def test_self_contradiction_is_named_in_the_note():
    event = IntakeEvent(
        id="x", created_at="2026-01-01T00:00:00Z",
        source=Source(kind="text", ref="text"),
        extracted=Extracted(title="t", text="body", meta={"contradictions": [
            {"claim": "CPU is enough", "conflicts_with": "GPU required",
             "why": "both cannot hold", "against": "Old note", "yourself": True},
        ]}),
        routing=Routing(domain="research", confidence=0.5, reason="r"),
        decision=Decision(action="note", target="t.md"),
        provenance=Provenance(tool="smelt", version="0", public_demo=True),
    )
    note = render_markdown(event)
    assert "You contradict yourself." in note
    assert "_(a note you kept)_" in note
