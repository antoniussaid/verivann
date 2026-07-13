"""Webpage adapter — fetch a URL, pull title + readable text.

It also pulls two things a reader never sees but a security scan needs
(security.py): the text a page hides from the human eye (white-on-white,
`display:none`, zero-size type, off-screen positioning) and the page's outbound
links. Text that only a machine will read is not editorial content — it exists for
a reason, and that reason belongs in the note.

Degrades gracefully: on any network/parse failure it still returns a minimal
Extracted carrying the URL and the error, so the pipeline never crashes and the
visitor gets a note they can process manually.
"""

from __future__ import annotations

import re

from ..schema import Extracted

_UA = "Mozilla/5.0 (compatible; verivann/0.1; +https://antonius.app)"

# Inline styles that put text outside a human's field of view.
_HIDDEN_STYLE = re.compile(
    r"display\s*:\s*none|visibility\s*:\s*hidden|opacity\s*:\s*0(\.0+)?\b"
    r"|font-size\s*:\s*0|text-indent\s*:\s*-\d{3,}|left\s*:\s*-\d{4,}|clip\s*:\s*rect\(0",
    re.IGNORECASE,
)
_HIDDEN_CLASS = re.compile(r"\b(sr-only|visually-hidden|screen-reader|hidden|invisible)\b", re.IGNORECASE)
_MAX_HIDDEN = 4000
_MAX_LINKS = 6000


def extract_webpage(url: str) -> Extracted:
    try:
        import httpx  # imported lazily so the core runs without it installed
    except ImportError:
        return _fallback(url, "httpx not installed")

    try:
        resp = httpx.get(url, headers={"user-agent": _UA}, follow_redirects=True, timeout=20.0)
        resp.raise_for_status()
        html = resp.text
    except Exception as exc:  # noqa: BLE001 - network errors are expected, fail soft
        return _fallback(url, f"fetch failed: {exc}")

    title, text, hidden, links = _parse(html)
    return Extracted(
        title=title or url,
        text=text,
        meta={
            "url": url,
            "status": resp.status_code,
            "chars": len(text),
            "hidden_text": hidden or None,
            "links": links or None,
        },
    )


def _parse(html: str) -> tuple[str, str, str, str]:
    try:
        from bs4 import BeautifulSoup
    except ImportError:
        return "", "", "", ""

    soup = BeautifulSoup(html, "html.parser")
    title = (soup.title.string.strip() if soup.title and soup.title.string else "")

    links = " ".join(
        a.get("href", "") for a in soup.find_all("a", href=True)[:200]
    )[:_MAX_LINKS]

    hidden = _hidden_text(soup)

    for tag in soup(["script", "style", "noscript", "nav", "footer", "header", "aside"]):
        tag.decompose()
    # Prefer the main article body when present.
    root = soup.find("article") or soup.find("main") or soup.body or soup
    text = "\n".join(
        line for line in (p.get_text(" ", strip=True) for p in root.find_all(["p", "h1", "h2", "h3", "li"]))
        if line
    )
    return title, text.strip(), hidden, links


def _hidden_text(soup) -> str:
    """Text the page keeps out of sight. Collected before the tree is stripped."""
    out: list[str] = []
    for tag in soup.find_all(style=_HIDDEN_STYLE):
        out.append(tag.get_text(" ", strip=True))
    for tag in soup.find_all(class_=_HIDDEN_CLASS):
        out.append(tag.get_text(" ", strip=True))
    for tag in soup.find_all(attrs={"aria-hidden": "true"}):
        out.append(tag.get_text(" ", strip=True))
    for tag in soup.find_all(attrs={"hidden": True}):
        out.append(tag.get_text(" ", strip=True))
    return " ".join(t for t in out if t)[:_MAX_HIDDEN].strip()


def _fallback(url: str, error: str) -> Extracted:
    return Extracted(
        title=url,
        text=f"[Extraction failed — process manually]\nURL: {url}\nReason: {error}",
        meta={"url": url, "error": error, "fallback": True},
    )
