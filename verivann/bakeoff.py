"""Two models read the same thing. You decide which one was right.

We keep a permanent record of every *source* - right, wrong, manipulative. And
`verivann calibrate` measures the *router* against your verdicts. The obvious next step
was sitting there the whole time: **make the models compete.**

    verivann bakeoff --models llama-3.3-70b,gpt-4o-mini --notes 20

Both models read the same stored material (no re-fetch, no network - reanalyze.py
already proved that works). Their proposals are recorded side by side. Then, as you
judge those notes over the following days, `verivann bakeoff --results` tells you which
model actually agreed with *you* more often, on *your* material, in *your* language.

That is not a benchmark. Benchmarks tell you which model is better at someone else's
questions. This tells you which model is better at yours.

Two disciplines make it honest:

* **The comparison is blind to cost and hype.** The only score is agreement with the
  human, and it is computed from the same ground truth as everything else.
* **A tie is reported as a tie.** With five judged notes there is no winner, and the
  tool says so instead of crowning one.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from .config import Config

MIN_JUDGED = 8  # below this, the "winner" is noise with a rosette


@dataclass
class Contender:
    model: str
    read: int = 0  # notes it analyzed
    judged: int = 0  # …of which you have since judged
    agreed: int = 0  # …and where its proposal matched your verdict

    @property
    def accuracy(self) -> float | None:
        return round(self.agreed / self.judged, 2) if self.judged else None


@dataclass
class Result:
    contenders: list[Contender] = field(default_factory=list)
    notes: int = 0

    @property
    def ready(self) -> bool:
        return all(c.judged >= MIN_JUDGED for c in self.contenders) and len(self.contenders) > 1

    def verdict(self) -> str:
        if len(self.contenders) < 2:
            return "Only one model has read anything. There is nothing to compare."
        if not self.ready:
            short = min(c.judged for c in self.contenders)
            return (
                f"Not decided: the models have read {self.notes} note(s), but you have only "
                f"judged {short} of them for one of the models. "
                f"{MIN_JUDGED} are needed. Judge more (`verivann list`, then keep/drop) and ask again."
            )
        ranked = sorted(self.contenders, key=lambda c: (c.accuracy or 0), reverse=True)
        best, second = ranked[0], ranked[1]
        if best.accuracy == second.accuracy:
            return (
                f"A tie: both agreed with you {int((best.accuracy or 0) * 100)}% of the time. "
                "On your material, the more expensive one is not buying you anything."
            )
        gap = int(((best.accuracy or 0) - (second.accuracy or 0)) * 100)
        return (
            f"**{best.model}** agreed with you {int((best.accuracy or 0) * 100)}% of the time; "
            f"{second.model} managed {int((second.accuracy or 0) * 100)}%. "
            f"{gap} points, on your own material, judged by you."
        )


def run(
    models: list[str],
    config: Config | None = None,
    limit: int = 20,
    lens: str | None = None,
    on_item=None,
) -> int:
    """Have each model read the same stored notes. Returns how many notes were read."""
    config = config or Config.load()
    if len(models) < 2 or not config.llm.enabled:
        return 0

    from dataclasses import replace

    from .library import bakeoff_record
    from .pipeline import judge
    from .reanalyze import _restore, pending

    notes = pending(config, everything=True)[:limit]
    for row in notes:
        extracted = _restore(row["event_path"])
        if extracted is None:
            continue
        for model in models:
            contender = replace(config, llm=replace(config.llm, model=model, models=[], fallback=None))
            try:
                result = judge(
                    row["source_kind"] or "text",
                    row["source_ref"] or "text",
                    extracted.model_copy(deep=True),
                    contender,
                    lens=lens,
                    note_id=row["id"],
                )
            except Exception:  # noqa: BLE001 - a model that refuses simply does not score
                continue
            bakeoff_record(
                row["id"], model, result.event.decision.action, result.event.routing.confidence,
                config.staging_dir,
            )
            if on_item:
                on_item(row["id"], model, result.event.decision.action)
    return len(notes)


def results(config: Config | None = None) -> Result:
    """Who was right - scored against the only ground truth there is: your verdicts."""
    config = config or Config.load()
    from .library import bakeoff_rows

    rows = bakeoff_rows(config.staging_dir)
    by_model: dict[str, Contender] = {}
    seen_notes: set[str] = set()

    for row in rows:
        seen_notes.add(row["note_id"])
        contender = by_model.setdefault(row["model"], Contender(model=row["model"]))
        contender.read += 1
        if not row["verdict"]:
            continue
        contender.judged += 1
        proposed_keep = row["proposed"] in ("note", "task", "memory")
        if (row["verdict"] == "kept") == proposed_keep:
            contender.agreed += 1

    return Result(contenders=list(by_model.values()), notes=len(seen_notes))


def staging(config: Config) -> Path:
    return config.staging_dir
