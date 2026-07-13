"""The download decision is the user's. These tests are the proof.

This is not a preference toggle — it is where the legal architecture lives. Reading
a platform's published captions touches nothing. Fetching the media file touches the
platform's terms, and that act must belong to the person who agreed to those terms,
on their machine, under a setting they chose.
"""

import pytest

from smelt.mediapolicy import ALWAYS, ASK, FALLBACK, OFF, decide, keep_media, mode


@pytest.fixture(autouse=True)
def _clean(monkeypatch):
    monkeypatch.delenv("SMELT_MEDIA", raising=False)
    monkeypatch.delenv("SMELT_MEDIA_KEEP", raising=False)


def test_the_default_is_the_most_conservative_one_that_still_works():
    assert mode() == FALLBACK
    assert keep_media() is False  # we wanted the words, not the video


def test_captions_mean_nothing_is_downloaded():
    decision = decide(has_captions=True)
    assert decision.allowed is False
    assert "nothing was downloaded" in decision.note.lower()


def test_no_captions_means_audio_only_to_transcribe_and_then_deleted():
    decision = decide(has_captions=False)
    assert decision.allowed is True
    assert "deleted immediately" in decision.note
    assert "on your machine, under your setting" in decision.note


def test_off_means_off_even_without_captions(monkeypatch):
    monkeypatch.setenv("SMELT_MEDIA", OFF)
    decision = decide(has_captions=False)
    assert decision.allowed is False
    assert "policy: off" in decision.note


def test_ask_without_anyone_to_ask_is_a_no(monkeypatch):
    """A scheduled run, a server, a background job. Silence is never consent."""
    monkeypatch.setenv("SMELT_MEDIA", ASK)
    assert decide(has_captions=False, asked=None).allowed is False
    assert decide(has_captions=False, asked=lambda: False).allowed is False
    assert decide(has_captions=False, asked=lambda: True).allowed is True


def test_always_downloads_even_when_captions_exist(monkeypatch):
    monkeypatch.setenv("SMELT_MEDIA", ALWAYS)
    assert decide(has_captions=True).allowed is True


def test_keeping_the_file_is_stated_in_the_note(monkeypatch):
    monkeypatch.setenv("SMELT_MEDIA_KEEP", "1")
    decision = decide(has_captions=False)
    assert "and kept" in decision.note


def test_an_unknown_mode_falls_back_to_the_safe_one(monkeypatch):
    monkeypatch.setenv("SMELT_MEDIA", "yolo")
    assert mode() == FALLBACK


def test_a_protected_platform_can_never_be_switched_on(monkeypatch):
    """The rule no setting overrides.

    YouTube protects its media stream. Fetching it means circumventing that — and in
    the EU that is § 90c UrhG, which reaches the tool itself, not just the user. A
    user can consent to many things; they cannot consent us out of that. So: captions
    only, always, no matter what the config says.
    """
    monkeypatch.setenv("SMELT_MEDIA", ALWAYS)
    for url in (
        "https://youtube.com/watch?v=x",
        "https://youtu.be/x",
        "https://netflix.com/title/1",
        "https://open.spotify.com/episode/1",
    ):
        decision = decide(has_captions=False, asked=lambda: True, url=url)
        assert decision.allowed is False, url
        assert "cannot be switched on" in decision.note


def test_an_unprotected_platform_still_follows_the_user_setting(monkeypatch):
    monkeypatch.setenv("SMELT_MEDIA", ALWAYS)
    assert decide(has_captions=False, url="https://example.com/talk.mp4").allowed is True
    monkeypatch.setenv("SMELT_MEDIA", OFF)
    assert decide(has_captions=False, url="https://example.com/talk.mp4").allowed is False


def test_the_policy_reaches_the_note(monkeypatch, tmp_path):
    from smelt.config import Config
    from smelt.pipeline import run
    from smelt.render import render_markdown
    from smelt.schema import Extracted

    monkeypatch.setattr(
        "smelt.pipeline.extract_media",
        lambda url, subs: Extracted(
            title="A video", text="spoken words about agents",
            meta={"media_policy": "fallback",
                  "media_note": "Captions were read; **nothing was downloaded**."},
        ),
    )
    result = run("youtube", ref="https://youtube.com/watch?v=x", config=Config(staging_dir=tmp_path))
    note = render_markdown(result.event)

    assert "## How this was read" in note
    assert "nothing was downloaded" in note
    assert "media policy: `fallback`" in note
