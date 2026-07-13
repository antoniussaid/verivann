"""One source, one identity.

Two things break identity in practice, and both showed up within an hour of real
use:

  * The same video arrives twice — once plain, once with `&t=78s` from a
    timestamp link — and becomes two notes.
  * A link copied out of Markdown arrives as `(https://…)`, so the "URL" carries
    a bracket and the note gets a garbage title.

So before anything is fetched or stored, a submitted string is cleaned and the
URL is canonicalized: tracking noise dropped, share forms normalized, position
markers removed. What is left is the source's identity — which is what dedup,
the library, and the keep/drop verdicts all key on.

Deliberately conservative: only *known* junk is stripped. An unknown query
parameter may be load-bearing (`?p=123`), so it stays.
"""

from __future__ import annotations

import re
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

# Params that never change WHAT the source is.
_JUNK_PARAMS = {
    "utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content", "utm_id",
    "fbclid", "gclid", "msclkid", "igshid", "igsh", "mc_cid", "mc_eid", "ref", "ref_src",
    "si", "feature", "spm", "share_id", "_branch_match_id", "sender_device",
    "is_from_webapp", "web_id", "pp",
    "t", "start", "time_continue", "at",  # a position in a video, not a different video
}

_TRAILING = " \t\r\n\"'`.,;:!?)]}>"
_LEADING = " \t\r\n\"'`([{<"


def clean_input(raw: str) -> str:
    """A pasted string, stripped of the punctuation that copying drags along."""
    text = (raw or "").strip()
    if "\n" in text or not re.match(r"^[\s\"'`([{<]*https?://", text, re.IGNORECASE):
        return text  # free text: leave it exactly as it is
    return text.lstrip(_LEADING).rstrip(_TRAILING)


def canonical_url(url: str) -> str:
    """The stable identity of a link: same source in, same string out."""
    url = clean_input(url)
    try:
        parts = urlsplit(url)
    except ValueError:
        return url
    if parts.scheme not in ("http", "https") or not parts.netloc:
        return url

    host = parts.netloc.lower()
    if host.startswith("www."):
        host = host[4:]
    path, query = parts.path, parts.query

    # Share forms of the same video.
    if host == "youtu.be" and len(path) > 1:
        video_id = path.lstrip("/").split("/")[0]
        host, path, query = "youtube.com", "/watch", f"v={video_id}"
    elif host in ("m.youtube.com", "music.youtube.com"):
        host = "youtube.com"
    elif host in ("m.facebook.com", "mobile.twitter.com", "vm.tiktok.com"):
        host = host.split(".", 1)[1]
    elif host == "x.com":
        host = "twitter.com"
    elif host.startswith(("old.reddit.com", "np.reddit.com")):
        host = "reddit.com"

    kept = [(k, v) for k, v in parse_qsl(query, keep_blank_values=True) if k.lower() not in _JUNK_PARAMS]
    path = path.rstrip("/") or "/"
    # Fragments are client-side; the only common exception is a hashbang route.
    fragment = parts.fragment if parts.fragment.startswith("!") else ""
    return urlunsplit((parts.scheme, host, path, urlencode(kept), fragment))
