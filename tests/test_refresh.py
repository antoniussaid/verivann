from datetime import datetime, timedelta, timezone

import httpx

from smelt.config import Config, LLMConfig
from smelt.library import (
    index_claims,
    index_event,
    mark_source,
    record_feedback,
    set_prediction_status,
)
from smelt.pipeline import run
from smelt.predictions import record
from smelt.questions import add
from smelt.refresh import refresh
from smelt.resurface import resurface
from smelt.schema import Decision, Extracted, IntakeEvent, Provenance, Routing, Source


class _Resp:
    def __init__(self, content):
        self._c = content

    def raise_for_status(self):
        return None

    def json(self):
        return {"choices": [{"message": {"content": self._c}}]}


def _staged(note_id, title, text, tmp_path, days_ago=0, source_key="web:example.com"):
    """A note that exists both on disk and in the index — like a real one."""
    created = (datetime.now(timezone.utc) - timedelta(days=days_ago)).isoformat()
    notes = tmp_path / "notes"
    notes.mkdir(parents=True, exist_ok=True)
    path = notes / f"{note_id}.md"
    path.write_text(
        f"---\nid: {note_id}\ntitle: \"{title}\"\n---\n\n# Intake: {title}\n\n{text}\n",
        encoding="utf-8",
    )
    event = IntakeEvent(
        id=note_id, created_at=created,
        source=Source(kind="url", ref=f"https://example.com/{note_id}"),
        extracted=Extracted(title=title, text=text),
        routing=Routing(domain="research", confidence=0.6, reason="r"),
        decision=Decision(action="note", target=str(path)),
        provenance=Provenance(tool="smelt", version="0", public_demo=True),
    )
    index_event(event, str(path), "e.json", tmp_path)
    return path


def test_a_note_learns_that_it_was_contradicted(monkeypatch, tmp_path):
    old_path = _staged("old", "Whisper needs a GPU", "GPU required for whisper", tmp_path)
    index_claims("old", ["Whisper needs a GPU."], tmp_path)

    monkeypatch.setattr(
        httpx, "post",
        lambda *a, **k: _Resp(
            '{"domain":"research","action":"note","summary":"s",'
            '"claims_to_verify":["Whisper runs fine on CPU."]}'
        ),
    )
    config = Config(staging_dir=tmp_path, llm=LLMConfig(provider="openai", model="m", base_url="http://x/v1"))

    # The second call (the contradiction check) must answer "yes, they conflict".
    calls = {"n": 0}

    def two_step(*a, **k):
        calls["n"] += 1
        if calls["n"] == 1:
            return _Resp('{"domain":"research","action":"note","claims_to_verify":["Whisper runs fine on CPU."]}')
        return _Resp('{"conflict": true, "with": "Whisper needs a GPU.", "why": "CPU suffices."}')

    monkeypatch.setattr(httpx, "post", two_step)
    run("text", ref="text", text="Whisper runs fine on CPU these days.", config=config)

    changed = refresh(config)
    assert len(changed) == 1
    text = old_path.read_text(encoding="utf-8")
    assert "Since you read this" in text
    assert "Contradicted" in text


def test_expired_claims_and_missed_predictions_reach_the_note(tmp_path):
    path = _staged("n1", "A confident piece", "body", tmp_path)
    index_claims("n1", ["The rate is 2%."], tmp_path, shelf_life_days=-1)  # already expired
    record("n1", "web:example.com", [{"text": "Rates will fall", "due": "2026-01-01"}], tmp_path)
    from smelt.library import prediction_rows

    set_prediction_status(prediction_rows(tmp_path)[0]["id"], "miss", tmp_path)

    refresh(Config(staging_dir=tmp_path))
    text = path.read_text(encoding="utf-8")
    assert "past their shelf life" in text
    assert "did not come true" in text


def test_a_source_that_went_bad_taints_its_old_notes(tmp_path):
    path = _staged("n1", "An old piece", "body", tmp_path)
    mark_source("web:example.com", "misses", tmp_path)
    mark_source("web:example.com", "hostile", tmp_path)

    refresh(Config(staging_dir=tmp_path))
    text = path.read_text(encoding="utf-8")
    assert "The source's record has changed" in text
    assert "manipulate" in text


def test_refreshing_twice_does_not_stack_banners(tmp_path):
    path = _staged("n1", "A piece", "body", tmp_path)
    index_claims("n1", ["Stale claim."], tmp_path, shelf_life_days=-1)
    config = Config(staging_dir=tmp_path)

    refresh(config)
    refresh(config)
    text = path.read_text(encoding="utf-8")
    assert text.count("Since you read this") == 1
    assert text.count("<!-- smelt:since -->") == 1


def test_the_frontmatter_survives_the_banner(tmp_path):
    path = _staged("n1", "A piece", "body", tmp_path)
    index_claims("n1", ["Stale."], tmp_path, shelf_life_days=-1)

    refresh(Config(staging_dir=tmp_path))
    text = path.read_text(encoding="utf-8")
    assert text.startswith("---\n")
    assert text.index("id: n1") < text.index("Since you read this")
    assert "# Intake: A piece" in text


# ---------- resurfacing ----------

def test_the_library_hands_back_what_you_forgot(tmp_path):
    config = Config(staging_dir=tmp_path)
    _staged("old", "Local-first agent sovereignty", "self-hosted local agents without the cloud",
            tmp_path, days_ago=200)
    record_feedback("old", "kept", tmp_path)
    add("How do I run agents without the cloud?", config)

    found = resurface(config)
    assert found and found[0].id == "old"
    assert found[0].age_days >= 190
    assert "your question" in found[0].because


def test_something_you_saw_last_week_is_not_a_discovery(tmp_path):
    config = Config(staging_dir=tmp_path)
    _staged("fresh", "Local-first agents", "self-hosted local agents", tmp_path, days_ago=3)
    record_feedback("fresh", "kept", tmp_path)
    add("How do I run agents without the cloud?", config)

    assert resurface(config) == []
