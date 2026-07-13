from smelt.accept import accept
from smelt.calibrate import MIN_JUDGED, calibrate
from smelt.cockpit import load
from smelt.config import Config
from smelt.library import index_event, record_feedback, verdict_of
from smelt.pipeline import run
from smelt.relevance import load_profile
from smelt.schema import Decision, Extracted, IntakeEvent, Provenance, Routing, Source
from smelt.signals import implied_drops, observe, sweep


def _old_note(note_id: str, title: str, staging, days_ago: int, action="note", confidence=0.7,
              engine="llm:m", lens="digest") -> IntakeEvent:
    from datetime import datetime, timedelta, timezone

    created = (datetime.now(timezone.utc) - timedelta(days=days_ago)).isoformat()
    event = IntakeEvent(
        id=note_id, created_at=created,
        source=Source(kind="text", ref="text"),
        extracted=Extracted(title=title, text=f"{title} body text about agents"),
        routing=Routing(domain="research", confidence=confidence, reason="r"),
        decision=Decision(action=action, target="t.md"),
        provenance=Provenance(tool="smelt", version="0", public_demo=True),
    )
    index_event(event, "n.md", "e.json", staging, engine=engine, lens=lens)
    return event


# ---------- implicit verdicts ----------

def test_silence_becomes_a_weak_verdict(tmp_path):
    _old_note("old", "Ignored piece", tmp_path, days_ago=45)
    _old_note("fresh", "Recent piece", tmp_path, days_ago=2)

    implied = implied_drops(tmp_path)
    assert [i.id for i in implied] == ["old"]
    assert implied[0].days >= 44

    assert sweep(tmp_path) == 1
    assert verdict_of("old", tmp_path) == "dropped"
    assert verdict_of("fresh", tmp_path) == ""


def test_an_inferred_verdict_never_overwrites_yours(tmp_path):
    _old_note("old", "You kept this", tmp_path, days_ago=90)
    record_feedback("old", "kept", tmp_path)  # you decided

    sweep(tmp_path)  # silence tries to say otherwise
    assert verdict_of("old", tmp_path) == "kept"  # you win, always


def test_opening_a_note_is_a_quiet_keep(tmp_path):
    _old_note("n1", "A note", tmp_path, days_ago=5)
    observe("n1", "open", tmp_path)

    assert verdict_of("n1", tmp_path) == "kept"
    profile = load_profile(tmp_path)
    assert profile.n_kept == 1
    assert profile.weight_kept == 0.4  # a glance, not a decision


def test_accepting_is_a_full_keep(tmp_path):
    config = Config(staging_dir=tmp_path)
    result = run("text", ref="text", text="an automation pipeline worth keeping", config=config)
    accept(result.event.id, tmp_path / "vault", config)

    profile = load_profile(tmp_path)
    assert profile.weight_kept == 1.0


def test_a_hundred_shrugs_do_not_outshout_one_verdict(tmp_path):
    """The profile wakes on the WEIGHT of evidence, not on the number of rows."""
    for i in range(10):
        _old_note(f"ign{i}", f"Ignored {i}", tmp_path, days_ago=60)
    sweep(tmp_path)  # 10 implicit drops, weight 0.25 each = 2.5

    profile = load_profile(tmp_path)
    assert profile.n_dropped == 10
    assert profile.evidence == 2.5
    assert profile.active is False  # still below MIN_SIGNAL (3.0) — correctly silent

    _old_note("real", "Explicitly dropped", tmp_path, days_ago=1)
    record_feedback("real", "dropped", tmp_path)
    assert load_profile(tmp_path).active is True  # one real verdict tips it


# ---------- calibration ----------

def test_calibration_refuses_to_report_on_thin_evidence(tmp_path):
    _old_note("n1", "A", tmp_path, days_ago=1)
    record_feedback("n1", "kept", tmp_path)

    report = calibrate(tmp_path)
    assert report.enough is False
    assert "not enough" in report.headline()
    assert f"{MIN_JUDGED} needed" in report.headline()


def test_the_router_is_measured_against_your_verdicts(tmp_path):
    # It proposed keeping 8 notes; you kept 2 of them. It proposed dropping 4; you dropped 4.
    for i in range(8):
        _old_note(f"k{i}", f"Proposed keep {i}", tmp_path, days_ago=1, action="note")
        record_feedback(f"k{i}", "kept" if i < 2 else "dropped", tmp_path)
    for i in range(4):
        _old_note(f"d{i}", f"Proposed drop {i}", tmp_path, days_ago=1, action="drop")
        record_feedback(f"d{i}", "dropped", tmp_path)

    report = calibrate(tmp_path)
    assert report.enough
    assert report.keeper_proposed == 8 and report.keeper_kept == 2
    assert report.keeper_precision == 0.25
    assert report.drop_precision == 1.0
    assert report.accuracy == 0.5
    assert "over-proposes" in report.headline()


def test_confidence_that_means_nothing_is_called_out(tmp_path):
    # High confidence, all dropped. Low confidence, all kept. Anti-calibrated.
    for i in range(6):
        _old_note(f"h{i}", f"Loud {i}", tmp_path, days_ago=1, confidence=0.9)
        record_feedback(f"h{i}", "dropped", tmp_path)
    for i in range(6):
        _old_note(f"l{i}", f"Quiet {i}", tmp_path, days_ago=1, confidence=0.3)
        record_feedback(f"l{i}", "kept", tmp_path)

    report = calibrate(tmp_path)
    assert report.calibrated() is False
    assert "NOT calibrated" in report.headline()


def test_lenses_and_engines_are_compared(tmp_path):
    for i in range(6):
        _old_note(f"c{i}", f"Critique {i}", tmp_path, days_ago=1, lens="critique", engine="llm:a")
        record_feedback(f"c{i}", "kept", tmp_path)
    for i in range(6):
        _old_note(f"d{i}", f"Digest {i}", tmp_path, days_ago=1, lens="digest", engine="heuristic")
        record_feedback(f"d{i}", "dropped", tmp_path)

    report = calibrate(tmp_path)
    by_lens = {s.name: s.accuracy for s in report.lenses}
    assert by_lens["critique"] == 1.0     # proposed keep, you kept
    assert by_lens["digest"] == 0.0       # proposed keep, you dropped
    by_engine = {s.name: s.accuracy for s in report.engines}
    assert by_engine["llm:a"] == 1.0 and by_engine["heuristic"] == 0.0


# ---------- the cockpit ----------

def test_an_empty_cockpit_says_the_ledger_is_clean(tmp_path):
    view = load(Config(staging_dir=tmp_path))
    assert view.quiet
    assert view.headline() == "Nothing is due. The ledger is clean."


def test_the_cockpit_leads_with_the_unread_pile(tmp_path):
    config = Config(staging_dir=tmp_path)
    for i in range(3):
        run("text", ref="text", text=f"some material about agents {i}", config=config)

    view = load(config)
    assert view.unjudged == 3
    assert view.unanalyzed == 3
    assert "No model is configured" in view.headline()


def test_a_due_prediction_outranks_everything(tmp_path):
    from smelt.predictions import record

    config = Config(staging_dir=tmp_path)
    run("text", ref="text", text="material", config=config)
    record("n", "youtube:@guru", [{"text": "Rates fall", "due": "2026-01-01"}], tmp_path)

    view = load(config)
    assert len(view.due_predictions) == 1
    assert "come due" in view.headline()
