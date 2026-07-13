from smelt.adapters import archive
from smelt.adapters.archive import archive_all, archive_url, enabled, formats


def test_archive_disabled_by_default(monkeypatch, tmp_path):
    monkeypatch.delenv("SMELT_ARCHIVE", raising=False)
    assert enabled() is False
    assert archive_url("https://example.com", tmp_path, "stem") is None
    assert archive_all("https://example.com", tmp_path, "stem") == {}


def test_archive_enabled_but_no_tool(monkeypatch, tmp_path):
    monkeypatch.setenv("SMELT_ARCHIVE", "1")
    # No monolith/single-file on PATH in CI -> returns None, never raises.
    monkeypatch.setattr(archive, "available_tool", lambda: None)
    assert archive_url("https://example.com", tmp_path, "stem") is None


def test_formats_default_to_html_and_reject_junk(monkeypatch):
    monkeypatch.delenv("SMELT_ARCHIVE_FORMATS", raising=False)
    assert formats() == ["html"]
    monkeypatch.setenv("SMELT_ARCHIVE_FORMATS", "png, pdf ,exe")
    assert formats() == ["png", "pdf"]
    monkeypatch.setenv("SMELT_ARCHIVE_FORMATS", "nonsense")
    assert formats() == ["html"]


def test_archive_all_collects_every_available_format(monkeypatch, tmp_path):
    monkeypatch.setenv("SMELT_ARCHIVE", "1")
    monkeypatch.setenv("SMELT_ARCHIVE_FORMATS", "html,pdf,png")
    monkeypatch.setattr(archive, "chrome_binary", lambda: "chrome")

    def fake_run(cmd, out, timeout=120):
        out.write_text("x", encoding="utf-8")  # pretend the tool produced the file
        return out

    monkeypatch.setattr(archive, "available_tool", lambda: "monolith")
    monkeypatch.setattr(archive, "_run", fake_run)

    made = archive_all("https://example.com", tmp_path, "stem")
    assert set(made) == {"html", "pdf", "png"}
    assert made["pdf"].endswith("stem.pdf")


def test_archive_all_skips_pdf_png_without_a_browser(monkeypatch, tmp_path):
    monkeypatch.setenv("SMELT_ARCHIVE", "1")
    monkeypatch.setenv("SMELT_ARCHIVE_FORMATS", "pdf,png")
    monkeypatch.setattr(archive, "chrome_binary", lambda: None)
    assert archive_all("https://example.com", tmp_path, "stem") == {}
