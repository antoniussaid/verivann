"""External-tool health — the yt-dlp staleness check that answers its own support case."""

from datetime import date

from verivann.tools import staleness_days, ytdlp_health


def test_staleness_reads_a_date_version():
    assert staleness_days("2026.01.01", date(2026, 1, 31)) == 30
    assert staleness_days("2026.07.01", date(2026, 7, 1)) == 0


def test_staleness_is_none_for_a_non_date_version():
    assert staleness_days("nightly", date(2026, 7, 1)) is None
    assert staleness_days("", date(2026, 7, 1)) is None


def test_staleness_never_goes_negative():
    # A clock skew (version dated in the future) must not report a negative age.
    assert staleness_days("2027.01.01", date(2026, 7, 1)) == 0


def test_health_absent_when_no_version(monkeypatch):
    # version=None means "look it up" — force the lookup to find nothing.
    monkeypatch.setattr("verivann.tools.ytdlp_version", lambda: None)
    assert ytdlp_health(date(2026, 7, 1)) == "no (youtube falls back)"


def test_health_fresh_version_is_just_the_number():
    assert ytdlp_health(date(2026, 7, 1), version="2026.06.20") == "2026.06.20"


def test_health_stale_version_nudges_an_update():
    line = ytdlp_health(date(2026, 7, 1), version="2026.01.01")
    assert "2026.01.01" in line
    assert "yt-dlp -U" in line
    assert "days old" in line


def test_health_odd_version_string_is_reported_as_is():
    # Unparseable version → shown, not hidden, and not flagged stale.
    assert ytdlp_health(date(2026, 7, 1), version="2026.1") == "2026.1"
