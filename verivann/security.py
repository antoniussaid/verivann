"""What the material is trying to do to you.

Every note Verivann writes says `content_trust: unverified` — web material is data,
never instruction. That is a *policy*. This module makes it *auditable*: it looks
for material that is actively trying to steer the analyzer, and for material that
is trying to steer you.

Two scans, both cheap, both offline:

  injection    text aimed at the model rather than at a reader ("ignore all
               previous instructions"), hidden from the human eye (white-on-white,
               display:none, zero-size type), or dressed in invisible characters.
               A hit downgrades the note to `content_trust: hostile` and puts a
               permanent mark on the source's record (sources.py). This is the one
               judgment Verivann makes without asking a model.

  interest     who paid for this: sponsorships, affiliate codes, referral params,
               "link in bio". Rendered ABOVE the summary — you learn who profits
               before you learn what they claim.

Neither scan blocks anything. It reports. The pipeline is the same either way; the
difference is that you know.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

# Text addressed to a model, not to a reader. Deliberately narrow: these phrases
# have no innocent use in editorial material.
_INJECTION_PATTERNS: list[tuple[str, str]] = [
    (r"ignore (all |any )?(the )?(previous|prior|above|preceding) (instructions?|prompts?|rules?)", "override attempt"),
    (r"disregard (all |any )?(the )?(previous|prior|above)", "override attempt"),
    (r"forget (everything|all previous|your instructions)", "override attempt"),
    (r"you are now (a|an|the)\b", "role hijack"),
    (r"(new|updated) (system )?(prompt|instructions?)\s*:", "role hijack"),
    (r"\b(system|assistant|user)\s*:\s*(you|please|now)\b", "role hijack"),
    (r"<\|(im_start|im_end|system|endoftext)\|>", "chat-template smuggling"),
    (r"###\s*(instruction|system)", "chat-template smuggling"),
    (r"\[\[?\s*(system|admin)\s*\]?\]", "chat-template smuggling"),
    (r"do not (summari[sz]e|analy[sz]e|mention|reveal)", "output steering"),
    (r"instead,? (output|print|write|respond|say|reply)", "output steering"),
    (r"(print|output|repeat) (your|the) (system )?(prompt|instructions)", "prompt exfiltration"),
    (r"(send|post|exfiltrate|upload)\b.{0,40}\b(to|at)\s+https?://", "exfiltration attempt"),
    (r"\b(api[_ -]?key|password|secret|token)\b.{0,30}\b(send|reveal|include|output)", "exfiltration attempt"),
]

# Zero-width and directional characters. NOT the soft hyphen (U+00AD) — that is
# ordinary typography, and treating it as an attack was how this scan first learned
# to cry wolf.
_INVISIBLE = re.compile(r"[​-‏⁠-⁤﻿]")

# The Unicode TAG block: invisible characters that carry a full ASCII payload. This
# is the currently fashionable way to hide an instruction in plain text — a human
# sees nothing, the model reads a sentence. There is no innocent use of it.
_TAG_BLOCK = re.compile(r"[\U000E0000-\U000E007F]+")

# Long base64 blobs sometimes carry the payload one decode away.
_BASE64 = re.compile(r"[A-Za-z0-9+/]{60,}={0,2}")

_INVISIBLE_ALARM = 30  # a handful are joiners in emoji and Indic scripts; dozens are a technique

_INTEREST_PATTERNS: list[tuple[str, str]] = [
    (r"\b(sponsored by|sponsor of (this|today)|brought to you by|in partnership with)\b", "sponsorship"),
    (r"\b(paid partnership|bezahlte partnerschaft|werbung|anzeige|dieses video enthält werbung)\b", "sponsorship"),
    (r"\b(affiliate|provisions?link|werbelink|ref(erral)? link)\b", "affiliate"),
    (r"\b(use (the )?code|discount code|promo code|rabattcode|gutscheincode)\b", "discount code"),
    (r"\b(link in (the )?bio|link in der bio|erster link)\b", "funnel"),
    (r"\b(my course|mein kurs|masterclass|coaching|mentorship|join my)\b", "own product"),
    (r"\b(not financial advice|keine anlageberatung)\b", "disclaimer (finance)"),
]

# Referral/affiliate markers inside outbound links.
_AFFILIATE_PARAMS = re.compile(
    r"[?&](tag|aff|affid|affiliate|ref|referrer|partner|utm_campaign=aff\w*)=", re.IGNORECASE
)

_MAX_QUOTE = 140


@dataclass
class Finding:
    kind: str  # what it is ("override attempt", "sponsorship", …)
    quote: str  # the evidence, verbatim (truncated)
    where: str = "text"  # "text" | "hidden" | "links"


def scan_injection(
    text: str,
    hidden_text: str = "",
    links: str = "",
    ocr_text: str = "",
    transcript: str = "",
) -> list[Finding]:
    """Material trying to give the analyzer orders. Empty list = nothing found.

    Five channels, and the channel matters as much as the content:

      text        the page as a human reads it
      hidden      styled out of sight (white-on-white, display:none, off-screen)
      ocr         text extracted from an IMAGE — it never passed a web sanitizer,
      audio       text extracted from SPEECH — nor did this one.
      links       the page's outbound URLs

    A poster in a video and a sentence in a podcast can both carry an instruction,
    and both bypass every text-layer defence in existence. That is why they get
    their own label instead of being folded into `text`.

    What is deliberately NOT reported: the mere existence of hidden text. Every
    accessible website hides text from sighted users (`sr-only` navigation,
    `aria-hidden` icons), and an early version of this scan branded GitHub as
    hostile for it. Hidden text is evidence only when it *says* something.
    """
    findings: list[Finding] = []

    channels = (
        (text or "", "text"),
        (hidden_text or "", "hidden"),
        (ocr_text or "", "ocr"),
        (transcript or "", "audio"),
    )
    for haystack, where in channels:
        low = haystack.lower()
        for pattern, kind in _INJECTION_PATTERNS:
            match = re.search(pattern, low, re.IGNORECASE)
            if match:
                findings.append(Finding(kind, _quote(haystack, match.start()), where))

        # A payload smuggled through invisible characters, or one decode away.
        findings.extend(_smuggled(haystack, where))

    if links and re.search(r"data:text/|javascript:", links, re.IGNORECASE):
        findings.append(Finding("active link", "javascript:/data: URL in the page", "links"))

    return _dedupe(findings)


def _smuggled(haystack: str, where: str) -> list[Finding]:
    """Payloads that are invisible to a reader but perfectly legible to a model."""
    findings: list[Finding] = []

    tags = _TAG_BLOCK.findall(haystack)
    if tags:
        decoded = "".join(chr(ord(c) - 0xE0000) for c in "".join(tags) if 0xE0020 <= ord(c) <= 0xE007E)
        findings.append(
            Finding("invisible payload (unicode tags)", (decoded or f"{len(tags)} tag runs")[:_MAX_QUOTE], where)
        )

    invisible = _INVISIBLE.findall(haystack)
    if len(invisible) > _INVISIBLE_ALARM:
        findings.append(
            Finding("invisible characters", f"{len(invisible)} zero-width characters", where)
        )

    for blob in _BASE64.findall(haystack)[:3]:
        plain = _b64(blob)
        if not plain:
            continue
        low = plain.lower()
        for pattern, kind in _INJECTION_PATTERNS:
            if re.search(pattern, low, re.IGNORECASE):
                findings.append(Finding(f"{kind} (base64-encoded)", plain[:_MAX_QUOTE], where))
                break
    return findings


def _b64(blob: str) -> str:
    import base64
    import binascii

    try:
        raw = base64.b64decode(blob + "=" * (-len(blob) % 4), validate=True)
        plain = raw.decode("utf-8")
    except (binascii.Error, UnicodeDecodeError, ValueError):
        return ""
    printable = sum(c.isprintable() or c.isspace() for c in plain)
    return plain if plain and printable / len(plain) > 0.9 else ""


def scan_interest(text: str, links: str = "") -> list[Finding]:
    """Who profits if you believe this."""
    findings: list[Finding] = []
    low = (text or "").lower()
    for pattern, kind in _INTEREST_PATTERNS:
        match = re.search(pattern, low, re.IGNORECASE)
        if match:
            findings.append(Finding(kind, _quote(text, match.start()), "text"))
    if links and _AFFILIATE_PARAMS.search(links):
        findings.append(Finding("affiliate", "outbound links carry referral parameters", "links"))
    return _dedupe(findings)


def trust_level(injection: list[Finding]) -> str:
    """The value that goes into the note's frontmatter."""
    return "hostile" if injection else "unverified"


def _quote(text: str, at: int) -> str:
    start = max(0, at - 20)
    snippet = " ".join((text[start : at + _MAX_QUOTE]).split())
    return snippet[:_MAX_QUOTE] + ("…" if len(snippet) > _MAX_QUOTE else "")


def _dedupe(findings: list[Finding]) -> list[Finding]:
    seen: set[tuple[str, str]] = set()
    out: list[Finding] = []
    for f in findings:
        key = (f.kind, f.where)
        if key not in seen:
            seen.add(key)
            out.append(f)
    return out[:6]
