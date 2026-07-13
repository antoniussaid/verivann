"""Learned relevance — the router adapts to what you actually keep.

Every archiver treats all captured material as equally worth keeping. Smelt does
not: `smelt keep <id>` / `smelt drop <id>` records a verdict, and from those
verdicts the router builds a profile of the reader.

Two effects, both deliberately conservative:

  * heuristic routing — a new intake whose vocabulary matches what you kept gains
    confidence; one that matches what you dropped loses it, and at a strong
    negative it is *proposed* as a drop. Still a proposal. Nothing is ever
    committed or deleted.
  * LLM routing — the profile becomes a one-line preference hint in the system
    prompt ("kept: …, dropped: …").

Below MIN_SIGNAL judged notes the profile stays silent — a router that "learns"
from two clicks is superstition, not learning.
"""

from __future__ import annotations

import math
import re
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

from .analysis.analyzer import Analysis
from .library import feedback_rows
from .schema import Extracted

MIN_SIGNAL = 3  # judged notes needed before the profile is trusted at all
# Only a strong, well-evidenced negative may turn a "note" into a proposed "drop".
# score = match × trust, and trust = judged/12 — so this needs ~6+ verdicts that
# nearly all point the same way. Below that the profile only shifts confidence.
_DROP_AT = -0.45
_TOKENS = re.compile(r"[A-Za-zÀ-ÿ][A-Za-zÀ-ÿ0-9\-]{2,}")

_STOP = {
    "the", "and", "for", "with", "that", "this", "you", "your", "are", "was", "from",
    "have", "has", "not", "but", "all", "can", "will", "how", "why", "what", "about",
    "der", "die", "das", "und", "ist", "ein", "eine", "für", "mit", "auf", "von",
    "nicht", "auch", "sich", "dass", "wie", "wir", "ich", "man", "them", "they",
}


def _terms(text: str) -> list[str]:
    return [w for w in (m.group(0).lower() for m in _TOKENS.finditer(text)) if w not in _STOP]


@dataclass
class Profile:
    kept: Counter = field(default_factory=Counter)
    dropped: Counter = field(default_factory=Counter)
    kept_domains: Counter = field(default_factory=Counter)
    dropped_domains: Counter = field(default_factory=Counter)
    n_kept: int = 0
    n_dropped: int = 0
    # Verdicts you actually gave, as opposed to ones your behaviour implied. The
    # profile only comes alive on the strength of real evidence — a pile of
    # inferred drops is not a taste, it is a backlog.
    weight_kept: float = 0.0
    weight_dropped: float = 0.0

    @property
    def judged(self) -> int:
        return self.n_kept + self.n_dropped

    @property
    def evidence(self) -> float:
        return self.weight_kept + self.weight_dropped

    @property
    def active(self) -> bool:
        return self.evidence >= MIN_SIGNAL

    def score(self, text: str, domain: str = "") -> float:
        """-1 … +1. Positive = looks like what this reader keeps."""
        if not self.active:
            return 0.0
        terms = set(_terms(text)[:400])
        if not terms:
            return 0.0
        # Log-scaled term evidence, so one loud note can't dominate the profile.
        pro = sum(math.log1p(self.kept[t]) for t in terms if self.kept[t])
        con = sum(math.log1p(self.dropped[t]) for t in terms if self.dropped[t])
        if domain:
            pro += math.log1p(self.kept_domains[domain]) * 1.5
            con += math.log1p(self.dropped_domains[domain]) * 1.5
        total = pro + con
        if total < 1e-6:
            return 0.0
        raw = (pro - con) / total
        # Confidence in the profile itself grows with the WEIGHT of the evidence,
        # not with the count: twelve shrugs are not twelve decisions.
        trust = min(1.0, self.evidence / 12)
        return round(raw * trust, 3)

    def hint(self) -> str:
        """One line for the LLM system prompt — never the raw material, just the taste."""
        if not self.active:
            return ""
        keep = ", ".join(w for w, _ in self.kept.most_common(8) if self.dropped[w] == 0)
        drop = ", ".join(w for w, _ in self.dropped.most_common(6) if self.kept[w] == 0)
        parts = []
        if keep:
            parts.append(f"they keep material about: {keep}")
        if drop:
            parts.append(f"they drop material about: {drop}")
        if not parts:
            return ""
        return (
            f"Across {self.judged} judged notes, {'; '.join(parts)}. "
            "Use this as a mild prior for relevance and confidence — never as a reason "
            "to distort what the material actually says."
        )


def load_profile(staging_dir: Path) -> Profile:
    profile = Profile()
    try:
        rows = feedback_rows(staging_dir)
    except Exception:  # noqa: BLE001 - a missing/locked db must never break an intake
        return profile
    for verdict, domain, title, text, weight in rows:
        # Weighted evidence: an explicit verdict counts fully, a shrug counts a
        # quarter. The vocabulary of a note you merely ignored should not colour
        # the profile as strongly as one you actually threw away.
        bag = Counter({term: count * weight for term, count in Counter(_terms(f"{title}\n{text[:1500]}")).items()})
        if verdict == "kept":
            profile.kept += bag
            profile.kept_domains[domain] += weight
            profile.n_kept += 1
            profile.weight_kept += weight
        else:
            profile.dropped += bag
            profile.dropped_domains[domain] += weight
            profile.n_dropped += 1
            profile.weight_dropped += weight
    return profile


def apply_profile(analysis: Analysis, extracted: Extracted, profile: Profile) -> Analysis:
    """Nudge a heuristic analysis with the learned signal (LLM runs use hint() instead)."""
    if not profile.active:
        return analysis
    score = profile.score(f"{extracted.title}\n{extracted.text[:2000]}", analysis.domain)
    if abs(score) < 0.15:
        return analysis

    analysis.confidence = round(max(0.05, min(0.95, analysis.confidence + score * 0.25)), 2)
    if score > 0:
        analysis.reason += f" Matches what you keep (learned {score:+.2f})."
    else:
        analysis.reason += f" Looks like what you usually drop (learned {score:+.2f})."
        if score < _DROP_AT and analysis.action == "note":
            analysis.action = "drop"  # a proposal, like every other action
    return analysis
