"""Analysis layer - relevance, routing, and (optionally) content digestion.

Two backends behind one `analyze()`:
  - `heuristic_analyze` - offline keyword scoring. Transparent, free, no model.
    Fills routing only; content sections stay for review. This is the public
    default.
  - the LLM backend (analysis/llm.py) - kicks in only when a model is configured
    (private LLMConfig). It also fills summary / ideas / claims / actions.

Hard rule (contract): PROPOSE-ONLY. Neither backend ever proposes "memory".
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from ..language import GERMAN_ACTION_WORDS, GERMAN_KEYWORDS, detect
from ..schema import Action, Extracted
from .lenses import DEFAULT_LENS


@dataclass
class Analysis:
    domain: str
    confidence: float
    reason: str
    action: Action
    summary: str = ""
    useful_ideas: list[str] = field(default_factory=list)
    claims_to_verify: list[str] = field(default_factory=list)
    possible_actions: list[str] = field(default_factory=list)
    engine: str = "heuristic"  # "heuristic" or "llm:<model>"
    lens: str = DEFAULT_LENS  # which reading intent produced this
    # Claims about the future, with a date. These go on the record and come back
    # to haunt whoever made them (predictions.py).
    predictions: list[dict] = field(default_factory=list)  # [{"text", "due"}]
    # How long each claim can be trusted before it should be re-checked (claims.py).
    shelf_life_days: int = 0  # 0 = unknown / not estimated
    language: str = "en"  # what the MATERIAL is written in - the note answers in it


def analyze(
    extracted: Extracted, config=None, lens: str | None = None, preference: str = ""
) -> Analysis:
    """Dispatch to the LLM when configured, else the heuristic (with fallback).

    `preference` is the learned-relevance hint (see relevance.py) - a mild prior,
    passed to the LLM only; the heuristic path is nudged by the caller instead.
    """
    lens = lens or getattr(config, "lens", None) or DEFAULT_LENS
    llm = getattr(config, "llm", None) if config is not None else None
    if llm is not None and llm.enabled:
        from .llm import llm_analyze  # lazy import avoids a hard httpx/config cycle

        try:
            return llm_analyze(extracted, config, lens=lens, preference=preference)
        except Exception as exc:  # noqa: BLE001 - any LLM failure -> heuristic
            fallback = heuristic_analyze(extracted)
            fallback.lens = lens
            fallback.reason = f"LLM unavailable ({exc}); heuristic fallback. " + fallback.reason
            return fallback
    result = heuristic_analyze(extracted)
    result.lens = lens
    return result


# ---------- heuristic backend ----------

def _matches(word: str, text: str) -> bool:
    # Word-boundary match so short tokens like "ai" don't hit "sustain"/"detail".
    return re.search(r"\b" + re.escape(word) + r"\b", text) is not None


_ENGLISH_KEYWORDS: dict[str, list[str]] = {
    # Writing the German list exposed how thin this one always was: it had no word for
    # insurance, rent, pension or fees - the things people actually deal with.
    "finance": [
        "finance", "money", "invest", "budget", "cost", "price", "salary",
        "tax", "bank", "crypto", "insurance", "premium", "rent", "loan",
        "interest", "pension", "savings", "fee", "invoice", "broker", "etf",
    ],
    "media": [
        "video", "youtube", "tiktok", "reel", "podcast", "film", "image",
        "photo", "foto", "media", "social", "instagram", "pinterest",
    ],
    "research": [
        "architecture", "system", "ai", "llm", "model", "memory", "agent",
        "local-first", "self-hosted", "automation", "framework", "research",
        "paper", "study", "protocol", "security", "governance", "pipeline",
    ],
    "tasks": [
        "todo", "task", "deadline", "apply", "schedule", "fix", "buy",
        "aufgabe", "erledigen", "frist", "bewerben",
    ],
}

_ENGLISH_ACTION_WORDS = [
    "todo", "task", "deadline", "apply", "buy", "schedule",
    "next step", "action",
]


def _vocabulary(language: str) -> tuple[dict[str, list[str]], list[str]]:
    """The routing vocabulary for the language the material is actually written in.

    German material used to be routed by an English keyword list with a handful of
    German words bolted on. "Kündigungsfrist" should route as surely as "deadline".
    """
    if language != "de":
        return _ENGLISH_KEYWORDS, _ENGLISH_ACTION_WORDS

    merged = {
        domain: words + GERMAN_KEYWORDS.get(domain, [])
        for domain, words in _ENGLISH_KEYWORDS.items()
    }
    return merged, _ENGLISH_ACTION_WORDS + GERMAN_ACTION_WORDS


def heuristic_analyze(extracted: Extracted) -> Analysis:
    raw = f"{extracted.title}\n{extracted.text}".strip()
    text = raw.lower()

    if len(text) < 20:
        return Analysis("inbox", 0.1, "Too little content to route.", "drop")

    language = detect(raw)
    keywords, action_words = _vocabulary(language)

    scores: dict[str, int] = {}
    for domain, words in keywords.items():
        hits = sum(1 for w in words if _matches(w, text))
        if hits:
            scores[domain] = hits

    if scores:
        domain = max(scores, key=lambda d: scores[d])
        hits = scores[domain]
        confidence = min(0.95, 0.4 + hits * 0.15)
        reason = f"Matched {hits} '{domain}' keyword(s)."
    else:
        domain, confidence, reason = "inbox", 0.2, "No routing keywords matched."

    action: Action = "task" if any(_matches(w, text) for w in action_words) else "note"
    result = Analysis(domain, round(confidence, 2), reason, action)
    result.language = language
    return result
