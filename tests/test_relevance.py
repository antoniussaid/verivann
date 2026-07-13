from smelt.analysis.analyzer import Analysis, heuristic_analyze
from smelt.config import Config
from smelt.library import index_event, record_feedback
from smelt.pipeline import run
from smelt.relevance import MIN_SIGNAL, apply_profile, load_profile
from smelt.schema import Decision, Extracted, IntakeEvent, Provenance, Routing, Source


def _event(note_id: str, title: str, text: str, domain: str = "research") -> IntakeEvent:
    return IntakeEvent(
        id=note_id, created_at="2026-01-01T00:00:00Z",
        source=Source(kind="text", ref="text"),
        extracted=Extracted(title=title, text=text),
        routing=Routing(domain=domain, confidence=0.5, reason="r"),
        decision=Decision(action="note", target="t.md"),
        provenance=Provenance(tool="smelt", version="0", public_demo=True),
    )


def _judge(tmp_path, note_id, title, text, verdict, domain="research"):
    index_event(_event(note_id, title, text, domain), "n.md", "e.json", tmp_path)
    assert record_feedback(note_id, verdict, tmp_path) is not None


def test_profile_stays_dormant_below_the_signal_floor(tmp_path):
    _judge(tmp_path, "a", "Local agents", "local-first agent orchestration", "kept")
    profile = load_profile(tmp_path)
    assert profile.judged == 1 < MIN_SIGNAL
    assert profile.active is False
    assert profile.score("local-first agent orchestration") == 0.0
    assert profile.hint() == ""


def test_kept_material_scores_higher_than_dropped(tmp_path):
    for i in range(3):
        _judge(tmp_path, f"k{i}", "Local agents", "local-first agent orchestration sovereignty", "kept")
    for i in range(3):
        _judge(tmp_path, f"d{i}", "Crypto moonshot", "crypto pump memecoin airdrop hype", "dropped", "finance")

    profile = load_profile(tmp_path)
    assert profile.active
    assert profile.score("local-first agent orchestration") > 0.2
    assert profile.score("memecoin airdrop pump") < -0.2
    hint = profile.hint()
    assert "keep" in hint and "agent" in hint


def test_profile_nudges_heuristic_confidence_and_can_propose_a_drop(tmp_path):
    for i in range(6):
        _judge(tmp_path, f"d{i}", "Crypto moonshot", "crypto pump memecoin airdrop hype", "dropped", "finance")
    profile = load_profile(tmp_path)

    extracted = Extracted(title="Memecoin pump", text="crypto pump memecoin airdrop hype guaranteed")
    baseline = heuristic_analyze(extracted)
    nudged = apply_profile(Analysis(**vars(baseline)), extracted, profile)

    assert nudged.confidence < baseline.confidence
    assert nudged.action == "drop"  # a proposal — nothing is deleted
    assert "drop" in nudged.reason.lower()


def test_feedback_accepts_an_id_prefix_and_unknown_ids_are_reported(tmp_path):
    index_event(_event("abcdef-1234", "T", "body text here"), "n.md", "e.json", tmp_path)
    assert record_feedback("abcdef", "kept", tmp_path).title == "T"
    assert record_feedback("zzz", "kept", tmp_path) is None


def test_intake_still_works_when_the_profile_is_empty(tmp_path):
    config = Config(staging_dir=tmp_path)
    result = run("text", ref="text", text="an automation pipeline for local-first agents", config=config)
    assert result.event.routing.domain == "research"
