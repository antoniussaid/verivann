from smelt.adapters.transcribe import enabled, maybe_transcribe
from smelt.render.markdown import render_markdown
from smelt.schema import Decision, Extracted, IntakeEvent, Provenance, Routing, Source


def test_transcribe_disabled_by_default(monkeypatch, tmp_path):
    monkeypatch.delenv("SMELT_WHISPER_MODEL", raising=False)
    assert enabled() is False
    assert maybe_transcribe("https://example.com/v", tmp_path) == (None, None)


def _event_with_transcript() -> IntakeEvent:
    return IntakeEvent(
        id="x",
        created_at="t",
        source=Source(kind="youtube", ref="u"),
        extracted=Extracted(
            title="Vid",
            text="desc\n\n--- Transcript ---\nhello world",
            meta={
                "description": "desc",
                "transcript_text": "hello world",
                "transcript_source": "whisper",
                "transcript": "en",
            },
        ),
        routing=Routing(domain="media", confidence=0.5, reason="r"),
        decision=Decision(action="note", target="p"),
        provenance=Provenance(version="0.1.0"),
    )


def test_markdown_renders_full_transcript_section():
    md = render_markdown(_event_with_transcript())
    assert "## Transcript (whisper · en)" in md
    assert "hello world" in md
