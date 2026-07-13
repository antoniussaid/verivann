"""Reddit adapter — post + top comments via the public JSON endpoint.

Reddit is a JS app; its raw HTML carries little content. Appending `.json` to a
post URL returns the post and its comment tree (public, read-only, no auth, no
extra dependency). We structure the post body + top comments. Best-effort: any
failure returns a minimal fallback so the pipeline never breaks.
"""

from __future__ import annotations

from urllib.parse import urlparse

from ..schema import Extracted

# A browser-like UA + old.reddit.com give the best odds against Reddit's
# anti-bot gate. Access is still environmental (IP/rate); on failure we fall back.
_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)
_MAX_COMMENTS = 15


def extract_reddit(url: str) -> Extracted:
    try:
        import httpx
    except ImportError:
        return _fallback(url, "httpx not installed")

    path = urlparse(url).path.rstrip("/")
    json_url = f"https://old.reddit.com{path}.json"
    try:
        resp = httpx.get(json_url, headers={"user-agent": _UA}, follow_redirects=True, timeout=20.0)
        resp.raise_for_status()
        data = resp.json()
    except Exception as exc:  # noqa: BLE001 - network is expected to fail sometimes
        return _fallback(url, f"fetch failed: {exc}")

    try:
        post = data[0]["data"]["children"][0]["data"]
    except (KeyError, IndexError, TypeError):
        return _fallback(url, "unexpected JSON shape")

    title = post.get("title", "") or url
    body = (post.get("selftext") or "").strip()

    comments: list[str] = []
    try:
        for child in data[1]["data"]["children"][:_MAX_COMMENTS]:
            c = child.get("data", {})
            text = (c.get("body") or "").strip()
            if text and c.get("author") != "AutoModerator":
                comments.append(f"[{c.get('score', 0)}] {c.get('author', '?')}: {text}")
    except (KeyError, IndexError, TypeError):
        pass

    parts = [body] if body else []
    if comments:
        parts.append("--- Top comments ---\n" + "\n\n".join(comments))
    text = (f"{title}\n\n" + "\n\n".join(parts)).strip() if parts else title

    meta = {
        "url": url,
        "subreddit": post.get("subreddit"),
        "score": post.get("score"),
        "num_comments": post.get("num_comments"),
        "comments_captured": len(comments),
    }
    return Extracted(title=title, text=text[:20000], meta=meta)


def _fallback(url: str, error: str) -> Extracted:
    return Extracted(
        title=url,
        text=f"[Reddit extraction failed — process manually]\nURL: {url}\nReason: {error}",
        meta={"url": url, "error": error, "fallback": True},
    )
