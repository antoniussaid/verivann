"""Textdump adapter - accept arbitrary pasted text.

The simplest, most robust intake: no network, no platform. Always available,
so the system is useful even when a platform can't be extracted.
"""

from __future__ import annotations

from ..schema import Extracted


def extract_text(text: str) -> Extracted:
    text = (text or "").strip()
    # Title = first non-empty line, trimmed to a sane length.
    first_line = next((ln.strip() for ln in text.splitlines() if ln.strip()), "")
    title = (first_line[:80] + "…") if len(first_line) > 80 else first_line
    return Extracted(title=title or "Untitled text", text=text, meta={"chars": len(text)})
