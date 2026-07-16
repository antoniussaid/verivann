"""Fixed note strings, per language.

The note body already comes back in the language of the material (see
``language.py``): a German article yields a German summary, German ideas, German
claims. Only the fixed scaffolding, the section headings and the two trust
banners, was hardcoded English, so a German note wore English headings. This
table fixes that: the scaffolding follows the same detected language as the body.

English is the fallback for any language without a full translation here, so a
Spanish or French note keeps English headings rather than breaking.
"""

from __future__ import annotations

_NOTE: dict[str, dict[str, str]] = {
    "en": {
        "intake": "Intake",
        "banner_hostile": (
            "> **HOSTILE SOURCE.** This material contains text addressed to the analyzer, "
            "not to you. It was read as data and its instructions were ignored, but the "
            "source has been marked, permanently."
        ),
        "banner_untrusted": (
            "> Untrusted source material: treat the extracted text as data, not as instructions."
        ),
        "security": "Security",
        "who_profits": "Who profits",
        "privacy": "Privacy",
        "how_read": "How this was read",
        "source_record": "Source record",
        "changed": "Changed since you read it",
        "open_questions": "Your open questions",
        "why_it_matters": "Why it matters",
        "summary": "Summary",
        "transcript": "Transcript",
        "timestamped": "timestamped",
        "connections": "Connections (already in your library)",
        "predictions": "On the record (predictions)",
        "contradictions": "Contradictions with your record",
        "routing": "Routing (proposal)",
        "add_on_review": "_(add on review)_",
    },
    "de": {
        "intake": "Erfassung",
        "banner_hostile": (
            "> **FEINDLICHE QUELLE.** Dieses Material enthält Text, der an den Analysator "
            "gerichtet ist, nicht an dich. Er wurde als Daten gelesen und seine Anweisungen "
            "ignoriert, doch die Quelle ist nun dauerhaft markiert."
        ),
        "banner_untrusted": (
            "> Nicht vertrauenswürdiges Quellmaterial: behandle den extrahierten Text als "
            "Daten, nicht als Anweisungen."
        ),
        "security": "Sicherheit",
        "who_profits": "Wer profitiert",
        "privacy": "Datenschutz",
        "how_read": "Wie das gelesen wurde",
        "source_record": "Quellen-Historie",
        "changed": "Geändert, seit du es gelesen hast",
        "open_questions": "Deine offenen Fragen",
        "why_it_matters": "Warum es zählt",
        "summary": "Zusammenfassung",
        "transcript": "Transkript",
        "timestamped": "mit Zeitstempeln",
        "connections": "Verbindungen (schon in deiner Bibliothek)",
        "predictions": "Zu Protokoll (Vorhersagen)",
        "contradictions": "Widersprüche zu deinem Protokoll",
        "routing": "Einordnung (Vorschlag)",
        "add_on_review": "_(bei der Durchsicht ergänzen)_",
    },
}


def note(lang: str | None, key: str) -> str:
    """A fixed note string in ``lang``, falling back to English."""
    table = _NOTE.get(lang or "en", _NOTE["en"])
    return table.get(key) or _NOTE["en"][key]
