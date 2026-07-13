"""The router, measured against the only truth there is: yours.

We keep a permanent record of every source — right, wrong, manipulative. And we
have never once asked the same question about **ourselves**, although the answer
is sitting in the same database: the analyzer makes a prediction on every intake
(a domain, an action, a confidence), and your keep/drop verdicts say whether it
was any good.

    verivann calibrate

  keeper precision   of the notes it proposed as note/task, how many did you keep?
  drop precision     of those it proposed dropping, how many did you drop?
  by confidence      in the 0.8–1.0 bucket, what share survived? A model whose 0.9s
                     survive at 30 % is not confident, it is loud.
  by engine / lens   heuristic vs llm:<model>; critique vs digest. Which reads YOUR
                     material better — measured, not assumed.

Two honesty rules, both load-bearing:

* **Below MIN_JUDGED it refuses to report.** A precision computed on five samples
  is a horoscope with a decimal point.
* **Inferred verdicts count less.** A note you ignored is weaker evidence than one
  you threw away, and the numbers say which is which (`explicit` vs `implicit`).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

MIN_JUDGED = 10  # below this, there is no number worth printing

_BUCKETS = ((0.0, 0.5), (0.5, 0.8), (0.8, 1.01))


@dataclass
class Bucket:
    low: float
    high: float
    n: int = 0
    kept: int = 0

    @property
    def survival(self) -> float | None:
        return round(self.kept / self.n, 2) if self.n else None

    def label(self) -> str:
        return f"{self.low:.1f}–{min(self.high, 1.0):.1f}"


@dataclass
class Slice:
    name: str
    n: int = 0
    correct: int = 0

    @property
    def accuracy(self) -> float | None:
        return round(self.correct / self.n, 2) if self.n else None


@dataclass
class Report:
    judged: int = 0
    explicit: int = 0
    keeper_proposed: int = 0
    keeper_kept: int = 0
    drop_proposed: int = 0
    drop_dropped: int = 0
    buckets: list[Bucket] = field(default_factory=list)
    engines: list[Slice] = field(default_factory=list)
    lenses: list[Slice] = field(default_factory=list)

    @property
    def enough(self) -> bool:
        return self.judged >= MIN_JUDGED

    @property
    def keeper_precision(self) -> float | None:
        return round(self.keeper_kept / self.keeper_proposed, 2) if self.keeper_proposed else None

    @property
    def drop_precision(self) -> float | None:
        return round(self.drop_dropped / self.drop_proposed, 2) if self.drop_proposed else None

    @property
    def accuracy(self) -> float | None:
        total = self.keeper_proposed + self.drop_proposed
        if not total:
            return None
        return round((self.keeper_kept + self.drop_dropped) / total, 2)

    def calibrated(self) -> bool | None:
        """Does higher confidence actually mean higher survival? (Monotonic buckets.)"""
        rates = [b.survival for b in self.buckets if b.survival is not None and b.n >= 3]
        if len(rates) < 2:
            return None
        return all(a <= b for a, b in zip(rates, rates[1:], strict=False))

    def headline(self) -> str:
        if not self.enough:
            return (
                f"Only {self.judged} judged note(s) — not enough to measure the router. "
                f"({MIN_JUDGED} needed; a precision on five samples is a horoscope.)"
            )
        parts = [f"The router agreed with you {int((self.accuracy or 0) * 100)}% of the time"]
        if self.keeper_precision is not None and self.keeper_precision < 0.5:
            parts.append(
                f"it proposed keeping {self.keeper_proposed} note(s) and you kept "
                f"{self.keeper_kept} — it over-proposes"
            )
        if self.calibrated() is False:
            parts.append("and its confidence is NOT calibrated: being surer did not make it righter")
        return ". ".join(parts) + "."


def calibrate(staging_dir: Path) -> Report:
    from .library import judged_rows

    rows = judged_rows(staging_dir)
    report = Report(judged=len(rows))
    report.explicit = sum(1 for r in rows if r["origin"] == "explicit")
    report.buckets = [Bucket(low, high) for low, high in _BUCKETS]

    engines: dict[str, Slice] = {}
    lenses: dict[str, Slice] = {}

    for row in rows:
        kept = row["verdict"] == "kept"
        proposed_keep = row["proposed"] in ("note", "task", "memory")

        if proposed_keep:
            report.keeper_proposed += 1
            report.keeper_kept += int(kept)
        elif row["proposed"] == "drop":
            report.drop_proposed += 1
            report.drop_dropped += int(not kept)

        for bucket in report.buckets:
            if bucket.low <= (row["confidence"] or 0.0) < bucket.high:
                bucket.n += 1
                bucket.kept += int(kept)
                break

        correct = int(kept == proposed_keep)
        engines.setdefault(row["engine"], Slice(row["engine"])).n += 1
        engines[row["engine"]].correct += correct
        lenses.setdefault(row["lens"], Slice(row["lens"])).n += 1
        lenses[row["lens"]].correct += correct

    report.engines = sorted(engines.values(), key=lambda s: -s.n)
    report.lenses = sorted(lenses.values(), key=lambda s: -s.n)
    return report
