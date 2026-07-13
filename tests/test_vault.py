"""Data sovereignty: back it up, export it readable, erase it clean — losing nothing
you meant to keep and leaving nothing you meant to erase.
"""

import zipfile
from pathlib import Path

from typer.testing import CliRunner

from verivann.cli import app
from verivann.config import Config
from verivann.library import _connect, count, purge_source
from verivann.pipeline import run
from verivann.vault import backup, erase, export_notes


def _stage(staging, text):
    return run("text", ref="text", text=text, config=Config(staging_dir=staging)).event.id


def test_backup_bundles_the_whole_library(tmp_path):
    staging = tmp_path / "s"
    _stage(staging, "A note about local-first software and ownership.")
    (staging / ".subs" / "scratch").mkdir(parents=True)  # transient work dir
    (staging / ".subs" / "scratch" / "junk.tmp").write_text("temp", encoding="utf-8")

    out = backup(staging, tmp_path / "mybackup")

    assert out.suffix == ".zip" and out.is_file()
    names = zipfile.ZipFile(out).namelist()
    assert "library.db" in names
    assert any(n.startswith("notes/") and n.endswith(".md") for n in names)
    assert not any(n.startswith(".subs/") for n in names)         # transient excluded
    assert not any(n.endswith(("-wal", "-shm")) for n in names)   # sidecars excluded


def test_export_notes_copies_readable_markdown(tmp_path):
    staging = tmp_path / "s"
    _stage(staging, "First piece about note-taking systems.")
    _stage(staging, "Second, unrelated piece about spaced repetition and memory.")

    n = export_notes(staging, tmp_path / "out")

    assert n == 2
    copied = list((tmp_path / "out").glob("*.md"))
    assert len(copied) == 2
    assert "---" in copied[0].read_text(encoding="utf-8")  # real note frontmatter


def test_export_notes_on_an_empty_library_is_zero(tmp_path):
    assert export_notes(tmp_path / "nothing", tmp_path / "out") == 0


def test_erase_removes_everything_and_counts_it(tmp_path):
    staging = tmp_path / "s"
    _stage(staging, "Something to forget.")
    assert count(staging) == 1

    result = erase(staging)

    assert result["notes"] == 1 and result["files"] > 0
    assert not staging.exists()
    assert count(staging) == 0  # next connect starts from an empty slate


def test_erase_on_a_missing_dir_is_a_no_op(tmp_path):
    assert erase(tmp_path / "never-existed") == {"notes": 0, "files": 0}


def test_purge_source_is_surgical(tmp_path):
    """One source erased to nothing; another source left entirely intact."""
    staging = tmp_path / "s"
    doomed = _stage(staging, "A piece from the source we will erase.")
    kept = _stage(staging, "A piece from a source we will keep, quite different in content.")

    con = _connect(staging)
    try:
        con.execute("UPDATE notes SET source_key = 'src:doomed' WHERE id = ?", (doomed,))
        con.execute("UPDATE notes SET source_key = 'src:kept' WHERE id = ?", (kept,))
        # Rows owned by the doomed note, to prove the cascade reaches them.
        con.execute("INSERT INTO feedback (note_id, verdict) VALUES (?, 'kept')", (doomed,))
        con.execute("INSERT INTO signals (note_id, kind, at) VALUES (?, 'open', '2026-01-01')", (doomed,))
        con.execute("INSERT INTO sources (key, label) VALUES ('src:doomed', 'Doomed')")
        con.commit()
        doomed_path = con.execute("SELECT note_path FROM notes WHERE id = ?", (doomed,)).fetchone()[0]
    finally:
        con.close()

    assert Path(doomed_path).is_file()

    result = purge_source("src:doomed", staging)

    assert result["notes"] == 1 and result["files"] >= 1
    assert not Path(doomed_path).is_file()          # the note file is gone

    con = _connect(staging)
    try:
        assert con.execute("SELECT COUNT(*) FROM notes WHERE id = ?", (doomed,)).fetchone()[0] == 0
        assert con.execute("SELECT COUNT(*) FROM notes WHERE id = ?", (kept,)).fetchone()[0] == 1
        assert con.execute("SELECT COUNT(*) FROM feedback WHERE note_id = ?", (doomed,)).fetchone()[0] == 0
        assert con.execute("SELECT COUNT(*) FROM signals WHERE note_id = ?", (doomed,)).fetchone()[0] == 0
        assert con.execute("SELECT COUNT(*) FROM sources WHERE key = 'src:doomed'").fetchone()[0] == 0
    finally:
        con.close()


def test_purge_source_that_does_not_exist_is_a_no_op(tmp_path):
    staging = tmp_path / "s"
    _stage(staging, "Only note.")
    result = purge_source("src:ghost", staging)
    assert result == {"source": "src:ghost", "notes": 0, "files": 0}
    assert count(staging) == 1  # nothing collateral was touched


# --- CLI: the destructive command is gated by a confirmation and backs up first. ---

def _default_staging():
    return Path("data/staging")  # what Config.load() uses when nothing overrides it


def test_cli_purge_all_erases_after_confirmation(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    _stage(_default_staging(), "A note that will be wiped.")
    result = CliRunner().invoke(app, ["purge", "--all", "--no-backup"], input="y\n")
    assert result.exit_code == 0, result.output
    assert "Erased" in result.output
    assert count(_default_staging()) == 0


def test_cli_purge_declined_touches_nothing(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    _stage(_default_staging(), "A note that must survive a declined purge.")
    result = CliRunner().invoke(app, ["purge", "--all"], input="n\n")
    assert result.exit_code == 0, result.output
    assert "Cancelled" in result.output
    assert count(_default_staging()) == 1  # still there


def test_cli_purge_writes_a_safety_backup_first(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    _stage(_default_staging(), "A note worth a safety net.")
    result = CliRunner().invoke(app, ["purge", "--all", "--yes"])  # backup on by default
    assert result.exit_code == 0, result.output
    assert "Safety backup" in result.output
    assert Path("verivann-backup-before-purge.zip").is_file()
    assert count(_default_staging()) == 0


def test_cli_purge_requires_a_target(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    result = CliRunner().invoke(app, ["purge"])  # neither --source nor --all
    assert result.exit_code == 1
    assert "exactly one" in result.output
