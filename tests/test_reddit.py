import httpx

from smelt.adapters.reddit import extract_reddit


class _FakeResp:
    def __init__(self, payload):
        self._p = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self._p


_CANNED = [
    {"data": {"children": [{"data": {
        "title": "Best self-hosted note app?",
        "selftext": "Looking for something local-first.",
        "subreddit": "selfhosted", "score": 42, "num_comments": 2,
    }}]}},
    {"data": {"children": [
        {"data": {"body": "Try Obsidian.", "author": "alice", "score": 10}},
        {"data": {"body": "AutoMod note", "author": "AutoModerator", "score": 1}},
        {"data": {"body": "Logseq is great.", "author": "bob", "score": 7}},
    ]}},
]


def test_reddit_parses_post_and_comments(monkeypatch):
    monkeypatch.setattr(httpx, "get", lambda *a, **k: _FakeResp(_CANNED))
    ex = extract_reddit("https://www.reddit.com/r/selfhosted/comments/x/best/")
    assert ex.title == "Best self-hosted note app?"
    assert ex.meta["subreddit"] == "selfhosted"
    assert ex.meta["comments_captured"] == 2  # AutoModerator dropped
    assert "Obsidian" in ex.text and "Logseq" in ex.text
    assert "AutoMod note" not in ex.text
