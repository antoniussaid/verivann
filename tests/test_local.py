import zipfile

import httpx

from verivann import feeds, watchfolder
from verivann.adapters.local import extract_epub, extract_file, extract_image
from verivann.config import Config
from verivann.pipeline import run


def test_an_image_without_ocr_says_so_instead_of_lying(monkeypatch, tmp_path):
    monkeypatch.setattr("verivann.adapters.vision.ocr_available", lambda: False)
    shot = tmp_path / "screenshot.png"
    shot.write_bytes(b"\x89PNG\r\n\x1a\n")

    extracted = extract_image(shot)
    assert "no OCR available" in extracted.text
    assert extracted.meta["ocr"] is False


def test_a_screenshot_becomes_a_routed_note(monkeypatch, tmp_path):
    monkeypatch.setattr("verivann.adapters.vision.ocr_available", lambda: True)
    monkeypatch.setattr(
        "verivann.adapters.vision.ocr_image",
        lambda path: "Self-hosted agent architecture\nlocal-first automation beats the cloud",
    )
    shot = tmp_path / "shot.png"
    shot.write_bytes(b"\x89PNG\r\n\x1a\n")

    result = run("file", ref=str(shot), config=Config(staging_dir=tmp_path))
    assert result.event.routing.domain == "research"
    assert "Self-hosted agent architecture" in result.event.extracted.title


def test_audio_without_whisper_is_honest(monkeypatch, tmp_path):
    monkeypatch.delenv("VERIVANN_WHISPER_MODEL", raising=False)
    memo = tmp_path / "memo.m4a"
    memo.write_bytes(b"\x00")

    extracted = extract_file(memo)
    assert "transcription is off" in extracted.text
    assert extracted.meta["has_transcript"] is False


def test_a_voice_memo_is_transcribed_and_routed(monkeypatch, tmp_path):
    monkeypatch.setenv("VERIVANN_WHISPER_MODEL", "base")
    monkeypatch.setattr(
        "verivann.adapters.transcribe.transcribe_file",
        lambda path: ("Idea: route intake by open questions, not folders.", "en"),
    )
    memo = tmp_path / "memo.m4a"
    memo.write_bytes(b"\x00")

    extracted = extract_file(memo)
    assert "open questions" in extracted.text
    assert extracted.meta["transcript_source"] == "whisper"


def test_an_epub_is_just_a_zip_of_html(tmp_path):
    book = tmp_path / "book.epub"
    with zipfile.ZipFile(book, "w") as z:
        z.writestr("ch1.xhtml", "<html><title>On Sovereignty</title><body><p>Own your infrastructure.</p></body></html>")

    extracted = extract_epub(book)
    assert extracted.title == "On Sovereignty"
    assert "Own your infrastructure." in extracted.text


def test_a_pdf_without_a_reader_says_what_to_install(monkeypatch, tmp_path):
    monkeypatch.setattr("verivann.adapters.local._pdf_via_poppler", lambda p: None)
    monkeypatch.setattr("verivann.adapters.local._pdf_via_pypdf", lambda p: None)
    pdf = tmp_path / "paper.pdf"
    pdf.write_bytes(b"%PDF-1.4")

    extracted = extract_file(pdf)
    assert "pip install pypdf" in extracted.text
    assert extracted.meta["read"] is False


def test_a_folder_digests_only_what_is_new(monkeypatch, tmp_path):
    monkeypatch.setattr("verivann.adapters.vision.ocr_available", lambda: True)
    monkeypatch.setattr("verivann.adapters.vision.ocr_image", lambda p: f"text of {p.name} about agents")

    folder = tmp_path / "shots"
    folder.mkdir()
    (folder / "a.png").write_bytes(b"\x89PNG")
    (folder / "b.png").write_bytes(b"\x89PNG")
    (folder / "notes.doc").write_bytes(b"x")  # unsupported -> ignored
    config = Config(staging_dir=tmp_path / "staging")

    first = watchfolder.run_once(folder, config)
    assert len(first) == 2
    assert watchfolder.run_once(folder, config) == []  # nothing new the second time

    (folder / "c.png").write_bytes(b"\x89PNG")
    assert len(watchfolder.run_once(folder, config)) == 1


def test_the_folder_is_never_modified(monkeypatch, tmp_path):
    monkeypatch.setattr("verivann.adapters.vision.ocr_available", lambda: True)
    monkeypatch.setattr("verivann.adapters.vision.ocr_image", lambda p: "some text about automation")
    folder = tmp_path / "shots"
    folder.mkdir()
    (folder / "a.png").write_bytes(b"\x89PNG")

    watchfolder.run_once(folder, Config(staging_dir=tmp_path / "staging"))
    assert [p.name for p in folder.iterdir()] == ["a.png"]  # still there, untouched


# ---------- feeds ----------

_RSS = """<?xml version="1.0"?>
<rss version="2.0"><channel>
  <title>A Feed</title>
  <item><title>Local-first agents</title><link>https://example.com/a</link><guid>a</guid></item>
  <item><title>Celebrity gossip</title><link>https://example.com/b</link><guid>b</guid></item>
</channel></rss>"""


class _FeedResp:
    content = _RSS.encode()

    def raise_for_status(self):
        return None


def test_rss_is_parsed_without_a_dependency(monkeypatch):
    monkeypatch.setattr(httpx, "get", lambda *a, **k: _FeedResp())
    title, items = feeds.fetch("https://example.com/rss")
    assert title == "A Feed"
    assert [i.link for i in items] == ["https://example.com/a", "https://example.com/b"]


def _feed_pages(monkeypatch):
    from verivann.schema import Extracted

    pages = {
        "https://example.com/a": Extracted(
            title="Local-first agents",
            text="self-hosted local-first agent automation architecture research sovereignty",
        ),
        "https://example.com/b": Extracted(title="Celebrity gossip", text="x"),  # too thin -> dropped
    }
    monkeypatch.setattr(httpx, "get", lambda *a, **k: _FeedResp())
    monkeypatch.setattr("verivann.pipeline.extract_webpage", lambda url: pages[url])


def test_an_untrained_filter_admits_it_instead_of_pretending(monkeypatch, tmp_path):
    _feed_pages(monkeypatch)
    config = Config(staging_dir=tmp_path)
    feeds.add("https://example.com/rss", config)

    result = feeds.run(config)[0]
    assert result.seen == 2
    assert result.filter == "untrained"
    assert result.trained is False
    # The thin item is still proposed as a drop and never surfaces…
    assert [p.title for p in result.passed] == ["Local-first agents"]
    assert feeds.run(config) == []  # already read -> nothing new


def test_a_trained_filter_uses_what_you_keep(monkeypatch, tmp_path):
    from verivann.library import record_feedback
    from verivann.pipeline import run as digest

    config = Config(staging_dir=tmp_path)
    # Teach it: three verdicts, all against crypto-style material.
    for i in range(3):
        dropped = digest("text", ref="text", text=f"crypto memecoin pump hype {i}", config=config)
        record_feedback(dropped.event.id, "dropped", tmp_path)
    kept = digest("text", ref="text", text="local-first self-hosted agent sovereignty", config=config)
    record_feedback(kept.event.id, "kept", tmp_path)

    _feed_pages(monkeypatch)
    feeds.add("https://example.com/rss", config)
    result = feeds.run(config)[0]

    assert result.filter == "learned"
    assert result.trained is True
    assert [p.title for p in result.passed] == ["Local-first agents"]
