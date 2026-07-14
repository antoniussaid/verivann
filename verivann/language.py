"""The material is German. The tool was not.

An Austrian reads German articles, watches German videos and writes German notes -
and every prompt in this codebase was in English, every keyword list was half-hearted
about German, and nobody ever measured what that cost. It is the kind of failure that
does not announce itself: the summaries come back in English, the routing is a little
worse, and you assume the model is just mediocre.

Two things happen here:

1. **The language of the material is detected** - cheaply, offline, by looking at
   function words. No dependency, no model, and it does not need to be clever: it needs
   to tell German from English from Spanish, which is a job that stopwords do well.
2. **The analyzer is told to answer in that language.** The instructions stay English
   (models follow English instructions better, and our prompts are engineered), but the
   *output* - summary, ideas, claims, reason - comes back in the language you read.

The heuristic router also gets a proper German vocabulary, because "Vorsorge" and
"Kündigungsfrist" should route as surely as "insurance" and "deadline".
"""

from __future__ import annotations

import re
from collections import Counter

# Function words: the most frequent, most unmistakable words in each language. A text
# is written in the language whose function words it is full of. This is a 1970s trick
# and it is still the right one at this size.
_MARKERS: dict[str, set[str]] = {
    "de": {
        "der", "die", "das", "und", "ist", "nicht", "ein", "eine", "auch", "mit",
        "sich", "auf", "für", "von", "dass", "aber", "wie", "wir", "man", "noch",
        "wenn", "werden", "kann", "sind", "haben", "wird", "einen", "einer", "über",
    },
    "en": {
        "the", "and", "is", "not", "a", "an", "also", "with", "itself", "on",
        "for", "from", "that", "but", "how", "we", "one", "still", "if", "will",
        "can", "are", "have", "of", "to", "this", "there", "about", "would",
    },
    "es": {"el", "la", "los", "las", "y", "es", "no", "un", "una", "con", "para", "que", "por"},
    "fr": {"le", "la", "les", "et", "est", "ne", "un", "une", "avec", "pour", "que", "par", "dans"},
    "it": {"il", "lo", "la", "e", "è", "non", "un", "una", "con", "per", "che", "di", "da"},
}

_WORD = re.compile(r"[a-zA-ZäöüßÄÖÜáéíóúàèìòùçñ]+")

_NAMES = {"de": "German", "en": "English", "es": "Spanish", "fr": "French", "it": "Italian"}


def detect(text: str, sample: int = 3000) -> str:
    """The language of the material - 'de', 'en', … Falls back to 'en' when unsure.

    Deliberately conservative: German and English share a lot of short words, so a
    close call goes to English, which is what the prompts already assume.
    """
    words = [w.lower() for w in _WORD.findall((text or "")[:sample])]
    if len(words) < 12:
        return "en"

    counts = Counter()
    for language, markers in _MARKERS.items():
        counts[language] = sum(1 for word in words if word in markers)

    best, hits = counts.most_common(1)[0]
    if hits < max(3, len(words) * 0.02):  # too few function words to call it
        return "en"
    return best


def name(code: str) -> str:
    return _NAMES.get(code, "English")


def instruction(code: str) -> str:
    """What we add to the system prompt so the ANSWER comes back in the reader's language.

    The instructions themselves stay in English - models follow English instructions
    more reliably, and our prompts are tuned. It is the output that must change.
    """
    if code == "en":
        return ""
    return (
        f"\nLANGUAGE: the material is in {name(code)}. Write every human-readable field "
        f"(summary, reason, ideas, claims, actions) in {name(code)}. The JSON keys and the "
        "enum values (domain, action) stay exactly as specified, in English.\n"
    )


# The German half of the routing vocabulary. It was always half-hearted; now it is not.
GERMAN_KEYWORDS: dict[str, list[str]] = {
    "finance": [
        "finanzen", "geld", "investieren", "investment", "aktien", "etf", "fonds", "depot",
        "budget", "kosten", "preis", "gehalt", "lohn", "steuer", "steuern", "bank", "konto",
        "kredit", "zinsen", "rendite", "versicherung", "vorsorge", "pension", "rechnung",
        "sparen", "miete", "kryptowährung", "inflation",
    ],
    "media": [
        "video", "film", "podcast", "folge", "kanal", "bild", "foto", "beitrag", "kurzvideo",
        "sendung", "hörbuch", "musik", "serie", "streaming",
    ],
    "research": [
        "architektur", "system", "modell", "gedächtnis", "speicher", "automatisierung",
        "framework", "forschung", "studie", "papier", "protokoll", "sicherheit", "datenschutz",
        "souveränität", "quelloffen", "selbstgehostet", "lokal", "werkzeug", "schnittstelle",
        "künstliche", "intelligenz", "algorithmus", "datenbank", "entwicklung",
    ],
    "tasks": [
        "aufgabe", "erledigen", "frist", "deadline", "termin", "bewerben", "bewerbung",
        "kaufen", "planen", "anmelden", "kündigen", "kündigungsfrist", "einreichen",
        "besorgen", "erinnern", "nachfragen",
    ],
}

GERMAN_ACTION_WORDS = [
    "aufgabe", "erledigen", "frist", "termin", "bewerben", "kaufen", "planen",
    "anmelden", "kündigen", "einreichen", "besorgen", "nächster schritt", "to-do",
]
