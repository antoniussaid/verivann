"""Stable, filesystem-safe artifact names: <date>-<platform>-<slug>-<hash>."""

from __future__ import annotations

import hashlib
import re

_SLUG_RE = re.compile(r"[^a-z0-9]+")


def _slug(text: str, max_len: int = 40) -> str:
    slug = _SLUG_RE.sub("-", (text or "").lower()).strip("-")
    return (slug[:max_len].strip("-")) or "untitled"


def artifact_stem(date: str, platform: str, title: str, ref: str) -> str:
    short = hashlib.sha1(f"{ref}|{title}".encode()).hexdigest()[:8]
    return f"{date}-{platform}-{_slug(title)}-{short}"
