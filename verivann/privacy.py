"""What is allowed to leave this machine.

We call ourselves local-first. Then we taught Verivann to read your screenshots, your
voice memos and your PDFs - and if `VERIVANN_LLM=openai` is set, every one of them is
shipped, in full, to somebody else's server. That is not local-first; that is a
leak with good branding.

So material is classified before any model sees it:

    public      it came from the open web. It was already public.
    sensitive   it came off your disk (a screenshot, a memo, a document), or it
                carries the marks of private life: an IBAN, a card number, a salary,
                a diagnosis, a credential.

And there are two model slots, not one:

    VERIVANN_LLM         may be hosted. Sees public material.
    VERIVANN_LOCAL_LLM   never leaves the machine (Ollama). Sees everything else.

Policy `VERIVANN_PRIVACY` (default **strict**):

    strict   sensitive material goes to the local slot. If there is none, it falls
             back to the offline heuristic and the note says so. It is never
             silently uploaded.
    allow    you have decided otherwise, explicitly, in writing, in your own config.

The classifier errs toward `sensitive`. A false positive costs you a worse summary;
a false negative costs you a bank statement in someone's training set.
"""

from __future__ import annotations

import os
import re
from dataclasses import replace
from urllib.parse import urlsplit

from .config import Config, LLMConfig

PUBLIC = "public"
SENSITIVE = "sensitive"

_LOCAL_HOSTS = ("localhost", "127.0.0.1", "0.0.0.0", "::1", "host.docker.internal")

# Marks of private life. Deliberately blunt: this decides where data goes, not what
# it means, and being wrong in the cautious direction is cheap.
_PII_PATTERNS: list[tuple[str, str]] = [
    (r"\b[A-Z]{2}\d{2}[ ]?[A-Z0-9]{4}(?:[ ]?\d{4}){2,4}\b", "IBAN"),
    (r"\b(?:\d[ -]?){13,19}\b", "card-like number"),
    (r"\b(?:bic|swift)\b[:\s]", "bank details"),
    (r"\b(gehalt|salär|salary|lohnzettel|payslip|kontoauszug|bank statement|rechnung|invoice)\b", "financial document"),
    (r"\b(diagnose|diagnosis|befund|patient|prescription|rezept|blutbild)\b", "medical"),
    (r"\b(passwort|password|api[_ -]?key|secret[_ -]?key|token|zugangsdaten|credentials)\b[:\s=]", "credential"),
    (r"\b(sozialversicherungsnummer|svnr|social security|steuernummer|tax id|passport no)\b", "government id"),
    (r"\b(vertraulich|confidential|streng geheim|nda|nicht zur weitergabe)\b", "marked confidential"),
]


def policy() -> str:
    value = os.environ.get("VERIVANN_PRIVACY", "strict").strip().lower()
    return value if value in ("strict", "allow") else "strict"


def classify(kind: str, text: str, meta: dict | None = None) -> tuple[str, str]:
    """(sensitivity, why). Anything off your own disk is sensitive until proven public."""
    if kind == "file":
        return SENSITIVE, "it came off your own disk"
    haystack = f"{text or ''}"[:20000]
    for pattern, label in _PII_PATTERNS:
        if re.search(pattern, haystack, re.IGNORECASE):
            return SENSITIVE, f"it contains what looks like {label}"
    return PUBLIC, "it came from the open web"


def is_local(llm: LLMConfig) -> bool:
    if not llm.enabled:
        return True  # the offline heuristic never leaves the room
    host = (urlsplit(llm.base_url).hostname or "").lower()
    return host in _LOCAL_HOSTS


REDACTED = "redacted"  # sent to a hosted model, but stripped of what identifies you


def slot_for(config: Config, sensitivity: str) -> tuple[LLMConfig, bool]:
    """Which model may read this - and whether the material stays on the machine.

    Returns (llm, stayed_local). A disabled LLMConfig means: nobody may read it but
    the offline heuristic, and the note will say so rather than pretend.
    """
    if sensitivity == PUBLIC:
        return config.llm, is_local(config.llm)

    if config.local_llm.enabled:
        return config.local_llm, True
    if policy() == "allow" and config.llm.enabled:
        return config.llm, is_local(config.llm)  # your machine, your call - but it is on the record
    return LLMConfig(), True  # strict, no local model: the heuristic, and an honest note


def mode_for(config: Config, sensitivity: str) -> tuple[LLMConfig, bool, str]:
    """(llm, stayed_local, mode) - the full decision, including redaction.

    Three ways sensitive material can be handled, and the user picks:

      local      a local model reads it; nothing leaves.
      redacted   VERIVANN_REDACT=1 - identity is stripped locally, the MEANING is sent
                 to the hosted model, and the note is restored on this machine.
      withheld   strict policy, no local model, no redaction: it is not uploaded, and
                 it is not read. The note says so instead of pretending.
    """
    from .redact import enabled as redaction_on

    llm, stayed_local = slot_for(config, sensitivity)
    if sensitivity == PUBLIC:
        return llm, stayed_local, "public"
    if llm.enabled and stayed_local:
        return llm, True, "local"
    if llm.enabled and not stayed_local:
        return llm, False, "uploaded"  # policy=allow
    if redaction_on() and config.llm.enabled:
        return config.llm, False, REDACTED
    return LLMConfig(), True, "withheld"


def config_for(config: Config, sensitivity: str) -> tuple[Config, bool]:
    """The config an analyzer may use for material of this sensitivity."""
    llm, stayed_local = slot_for(config, sensitivity)
    return replace(config, llm=llm), stayed_local


def explain(
    sensitivity: str, why: str, llm: LLMConfig, stayed_local: bool, mode: str = "", redaction: str = ""
) -> str:
    """The line that goes into the note. Nobody should have to guess where their data went."""
    if sensitivity == PUBLIC:
        target = "a local model" if stayed_local else "a hosted model"
        return f"Public material ({why}); analyzed by {target}." if llm.enabled else \
            f"Public material ({why}); analyzed offline."

    if mode == REDACTED:
        return (
            f"**Sensitive** ({why}) - analyzed by a hosted model **after local redaction**. "
            f"{redaction} No local model is configured; you enabled VERIVANN_REDACT to get this "
            "material read at all. `verivann outbound` records what was sent."
        )
    if mode == "withheld" or not llm.enabled:
        return (
            f"**Sensitive** ({why}). No local model is configured and the policy is `strict`, "
            "so this was NOT sent anywhere - it was routed by the offline heuristic and never "
            "properly read. Your options, in order of honesty: install a local model "
            "(VERIVANN_LOCAL_LLM), enable local redaction (VERIVANN_REDACT=1), or accept the upload "
            "explicitly (VERIVANN_PRIVACY=allow)."
        )
    if stayed_local:
        return f"**Sensitive** ({why}). Analyzed by the local model - nothing left this machine."
    return (
        f"**Sensitive** ({why}) - and VERIVANN_PRIVACY=allow, so the full text was sent to a hosted "
        f"model ({llm.provider}:{llm.model}). This is on the record: `verivann outbound`."
    )
