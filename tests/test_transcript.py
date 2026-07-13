import json

from smelt.adapters.media import (
    _json3_to_cues,
    _vtt_to_cues,
    group_cues,
    seek_template,
    timestamp,
)
from smelt.analysis.analyzer import Analysis
from smelt.render import render_markdown
from smelt.schema import Decision, Extracted, IntakeEvent, Provenance, Routing, Source


def test_json3_keeps_the_timeline():
    raw = json.dumps({"events": [
        {"tStartMs": 0, "segs": [{"utf8": "hello "}, {"utf8": "world"}]},
        {"tStartMs": 5000, "segs": [{"utf8": "second line"}]},
        {"tStartMs": 5000, "segs": [{"utf8": "second line"}]},  # rolling repeat
        {"tStartMs": 61000, "segs": [{"utf8": "later"}]},
    ]})
    cues = _json3_to_cues(raw)
    assert cues == [(0, "hello world"), (5, "second line"), (61, "later")]


def test_vtt_timestamps_are_parsed():
    raw = "WEBVTT\n\n00:00:01.000 --> 00:00:03.000\nfirst\n\n00:01:04.500 --> 00:01:06.000\nsecond\n"
    assert _vtt_to_cues(raw) == [(1, "first"), (64, "second")]


def test_cues_are_grouped_into_readable_blocks():
    cues = [(i * 5, f"line {i}") for i in range(6)]  # 0,5,10,…,25s
    blocks = group_cues(cues, window=20)
    assert blocks[0][0] == 0
    assert "line 0" in blocks[0][1] and "line 4" in blocks[0][1]
    assert blocks[1][0] == 25


def test_timestamp_and_seek_template():
    assert timestamp(65) == "01:05"
    assert timestamp(3725) == "1:02:05"
    assert seek_template("https://youtu.be/abc").format(t=90) == "https://youtu.be/abc?t=90s"
    assert seek_template("https://www.tiktok.com/@x/video/1") is None


def test_timestamped_transcript_is_rendered_with_seek_links():
    meta = {
        "transcript_text": "hello world\nlater",
        "transcript_source": "captions",
        "transcript": "en",
        "transcript_cues": [[0, "hello world"], [61, "later"]],
        "transcript_seek": "https://youtu.be/abc?t={t}s",
    }
    event = IntakeEvent(
        id="x", created_at="2026-01-01T00:00:00Z",
        source=Source(kind="youtube", ref="https://youtu.be/abc"),
        extracted=Extracted(title="t", text="body", meta=meta),
        routing=Routing(domain="media", confidence=0.5, reason="r"),
        decision=Decision(action="note", target="t.md"),
        provenance=Provenance(tool="smelt", version="0", public_demo=True),
    )
    note = render_markdown(event, Analysis("media", 0.5, "r", "note"))

    assert "## Transcript (captions · en · timestamped)" in note
    assert "**[01:01](https://youtu.be/abc?t=61s)** later" in note


def test_untimed_transcript_still_renders_plain():
    meta = {"transcript_text": "just text", "transcript_source": "whisper", "transcript": "de"}
    event = IntakeEvent(
        id="x", created_at="2026-01-01T00:00:00Z",
        source=Source(kind="url", ref="https://tiktok.com/x"),
        extracted=Extracted(title="t", text="body", meta=meta),
        routing=Routing(domain="media", confidence=0.5, reason="r"),
        decision=Decision(action="note", target="t.md"),
        provenance=Provenance(tool="smelt", version="0", public_demo=True),
    )
    note = render_markdown(event, Analysis("media", 0.5, "r", "note"))
    assert "## Transcript (whisper · de)" in note
    assert "just text" in note
