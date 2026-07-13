"""An editor, not a feed reader.

A feed reader shows you everything and calls the backlog your fault. Smelt reads
the feed *for* you: every new item is digested and routed, the learned profile
(relevance.py) scores it against what you actually keep, and you are shown **only
what got through**. The rest is staged, counted, and left alone.

    smelt feed add https://example.com/rss
    smelt feed run                  → "18 items, 3 got through"
    smelt feed list                 → the pass rate of every feed you follow

The pass rate is the interesting number. A feed that produces 40 items a week and
passes none of them is not a feed you follow — it is a habit, and now you can see it.

RSS and Atom, parsed with the standard library. No feedparser, no dependency.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from xml.etree import ElementTree

import httpx

from .config import Config

_UA = "Mozilla/5.0 (compatible; smelt/0.1; +https://antonius.app)"
_MAX_ITEMS = 25  # per feed per run — a bound, not a preference


@dataclass
class Item:
    guid: str
    title: str
    link: str


@dataclass
class Passed:
    title: str
    link: str
    domain: str
    confidence: float
    reason: str
    note_id: str


@dataclass
class Result:
    feed: str
    seen: int
    passed: list[Passed]
    filter: str = "untrained"  # "questions" | "learned" | "untrained"

    @property
    def rate(self) -> float:
        return round(len(self.passed) / self.seen, 2) if self.seen else 0.0

    @property
    def trained(self) -> bool:
        return self.filter != "untrained"


def fetch(url: str) -> tuple[str, list[Item]]:
    """(feed title, items). RSS or Atom — both are just XML with different names."""
    resp = httpx.get(url, headers={"user-agent": _UA}, follow_redirects=True, timeout=25.0)
    resp.raise_for_status()
    root = ElementTree.fromstring(resp.content)

    title = _text(root, ".//{*}channel/{*}title") or _text(root, "./{*}title") or url
    items: list[Item] = []
    # ElementTree's `{*}` wildcard works in find(), not in iter() — so match the
    # local name ourselves and stay namespace-agnostic (RSS and Atom both work).
    for node in root.iter():
        if _local(node.tag) not in ("item", "entry"):
            continue
        link = _text(node, "./{*}link") or _attr(node, "./{*}link", "href") or ""
        guid = _text(node, "./{*}guid") or _text(node, "./{*}id") or link
        item_title = _text(node, "./{*}title") or link
        if link:
            items.append(Item(guid=guid, title=_clean(item_title), link=link.strip()))
    return _clean(title), items[:_MAX_ITEMS]


def _local(tag) -> str:
    return str(tag).rsplit("}", 1)[-1]


def add(url: str, config: Config | None = None) -> str:
    config = config or Config.load()
    from .library import feed_add

    title, _ = fetch(url)
    feed_add(url, title, config.staging_dir)
    return title


def remove(url: str, config: Config | None = None) -> bool:
    config = config or Config.load()
    from .library import feed_remove

    return feed_remove(url, config.staging_dir)


def subscriptions(config: Config | None = None) -> list[dict]:
    config = config or Config.load()
    from .library import feed_rows

    return feed_rows(config.staging_dir)


def run(config: Config | None = None, lens: str | None = None) -> list[Result]:
    """Read every feed. Digest what is new. Report only what got through."""
    config = config or Config.load()
    from .library import feed_item_mark, feed_item_seen, feed_tally
    from .pipeline import run as digest
    from .questions import listing as open_questions
    from .relevance import load_profile

    profile = load_profile(config.staging_dir)
    has_questions = bool(config.llm.enabled and open_questions(config))
    mode = "questions" if has_questions else "learned" if profile.active else "untrained"

    results: list[Result] = []
    for feed in subscriptions(config):
        try:
            _, items = fetch(feed["url"])
        except Exception:  # noqa: BLE001 - a dead feed is not a crash
            continue

        seen = 0
        passed: list[Passed] = []
        for item in items:
            if feed_item_seen(item.guid, config.staging_dir):
                continue
            seen += 1
            feed_item_mark(item.guid, feed["url"], config.staging_dir)
            try:
                result = digest("url", ref=item.link, config=config, lens=lens)
            except Exception:  # noqa: BLE001 - one bad item must not stop the run
                continue
            if _gets_through(result, mode, profile):
                event = result.event
                passed.append(
                    Passed(
                        title=event.extracted.title,
                        link=item.link,
                        domain=event.routing.domain,
                        confidence=event.routing.confidence,
                        reason=event.routing.reason,
                        note_id=event.id,
                    )
                )
        feed_tally(feed["url"], seen, len(passed), config.staging_dir)
        if seen:
            results.append(
                Result(feed=feed["title"] or feed["url"], seen=seen, passed=passed, filter=mode)
            )
    return results


def _gets_through(result, mode: str, profile) -> bool:
    """The editorial decision — and an honest account of what it is based on.

    There are three regimes, and conflating them is how a filter becomes a lie:

      questions   You have open questions and a model to read against them. An item
                  passes if it advances one. This is a real editorial judgment.
      learned     No questions, but enough keep/drop verdicts to know your taste.
                  An item passes if it looks like what you keep.
      untrained   Neither. Smelt has NO basis for an editorial opinion, so it does
                  not fake one: everything that was not proposed as a drop comes
                  through, and the caller is told the filter is untrained.
    """
    event = result.event
    if event.decision.action == "drop":
        return False
    meta = event.extracted.meta or {}

    if mode == "questions":
        return bool(meta.get("questions"))
    if mode == "learned":
        text = f"{event.extracted.title}\n{event.extracted.text[:2000]}"
        return profile.score(text, event.routing.domain) > 0.1
    return True  # untrained: no opinion, no pretense


def _text(node, path: str) -> str:
    found = node.find(path)
    return (found.text or "").strip() if found is not None and found.text else ""


def _attr(node, path: str, attr: str) -> str:
    found = node.find(path)
    return (found.get(attr) or "").strip() if found is not None else ""


def _clean(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip()
