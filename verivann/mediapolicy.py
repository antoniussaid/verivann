"""Who decides whether a video gets downloaded — and the answer is: the user, always.

Reading a video's existing captions is one thing. Downloading the media file is
another, and it is the one that touches a platform's terms. So Verivann never makes
that decision on its own, never makes it silently, and never makes it *for* the
user on someone else's machine.

    VERIVANN_MEDIA=off        never download media. Captions or nothing.
    VERIVANN_MEDIA=fallback   (default) download ONLY when the video has no captions —
                           and only to transcribe it. The file is deleted the moment
                           the transcript exists.
    VERIVANN_MEDIA=ask        decide per item.
    VERIVANN_MEDIA=always     download whenever it would help.

    VERIVANN_MEDIA_KEEP=1     keep the downloaded file (default: delete it immediately)

Three things make this more than a preference toggle:

1. **The default is the most conservative one that still works.** Captions first;
   media only when there is no other way to know what was said; deleted at once.
2. **What actually happened is written into the note.** "Captions used, nothing
   downloaded" or "audio fetched for transcription, deleted immediately" — so there
   is a record, not a claim.
3. **The decision travels with the user, not with us.** Whatever runs on their
   machine, under their setting, is their act. Verivann does not download anything on
   anyone's behalf, anywhere, ever.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

OFF = "off"
FALLBACK = "fallback"
ASK = "ask"
ALWAYS = "always"

_MODES = (OFF, FALLBACK, ASK, ALWAYS)

# Platforms that put a technological protection measure on the media stream.
#
# This is not a preference and it is not configurable. Fetching the media file from
# these services means circumventing that measure — and in the EU that is not a terms
# problem, it is § 90c UrhG / Art. 6 InfoSoc, which reaches the *tool*, its *service*
# and even its *advertising*. OLG Hamburg held YouTube's rolling cipher to be an
# effective technological measure and made even a passive host liable; the BGH let it
# stand (Oct 2025).
#
# The published caption track is a different thing entirely: served separately, in
# plain text, behind no measure at all. So on these platforms Verivann reads the words
# and never touches the stream — which is also, conveniently, all we ever wanted.
_PROTECTED = (
    "youtube.com", "youtu.be", "youtube-nocookie.com",
    "netflix.com", "primevideo.com", "disneyplus.com", "spotify.com",
    "audible.com", "vimeo.com/ondemand",
)


def protected(url: str) -> bool:
    low = (url or "").lower()
    return any(host in low for host in _PROTECTED)


def mode() -> str:
    value = os.environ.get("VERIVANN_MEDIA", FALLBACK).strip().lower()
    return value if value in _MODES else FALLBACK


def keep_media() -> bool:
    """Keep the downloaded file? Off by default: we wanted the words, not the video."""
    return os.environ.get("VERIVANN_MEDIA_KEEP", "").strip().lower() in ("1", "true", "yes", "on")


@dataclass
class Decision:
    allowed: bool
    reason: str
    note: str  # what goes into the note, so the record is a record and not a claim


def decide(has_captions: bool, asked=None, url: str = "") -> Decision:
    """May we fetch the media itself for this item?

    `asked` is a callable the caller supplies for ASK mode (a CLI prompt, a dialog in
    the app). If none is supplied — a background run, a server, a scheduled job — ASK
    resolves to NO. Silence is never consent.
    """
    # The one rule no setting can override. A user may consent to many things; they
    # cannot consent us out of § 90c, because that provision is not about their
    # relationship with the platform — it is about what our software is.
    if protected(url):
        return Decision(
            False,
            "this platform protects its media stream — reading around that is not a "
            "setting, it is circumvention",
            "**No media was fetched.** This platform puts a technological measure on its "
            "stream, so Verivann reads only the published caption track — which is plain text, "
            "behind no measure at all. This cannot be switched on.",
        )

    current = mode()

    if current == OFF:
        return Decision(False, "media downloads are off", "No media was downloaded (policy: off).")

    if has_captions and current != ALWAYS:
        return Decision(
            False,
            "the video already has captions",
            "Captions were read; **nothing was downloaded** — the words were already there.",
        )

    if current == ASK:
        if asked is None or not asked():
            return Decision(
                False,
                "you were asked and said no (or nobody was there to ask)",
                "No media was downloaded (you were not asked, or you declined).",
            )
        return Decision(True, "you said yes", _did_download())

    if current == FALLBACK:
        return Decision(
            True,
            "there are no captions, so there is no other way to know what was said",
            _did_download(),
        )

    return Decision(True, "media downloads are set to always", _did_download())


def _did_download() -> str:
    if keep_media():
        return (
            "Audio was downloaded to transcribe it, **and kept** (VERIVANN_MEDIA_KEEP=1). "
            "This ran on your machine, under your setting."
        )
    return (
        "Audio was downloaded **only to transcribe it, and deleted immediately** — the "
        "transcript is what survives. This ran on your machine, under your setting."
    )


def describe() -> str:
    lines = {
        OFF: "never download media — captions or nothing",
        FALLBACK: "download only when there are no captions, transcribe, delete at once",
        ASK: "ask, every time",
        ALWAYS: "download whenever it helps",
    }
    return f"{mode()} — {lines[mode()]}" + ("  (files are kept)" if keep_media() else "")
