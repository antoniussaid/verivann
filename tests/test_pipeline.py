import json

from verivann.config import Config
from verivann.pipeline import run
from verivann.schema import IntakeEvent


def test_textdump_creates_md_and_json(tmp_path):
    cfg = Config(staging_dir=tmp_path)
    result = run(
        "text",
        ref="text",
        text="This article explains local AI memory and self-hosted automation architecture.",
        config=cfg,
    )
    assert result.note_path.exists()
    assert result.event_path.exists()
    assert result.note_path.suffix == ".md"
    assert result.event_path.suffix == ".json"


def test_event_validates_against_schema(tmp_path):
    cfg = Config(staging_dir=tmp_path)
    result = run("text", ref="text", text="Some research about AI systems and architecture.", config=cfg)
    data = json.loads(result.event_path.read_text(encoding="utf-8"))
    event = IntakeEvent.model_validate(data)  # raises if the contract shape is wrong
    assert event.source.kind == "text"
    assert event.provenance.public_demo is True
    # intake material is always flagged untrusted; the core never trusts it
    assert event.provenance.content_trust == "unverified"
    # public core never auto-commits memory
    assert event.decision.action in ("note", "task", "drop")


def test_markdown_has_required_sections(tmp_path):
    cfg = Config(staging_dir=tmp_path)
    result = run("text", ref="text", text="Some research about AI systems and architecture.", config=cfg)
    md = result.note_path.read_text(encoding="utf-8")
    for needle in ["## Why it matters", "## Summary", "## Routing (proposal)", "proposed_action:"]:
        assert needle in md
