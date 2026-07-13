"""An editor you have to wake up every morning is not an editor."""

import httpx

from smelt.config import Config
from smelt.daemon import due, install_hint, run_once, schedule
from smelt.library import get_state


def test_the_schedule_is_what_it_says_it_is():
    names = [job.name for job in schedule()]
    assert names == ["feeds", "watch", "refresh", "sweep"]
    every = {job.name: job.every_seconds for job in schedule()}
    assert every["feeds"] == 3600
    assert every["sweep"] == 86400


def test_everything_is_due_on_a_fresh_machine(tmp_path):
    config = Config(staging_dir=tmp_path)
    assert [job.name for job in due(config)] == ["feeds", "watch", "refresh", "sweep"]


def test_a_job_that_just_ran_is_not_due_again(tmp_path):
    config = Config(staging_dir=tmp_path)
    run_once(config)

    assert due(config) == []  # everything was just done
    assert get_state("daemon.feeds", tmp_path) != ""


def test_a_broken_job_does_not_stop_the_schedule(monkeypatch, tmp_path):
    def explode(config):
        raise RuntimeError("the feed server is on fire")

    monkeypatch.setattr("smelt.daemon._feeds", explode)
    config = Config(staging_dir=tmp_path)

    result = run_once(config)
    assert "feeds" in result.failed
    assert "on fire" in result.failed["feeds"]
    assert set(result.done) == {"watch", "refresh", "sweep"}  # the rest still ran


def test_the_daemon_never_downloads_media_because_nobody_is_there_to_ask(monkeypatch):
    """SMELT_MEDIA=ask in a background run means NO. Silence is not consent."""
    monkeypatch.setenv("SMELT_MEDIA", "ask")
    from smelt.mediapolicy import decide

    assert decide(has_captions=False, asked=None).allowed is False


def test_the_daemon_proposes_and_never_commits(monkeypatch, tmp_path):
    """Whatever it does, a human still has to accept it. It cannot."""
    from smelt.library import verdict_of
    from smelt.pipeline import run

    monkeypatch.setattr(httpx, "get", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("no net")))
    config = Config(staging_dir=tmp_path)
    note = run("text", ref="text", text="an automation pipeline for local agents", config=config)

    run_once(config)
    # The sweep is the only job that writes a verdict at all — and only for notes the
    # user has ignored for 30+ days. A fresh note is untouched.
    assert verdict_of(note.event.id, tmp_path) == ""


def test_the_install_hint_is_a_command_you_can_paste():
    hint = install_hint("python.exe", "D:/notes")
    assert "schtasks" in hint      # Windows
    assert "*/30 * * * *" in hint  # cron
    assert "daemon --once" in hint
