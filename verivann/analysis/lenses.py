"""Lenses — the same material, read with a different intent.

A lens does not change the contract: every analysis still returns the routing
keys (domain / confidence / reason / action) and three lists. What a lens changes
is *what the model looks for* in the material, and what the three lists are
called in the note.

    verivann ingest-url <url> --lens critique

Fabric-style prompt patterns, but wired into a router: the lens output is still
routed, still proposal-only, still indexed and checked against the claim ledger.

Lenses only affect the LLM backend. Without a model configured, routing stays
heuristic and the lens is recorded but has nothing to steer.
"""

from __future__ import annotations

from dataclasses import dataclass

DEFAULT_LENS = "digest"


@dataclass(frozen=True)
class Lens:
    name: str
    description: str
    guidance: str
    # Headings for the three lists, in note order: ideas / claims / actions.
    headings: tuple[str, str, str] = ("Useful ideas", "Claims to verify", "Possible actions")


_LENSES: dict[str, Lens] = {
    "digest": Lens(
        name="digest",
        description="Balanced default: what it says, what to check, what to do.",
        guidance=(
            "Digest the material fairly. useful_ideas = the ideas worth keeping. "
            "claims_to_verify = factual assertions that would need checking. "
            "possible_actions = concrete things the reader could do."
        ),
    ),
    "wisdom": Lens(
        name="wisdom",
        description="Insight extraction: timeless ideas, principles, habits.",
        guidance=(
            "Read for durable insight, not news. useful_ideas = surprising or "
            "timeless insights, stated as complete thoughts, not topic labels. "
            "claims_to_verify = the assertions those insights rest on. "
            "possible_actions = habits or practices the material implies."
        ),
        headings=("Insights", "Claims the insights rest on", "Habits to try"),
    ),
    "critique": Lens(
        name="critique",
        description="Skeptical read: weak points, missing evidence, what would falsify it.",
        guidance=(
            "Read adversarially, but fairly — you are not obliged to agree with the "
            "material. useful_ideas = the weakest points, stated plainly (what is "
            "asserted without support, what is conflated, what is left out). "
            "claims_to_verify = the assertions that carry the argument and are "
            "unsupported. possible_actions = what evidence would settle it, or what "
            "would falsify the central claim. If the material is sound, say so — do "
            "not invent flaws."
        ),
        headings=("Weak points", "Unsupported claims", "What would settle it"),
    ),
    "study": Lens(
        name="study",
        description="Study notes: key concepts, open questions, practice.",
        guidance=(
            "Read as a student. useful_ideas = the key concepts, each explained in "
            "one sentence a beginner could follow. claims_to_verify = the parts you "
            "would have to look up to be sure you understood them. "
            "possible_actions = exercises or practice steps to actually learn this."
        ),
        headings=("Key concepts", "Look these up", "Practice"),
    ),
    "actions": Lens(
        name="actions",
        description="Operator read: what to do, in what order, starting now.",
        guidance=(
            "Read as an operator with limited time. useful_ideas = only what changes "
            "a decision. claims_to_verify = the assumptions the plan depends on. "
            "possible_actions = concrete next steps, imperative, in order, each one "
            "small enough to do in a sitting. Prefer action=task when the material "
            "really implies work."
        ),
        headings=("What changes a decision", "Assumptions to check", "Next actions"),
    ),
}


def lens_names() -> list[str]:
    return list(_LENSES)


def get_lens(name: str | None) -> Lens:
    """Unknown or empty name -> the default lens (never raises)."""
    return _LENSES.get((name or "").strip().lower(), _LENSES[DEFAULT_LENS])


def describe() -> list[tuple[str, str]]:
    return [(lens.name, lens.description) for lens in _LENSES.values()]
