"""Send the meaning. Keep the identity.

The privacy rule (privacy.py) is binary and honest: sensitive material either goes
to a local model or to nobody. That is correct, and for a person without a local
model it is also useless — their screenshots, their PDFs, their voice memos simply
never get read.

So here is the middle path, and as far as we can tell nobody in this field offers
it: **redact locally, then upload.** Account numbers, card numbers, phone numbers,
emails, addresses, dates of birth, names and amounts are replaced with stable
placeholders *before* the text leaves the machine, and put back — locally — in the
note you read.

    VERIVANN_REDACT=1     analyze sensitive material after redaction (opt-in, explicit)

Three properties that make this trustworthy rather than a comfort blanket:

1. **Placeholders are stable within a note** (`[PERSON_1]` is the same person
   throughout), so the model can still reason about who did what — it just never
   learns who they are.
2. **The mapping never leaves the machine.** It lives in memory for the duration of
   one analysis and is used to restore the note locally.
3. **It is a reduction of risk, not a guarantee.** Redaction is pattern matching:
   an unusual name, an address in an odd format, a number we do not recognize will
   get through. The note says so. Anyone who tells you their redactor is complete
   is selling something.

For a bank statement that is a good trade. For a psychiatric report it is not, and
the honest advice — printed by the tool itself — is to keep `VERIVANN_PRIVACY=strict`
and install a local model.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field

# Order matters: the most specific patterns first, so an IBAN is not eaten by the
# generic "long number" rule.
_PATTERNS: list[tuple[str, str]] = [
    ("IBAN", r"\b[A-Z]{2}\d{2}[ ]?(?:[A-Z0-9]{4}[ ]?){2,7}[A-Z0-9]{1,4}\b"),
    ("CARD", r"\b(?:\d{4}[ -]?){3}\d{1,4}\b"),
    ("EMAIL", r"\b[\w.+-]+@[\w-]+\.[\w.-]+\b"),
    ("PHONE", r"(?<![\w/])(?:\+\d{1,3}[ /-]?)?(?:\(?\d{2,4}\)?[ /-]?)?\d{3,4}[ /-]?\d{3,6}(?![\w/])"),
    ("SVNR", r"\b\d{4}\s?\d{2}\s?\d{2}\s?\d{2}\b"),  # Austrian social security number
    ("DOB", r"\b(?:0?[1-9]|[12]\d|3[01])[./](?:0?[1-9]|1[0-2])[./](?:19|20)\d{2}\b"),
    ("AMOUNT", r"(?:€|EUR|\$|CHF)\s?\d[\d.,]{2,}|\b\d[\d.]{2,},\d{2}\s?(?:€|EUR)\b"),
    ("ADDRESS", r"\b[A-ZÄÖÜ][\wäöüß.-]+(?:straße|strasse|gasse|weg|platz|allee|ring)\s+\d+[a-z]?\b"),
    ("POSTAL", r"\b(?:A-)?\d{4,5}\s+[A-ZÄÖÜ][\wäöüß-]{2,}\b"),
    ("URLUSER", r"https?://[^\s]*[?&](?:token|key|auth|session)=[^\s&]+"),
]

# Names are the hard part without an NLP model. This catches the common German/English
# honorific + name form, which is where most of the identifying power sits in
# letters, invoices and medical documents.
_NAME = re.compile(
    r"\b(?:Herr|Frau|Hr\.|Fr\.|Dr\.|Mag\.|Ing\.|Prof\.|Mr\.|Mrs\.|Ms\.)\s+"
    r"(?:[A-ZÄÖÜ][\wäöüß-]+\s+){0,2}[A-ZÄÖÜ][\wäöüß-]+"
)


def enabled() -> bool:
    return os.environ.get("VERIVANN_REDACT", "").strip().lower() in ("1", "true", "yes", "on")


@dataclass
class Redaction:
    text: str
    mapping: dict[str, str] = field(default_factory=dict)  # placeholder -> original
    counts: dict[str, int] = field(default_factory=dict)  # kind -> how many

    @property
    def any(self) -> bool:
        return bool(self.mapping)

    def restore(self, text: str) -> str:
        """Put the truth back — locally, in the note you read."""
        for placeholder, original in self.mapping.items():
            text = text.replace(placeholder, original)
        return text

    def summary(self) -> str:
        if not self.any:
            return "Nothing identifiable was found to redact — the text was sent as it is."
        parts = ", ".join(f"{n}× {kind.lower()}" for kind, n in sorted(self.counts.items()))
        return (
            f"Redacted before upload: {parts}. The originals never left this machine; "
            "they were put back into this note locally. Redaction is pattern matching, "
            "not a guarantee — an unusual name or format can slip through."
        )


def redact(text: str) -> Redaction:
    """Replace what identifies a person with stable placeholders."""
    result = Redaction(text=text)
    seen: dict[str, str] = {}  # original -> placeholder, so the same value maps consistently

    def _swap(kind: str, match: re.Match) -> str:
        original = match.group(0)
        if original in seen:
            return seen[original]
        index = result.counts.get(kind, 0) + 1
        result.counts[kind] = index
        placeholder = f"[{kind}_{index}]"
        seen[original] = placeholder
        result.mapping[placeholder] = original
        return placeholder

    out = text
    for kind, pattern in _PATTERNS:
        out = re.sub(pattern, lambda m, k=kind: _swap(k, m), out)
    out = _NAME.sub(lambda m: _swap("PERSON", m), out)

    result.text = out
    return result
