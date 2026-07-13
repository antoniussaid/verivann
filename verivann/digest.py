"""The ingot — a week, poured into one document.

Not a newsletter and not a dashboard. A weekly digest that leads with what
survived, then names what contradicted itself, what came due, what went stale, and
what you never even looked at. The unflattering parts are not an appendix; they
are the point.

    verivann digest              the last 7 days, to stdout
    verivann digest --days 30 --out week.md

Also here: `verivann export anki` — cards, but ONLY from notes you kept. A tool that
drills you on material you already decided was noise is worse than no tool.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from .config import Config


def digest(config: Config | None = None, days: int = 7) -> str:
    config = config or Config.load()
    staging = config.staging_dir

    from .library import dropped_rows, kept_rows, stale_claims
    from .predictions import listing
    from .stats import mirror

    m = mirror(staging, days)
    kept = kept_rows(staging, since_days=days)
    dropped = dropped_rows(staging, limit=10)
    due = [p for p in listing(staging) if p.is_due]
    stale = stale_claims(staging, limit=8)
    today = datetime.now(timezone.utc).date().isoformat()

    out: list[str] = [
        f"# Verivann — the last {days} days",
        "",
        f"_{today}_",
        "",
        "## The number",
        "",
        m.verdict(),
        "",
        f"- material in: **{m.hours} h** ({m.notes} notes)",
        f"- judged: {m.kept} kept · {m.dropped} dropped · {m.unjudged} never judged",
        f"- read by a model: {m.analyzed}/{m.notes}",
    ]
    if m.hostile:
        out.append(f"- manipulation attempts on record: **{m.hostile}**")

    out += ["", "## What survived", ""]
    if kept:
        for row in kept:
            out.append(f"- **{row['title'][:70]}** — _{row['source']}_")
    else:
        out.append("_Nothing. You kept nothing this week._")

    if due:
        out += ["", "## Predictions that came due", ""]
        for p in due:
            out.append(f"- `{p.due}` **{p.text}** — {p.source_label}")
            out.append(f"  - judge it: `verivann resolve {p.id} --hit|--miss`")

    if stale:
        out += ["", "## What you believe may no longer be true", ""]
        for row in stale:
            out.append(f"- {row['claim']} _(expired {row['expires_at'][:10]}, {row['source']})_")

    if m.time_sinks:
        out += ["", "## Where the time went", ""]
        for source, minutes, kept_count in m.time_sinks:
            share = f"{minutes:g} min → {kept_count} kept"
            out.append(f"- {source} — {share}")

    if dropped:
        out += ["", "## The slag (what you threw away)", ""]
        for row in dropped:
            out.append(f"- {row['title'][:70]} _({row['source']})_")

    out += [
        "",
        "---",
        "",
        "_Every line above is a proposal or a record. Nothing here was committed to memory._",
        "",
    ]
    return "\n".join(out)


def anki(config: Config | None = None, limit: int = 200) -> str:
    """Cards from notes you KEPT. Tab-separated: front, back, tags — Anki reads it directly."""
    config = config or Config.load()
    from .library import kept_rows

    lines: list[str] = ["#separator:tab", "#html:false", "#tags column:3"]
    for row in kept_rows(config.staging_dir, limit=limit):
        for idea in _ideas(row["note_path"]):
            front = f"{row['title'][:90]} — what was the point?" if len(idea) > 120 else idea
            back = idea if front != idea else row["title"]
            lines.append(f"{_clean(front)}\t{_clean(back)}\t{row['domain']}")
    return "\n".join(lines) + "\n"


def _ideas(note_path: str) -> list[str]:
    """The bullet list under the note's ideas heading — whatever the lens called it."""
    try:
        text = Path(note_path).read_text(encoding="utf-8")
    except OSError:
        return []
    ideas: list[str] = []
    capturing = False
    for line in text.splitlines():
        if line.startswith("## "):
            capturing = line[3:].strip() in (
                "Useful ideas", "Insights", "Weak points", "Key concepts", "What changes a decision",
            )
            continue
        if capturing and line.startswith("- ") and "_(add on review)_" not in line:
            ideas.append(line[2:].strip())
    return ideas[:5]


def _clean(text: str) -> str:
    return text.replace("\t", " ").replace("\n", " ").strip()
