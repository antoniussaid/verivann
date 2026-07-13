import sqlite3
from datetime import datetime, timedelta, timezone

from smelt.config import Config
from smelt.importer import _CHROME_EPOCH, from_history, from_obsidian, from_urls, ingest
from smelt.schema import Extracted


def test_any_export_format_works_because_we_only_take_the_links(tmp_path):
    export = tmp_path / "pocket.csv"
    export.write_text(
        "title,url,time_added,tags\n"
        '"A piece",https://example.com/a?utm_source=pocket,1700000000,tech\n'
        '"Same piece",https://example.com/a,1700000001,tech\n'
        '"A video",https://youtu.be/xyz,1700000002,\n',
        encoding="utf-8",
    )
    candidates = from_urls(export)

    assert [c.ref for c in candidates] == ["https://example.com/a", "https://youtube.com/watch?v=xyz"]
    assert candidates[1].kind == "youtube"  # canonicalized AND recognized


def test_a_vault_is_read_not_touched(tmp_path):
    vault = tmp_path / "vault"
    (vault / "sub").mkdir(parents=True)
    (vault / "one.md").write_text("# One\nlocal-first agents", encoding="utf-8")
    (vault / "sub" / "two.md").write_text("# Two\nbroker fees", encoding="utf-8")
    (vault / ".obsidian").mkdir()
    (vault / ".obsidian" / "config.md").write_text("junk", encoding="utf-8")

    candidates = from_obsidian(vault)
    assert [c.title for c in candidates] == ["one", "two"]  # dotfolders skipped
    assert all(c.kind == "file" for c in candidates)  # → sensitive → never uploaded

    before = {p.name: p.read_text(encoding="utf-8") for p in vault.rglob("*.md")}
    ingest(candidates, Config(staging_dir=tmp_path / "staging"))
    after = {p.name: p.read_text(encoding="utf-8") for p in vault.rglob("*.md")}
    assert before == after


def test_the_pages_you_came_back_to(tmp_path):
    history = tmp_path / "History"
    con = sqlite3.connect(history)
    con.execute("CREATE TABLE urls (url TEXT, title TEXT, visit_count INT, last_visit_time INT)")
    recent = int((datetime.now(timezone.utc) - _CHROME_EPOCH).total_seconds() * 1e6)
    old = int((datetime.now(timezone.utc) - timedelta(days=200) - _CHROME_EPOCH).total_seconds() * 1e6)
    con.executemany(
        "INSERT INTO urls VALUES (?,?,?,?)",
        [
            ("https://example.com/read-often", "Read often", 9, recent),
            ("https://example.com/once", "Seen once", 1, recent),          # below threshold
            ("https://example.com/ancient", "Old news", 9, old),           # too old
            ("https://mail.google.com/inbox", "Inbox", 50, recent),        # never
        ],
    )
    con.commit()
    con.close()

    candidates = from_history(days=60, min_visits=3, browser_db=history)
    assert [c.ref for c in candidates] == ["https://example.com/read-often"]
    assert candidates[0].hint == "9 visits"


def test_a_missing_browser_is_not_a_crash(tmp_path):
    assert from_history(browser_db=tmp_path / "nope") == []


def test_importing_twice_digests_nothing_twice(monkeypatch, tmp_path):
    monkeypatch.setattr(
        "smelt.pipeline.extract_webpage",
        lambda url: Extracted(title="A piece", text="a local-first automation pipeline", meta={}),
    )
    export = tmp_path / "list.txt"
    export.write_text("https://example.com/a\n", encoding="utf-8")
    config = Config(staging_dir=tmp_path / "staging")

    first = ingest(from_urls(export), config)
    assert first.imported == 1 and first.skipped == 0

    second = ingest(from_urls(export), config)
    assert second.imported == 0 and second.skipped == 1  # resumable, not duplicating


def test_a_broken_link_does_not_stop_the_migration(monkeypatch, tmp_path):
    def flaky(url):
        if "bad" in url:
            raise RuntimeError("boom")
        return Extracted(title="Fine", text="an automation pipeline for agents", meta={})

    monkeypatch.setattr("smelt.pipeline.extract_webpage", flaky)
    export = tmp_path / "list.txt"
    export.write_text("https://example.com/bad\nhttps://example.com/good\n", encoding="utf-8")

    outcome = ingest(from_urls(export), Config(staging_dir=tmp_path / "staging"))
    assert outcome.imported == 1
    assert outcome.failed == 1


def test_the_limit_is_a_hard_bound(monkeypatch, tmp_path):
    monkeypatch.setattr(
        "smelt.pipeline.extract_webpage",
        lambda url: Extracted(title=url, text="an automation pipeline", meta={}),
    )
    export = tmp_path / "list.txt"
    export.write_text("\n".join(f"https://example.com/{i}" for i in range(20)), encoding="utf-8")

    outcome = ingest(from_urls(export), Config(staging_dir=tmp_path / "staging"), limit=5)
    assert outcome.imported == 5
