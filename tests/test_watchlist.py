from verivann import watchlist
from verivann.config import Config
from verivann.schema import Extracted


class _Page:
    """A page that can be edited between reads — like a real one."""

    def __init__(self, text):
        self.text = text
        self.reads = 0

    def __call__(self, url):
        self.reads += 1
        return Extracted(title="A news story", text=self.text, meta={"url": url})


def test_a_baseline_is_taken_when_you_start_watching(monkeypatch, tmp_path):
    page = _Page("The minister said A.\nThe cost is 5 million.")
    monkeypatch.setattr("verivann.watchlist.extract_webpage", page, raising=False)
    monkeypatch.setattr("verivann.adapters.extract_webpage", page)

    config = Config(staging_dir=tmp_path)
    entry = watchlist.add("https://news.example.com/story?utm_source=x", config)

    assert entry.url == "https://news.example.com/story"  # canonicalized
    assert entry.changes == 0
    assert watchlist.run(config) == []  # unchanged -> silence


def test_a_silent_edit_is_caught_and_lands_in_the_note(monkeypatch, tmp_path):
    page = _Page("The minister said A.\nThe cost is 5 million.")
    monkeypatch.setattr("verivann.adapters.extract_webpage", page)
    monkeypatch.setattr("verivann.pipeline.extract_webpage", page)

    config = Config(staging_dir=tmp_path)
    watchlist.add("https://news.example.com/story", config)

    page.text = "The minister said B.\nThe cost is 12 million."  # quietly rewritten
    moved = watchlist.run(config)

    assert len(moved) == 1
    url, patch, lines = moved[0]
    assert "-The cost is 5 million." in patch
    assert "+The cost is 12 million." in patch
    assert lines == 4

    note = (tmp_path / "notes").glob("*.md")
    text = next(note).read_text(encoding="utf-8")
    assert "## Changed since you read it" in text
    assert "+The minister said B." in text


def test_a_failed_fetch_is_not_reported_as_a_change(monkeypatch, tmp_path):
    page = _Page("Original text.")
    monkeypatch.setattr("verivann.adapters.extract_webpage", page)
    config = Config(staging_dir=tmp_path)
    watchlist.add("https://news.example.com/story", config)

    def broken(url):
        return Extracted(title=url, text="[Extraction failed]", meta={"fallback": True})

    monkeypatch.setattr("verivann.adapters.extract_webpage", broken)
    assert watchlist.run(config) == []  # never cry wolf over a network error


def test_the_diff_is_bounded(monkeypatch):
    old = "\n".join(f"line {i}" for i in range(200))
    new = "\n".join(f"changed {i}" for i in range(200))
    patch, lines = watchlist.diff(old, new)
    assert lines == 400
    assert len(patch.splitlines()) <= 41
    assert "more changed line(s)" in patch


def test_removing_stops_the_watch(monkeypatch, tmp_path):
    page = _Page("text")
    monkeypatch.setattr("verivann.adapters.extract_webpage", page)
    config = Config(staging_dir=tmp_path)
    watchlist.add("https://news.example.com/story", config)

    assert watchlist.remove("https://news.example.com/story", config) is True
    assert watchlist.watched(config) == []
