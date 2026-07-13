"""The commit gate: `accept` is the one place a proposal becomes a commitment.

It has to get three things right — resolve the proposal into a decision, stamp who
committed it, and never destroy what is already in the user's vault.
"""

import re
from pathlib import Path

from verivann.accept import (
    _note_id_of,
    _resolve,
    _unclobbered,
    accept,
    accept_all,
    default_target,
)
from verivann.config import Config
from verivann.pipeline import run


def _stage(tmp_path, text="A thoughtful piece about local-first software and why it matters."):
    config = Config(staging_dir=tmp_path / "staging")
    result = run("text", ref="text", text=text, config=config)
    return config, result.event.id


# --- End-to-end: stage a real note, then accept it. -------------------------------

def test_accept_resolves_the_proposal_and_stamps_the_decision(tmp_path):
    config, note_id = _stage(tmp_path)
    vault = tmp_path / "vault"

    accepted = accept(note_id, vault, config)

    assert accepted is not None
    written = accepted.target.read_text(encoding="utf-8")
    assert re.search(r"^action:\s*\w+", written, re.MULTILINE)
    assert "proposed_action:" not in written           # the proposal is resolved away
    assert re.search(r"^accepted_at:\s*\d{4}-\d{2}-\d{2}", written, re.MULTILINE)
    assert "accepted_by: human" in written             # who committed it is on record
    assert "proposal only — never committed here" not in written


def test_accept_returns_none_for_an_unknown_id(tmp_path):
    config, _ = _stage(tmp_path)
    assert accept("does-not-exist", tmp_path / "vault", config) is None


def test_accept_returns_none_when_the_staged_file_is_gone(tmp_path):
    config, note_id = _stage(tmp_path)
    from verivann.library import note_row

    Path(note_row(note_id, config.staging_dir)["note_path"]).unlink()

    assert accept(note_id, tmp_path / "vault", config) is None


def test_re_accepting_the_same_note_updates_in_place(tmp_path):
    config, note_id = _stage(tmp_path)
    vault = tmp_path / "vault"

    first = accept(note_id, vault, config)
    second = accept(note_id, vault, config)

    assert first.target == second.target                       # same file, not a copy
    assert len(list(vault.glob("*.md"))) == 1


def test_accept_never_clobbers_a_different_note_with_the_same_name(tmp_path):
    config, note_id = _stage(tmp_path)
    vault = tmp_path / "vault"
    vault.mkdir()

    # A different note already living in the vault under the exact filename we'll write.
    from verivann.library import note_row

    name = Path(note_row(note_id, config.staging_dir)["note_path"]).name
    stranger = vault / name
    stranger.write_text("---\nid: some-other-note\n---\nSomeone else's note.", encoding="utf-8")

    accepted = accept(note_id, vault, config)

    assert stranger.read_text(encoding="utf-8").endswith("Someone else's note.")  # untouched
    assert accepted.target != stranger                          # ours went somewhere else
    assert accepted.target.exists()


def test_accept_all_skips_the_misses(tmp_path):
    config, note_id = _stage(tmp_path)
    out = accept_all([note_id, "nope"], tmp_path / "vault", config)
    assert len(out) == 1 and out[0].note_id == note_id


# --- _resolve: frontmatter-scoped, always stamps. ---------------------------------

_NOTE = (
    "---\n"
    "id: abc123\n"
    "proposed_action: task\n"
    "domain: research\n"
    "---\n\n"
    "# Title\n\n"
    "- Proposed action: task  _(proposal only — never committed here)_\n"
)


def test_resolve_turns_proposal_into_action():
    out = _resolve(_NOTE)
    assert re.search(r"^action: task$", out, re.MULTILINE)
    assert "proposed_action:" not in out


def test_resolve_stamps_acceptance():
    out = _resolve(_NOTE)
    assert re.search(r"^accepted_at: \d{4}-\d{2}-\d{2}$", out, re.MULTILINE)
    assert re.search(r"^accepted_by: human$", out, re.MULTILINE)


def test_resolve_updates_the_proposal_marker_in_the_body():
    out = _resolve(_NOTE)
    assert "proposal only — never committed here" not in out
    assert re.search(r"_\(accepted by you on \d{4}-\d{2}-\d{2}\)_", out)


def test_resolve_does_not_touch_an_action_line_in_the_body():
    """A note whose body mentions `action: foo` must not have it rewritten."""
    note = "---\nid: x\nproposed_action: note\n---\n\nRun this: action: delete everything\n"
    out = _resolve(note)
    assert "action: delete everything" in out            # body untouched
    assert re.search(r"^action: note$", out, re.MULTILINE)  # frontmatter resolved


def test_resolve_stamps_even_without_a_proposed_action():
    note = "---\nid: y\ndomain: research\n---\n\nBody.\n"
    out = _resolve(note)
    assert "accepted_by: human" in out
    assert re.search(r"^action: note$", out, re.MULTILINE)  # a decision defaults to note


def test_resolve_prepends_frontmatter_when_there_is_none():
    out = _resolve("Just a bare body, no frontmatter.\n")
    assert out.startswith("---\n")
    assert "accepted_by: human" in out
    assert "Just a bare body" in out


def test_resolve_is_idempotent():
    once = _resolve(_NOTE)
    twice = _resolve(once)
    assert twice.count("accepted_by: human") == 1       # not double-stamped


# --- _unclobbered / _note_id_of. --------------------------------------------------

def test_note_id_is_read_from_frontmatter():
    assert _note_id_of("---\nid: hello-42\n---\nbody") == "hello-42"
    assert _note_id_of("no id here") == ""


def test_unclobbered_returns_a_free_path_unchanged(tmp_path):
    target = tmp_path / "note.md"
    assert _unclobbered(target, "---\nid: a\n---\n") == target


def test_unclobbered_reuses_the_file_of_the_same_note(tmp_path):
    target = tmp_path / "note.md"
    target.write_text("---\nid: same\n---\nold", encoding="utf-8")
    assert _unclobbered(target, "---\nid: same\n---\nnew") == target


def test_unclobbered_suffixes_a_colliding_different_note(tmp_path):
    target = tmp_path / "note.md"
    target.write_text("---\nid: theirs\n---\n", encoding="utf-8")
    chosen = _unclobbered(target, "---\nid: mine\n---\n")
    assert chosen == tmp_path / "note-2.md"


# --- default_target. --------------------------------------------------------------

def test_default_target_reads_the_env(monkeypatch, tmp_path):
    monkeypatch.setenv("VERIVANN_ACCEPT_DIR", str(tmp_path / "vault"))
    assert default_target() == tmp_path / "vault"


def test_default_target_is_none_without_the_env(monkeypatch):
    monkeypatch.delenv("VERIVANN_ACCEPT_DIR", raising=False)
    assert default_target() is None
