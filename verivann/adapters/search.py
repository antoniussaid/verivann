"""Going out to look — the only adapter that fetches something nobody asked for.

Every other adapter reads what the user handed it. This one goes hunting: it takes
a query and comes back with links, so that `counter.py` can fetch the other side of
an argument instead of merely noting that one is missing.

Two backends, both opt-in, neither of them a scraper:

    SearXNG   VERIVANN_SEARCH_URL=http://localhost:8888   — self-hosted, no key, no terms
              to violate, and the results never touch a third party's log.
    Brave     VERIVANN_SEARCH_KEY=...                     — a real API with a free tier.

We do not scrape Google or Bing. Their terms forbid it, and a tool whose selling
point is honesty cannot start by breaking someone's rules quietly.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

import httpx

_UA = "Mozilla/5.0 (compatible; verivann/0.1; +https://antonius.app)"
_TIMEOUT = 20.0


@dataclass
class Result:
    title: str
    url: str
    snippet: str = ""


def backend() -> str:
    if os.environ.get("VERIVANN_SEARCH_URL", "").strip():
        return "searxng"
    if os.environ.get("VERIVANN_SEARCH_KEY", "").strip():
        return "brave"
    return ""


def available() -> bool:
    return bool(backend())


def search(query: str, limit: int = 5) -> list[Result]:
    """Links for a query. Empty list on any failure — searching is never load-bearing."""
    which = backend()
    try:
        if which == "searxng":
            return _searxng(query, limit)
        if which == "brave":
            return _brave(query, limit)
    except Exception:  # noqa: BLE001 - a dead search engine is not a crash
        return []
    return []


def _searxng(query: str, limit: int) -> list[Result]:
    base = os.environ["VERIVANN_SEARCH_URL"].rstrip("/")
    resp = httpx.get(
        f"{base}/search",
        params={"q": query, "format": "json", "safesearch": 0},
        headers={"user-agent": _UA},
        timeout=_TIMEOUT,
    )
    resp.raise_for_status()
    items = resp.json().get("results", [])[:limit]
    return [
        Result(title=i.get("title", ""), url=i.get("url", ""), snippet=i.get("content", ""))
        for i in items
        if i.get("url")
    ]


def _brave(query: str, limit: int) -> list[Result]:
    resp = httpx.get(
        "https://api.search.brave.com/res/v1/web/search",
        params={"q": query, "count": limit},
        headers={
            "accept": "application/json",
            "x-subscription-token": os.environ["VERIVANN_SEARCH_KEY"],
            "user-agent": _UA,
        },
        timeout=_TIMEOUT,
    )
    resp.raise_for_status()
    items = resp.json().get("web", {}).get("results", [])[:limit]
    return [
        Result(title=i.get("title", ""), url=i.get("url", ""), snippet=i.get("description", ""))
        for i in items
        if i.get("url")
    ]
