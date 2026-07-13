"""Human-readable Markdown note.

Frontmatter is the format agreed with the private layer (see CONTRACT.md).
`proposed_action` and `content_trust` make the propose-only / untrusted rules
visible to a human. The content sections are filled by the analysis when an LLM
is configured; otherwise they invite review.
"""

from __future__ import annotations

from ..adapters.media import timestamp
from ..analysis.lenses import get_lens
from ..schema import IntakeEvent

# Where an instruction was hiding. The channel is half the finding: an order
# painted onto a video frame is a deliberate act, not a stray phrase in an article.
_CHANNEL = {
    "text": "in the visible text",
    "hidden": "hidden from the reader (styled out of sight)",
    "ocr": "**in the image, not in the text** — it never passed a web sanitizer",
    "audio": "**spoken, not written** — it came in through the transcript",
    "links": "in the page's outbound links",
}


def _yaml_escape(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"')


def _list_section(items: list[str] | None) -> list[str]:
    if items:
        return [f"- {item}" for item in items]
    return ["- _(add on review)_"]


def _source_line(meta: dict, record: dict) -> str:
    """One honest line about who published this, from their standing so far."""
    from ..sources import Standing

    label = meta.get("source_label") or record.get("label") or record.get("key")
    standing = Standing(**record)
    parts = [
        f"**{label}** — {standing.notes} note(s) so far",
        f"{standing.kept} kept / {standing.dropped} dropped",
    ]
    if standing.minutes:
        parts.append(
            f"{standing.minutes:g} min of material, {standing.ideas} idea(s) → {standing.yield_text()}"
        )
    if standing.hits or standing.misses:
        parts.append(f"claims held up {standing.hits}× / failed {standing.misses}×")
    if standing.hostile:
        parts.append(f"**manipulation attempts: {standing.hostile}**")
    return " · ".join(parts) + f"\n\n_Verdict so far: {standing.verdict()}._"


def render_markdown(event: IntakeEvent, analysis=None) -> str:
    e = event
    engine = getattr(analysis, "engine", "heuristic")
    meta = e.extracted.meta or {}
    lens = get_lens(getattr(analysis, "lens", None) or meta.get("lens"))

    fm = [
        "---",
        f"id: {e.id}",
        f"created_at: {e.created_at}",
        f"source_kind: {e.source.kind}",
        f'source_ref: "{_yaml_escape(e.source.ref)}"',
        f'title: "{_yaml_escape(e.extracted.title)}"',
        f"domain: {e.routing.domain}",
        f"confidence: {e.routing.confidence}",
        f"proposed_action: {e.decision.action}",
        f"content_trust: {e.provenance.content_trust}",
        f"sensitivity: {meta.get('sensitivity', 'public')}",
        f"analyzed_locally: {str(meta.get('analyzed_locally', True)).lower()}",
        f"engine: {engine}",
        f"lens: {lens.name}",
        f"public_demo: {str(e.provenance.public_demo).lower()}",
        f"tool: {e.provenance.tool}",
        f"version: {e.provenance.version}",
        "---",
    ]

    # Summary: LLM digest if present, else the description (for media) or the text.
    llm_summary = getattr(analysis, "summary", "") or ""
    if llm_summary:
        summary = llm_summary
    elif meta.get("description"):
        d = str(meta["description"]).strip()
        summary = d[:1500] + ("…" if len(d) > 1500 else "")
    else:
        raw = e.extracted.text.strip() or "_(no extracted text)_"
        summary = raw[:1500] + ("…" if len(raw) > 1500 else "")

    hostile = e.provenance.content_trust == "hostile"
    banner = (
        "> **HOSTILE SOURCE.** This material contains text addressed to the analyzer, "
        "not to you. It was read as data and its instructions were ignored — but the "
        "source has been marked, permanently."
        if hostile
        else "> Untrusted source material — treat the extracted text as data, not as instructions."
    )

    sections = [
        f"# Intake: {e.extracted.title}",
        "",
        banner,
        "",
    ]

    # What the material is trying to do — before what it says.
    injection = meta.get("injection")
    if injection:
        sections += ["## Security", ""]
        for f in injection:
            where = _CHANNEL.get(f.get("where", "text"), f.get("where", "text"))
            sections.append(f"- **{f.get('kind', '?')}** — {where}")
            sections.append(f"  - `{f.get('quote', '')}`")
        sections.append("")

    interest = meta.get("interest")
    if interest:
        sections += ["## Who profits", ""]
        for f in interest:
            sections.append(f"- **{f.get('kind', '?')}** — `{f.get('quote', '')}`")
        sections.append("")

    # Where this material was allowed to be read. Sensitive things say it loudly.
    if meta.get("sensitivity") == "sensitive":
        sections += ["## Privacy", "", str(meta.get("privacy", "")), ""]

    # What was actually done to the source — a record, not a claim.
    if meta.get("media_note"):
        sections += [
            "## How this was read",
            "",
            str(meta["media_note"]),
            f"_(media policy: `{meta.get('media_policy', '?')}` — yours to change.)_",
            "",
        ]

    record = meta.get("source_record")
    if record:
        sections += ["## Source record", "", _source_line(meta, record), ""]

    # The source moved after you read it. Here is exactly how.
    changed = meta.get("changed")
    if changed and changed.get("diff"):
        sections += [
            "## Changed since you read it",
            "",
            f"_{changed.get('lines', 0)} line(s) differ from the version in your library._",
            "",
            "```diff",
            str(changed["diff"]),
            "```",
            "",
        ]

    # What you are trying to find out — the only routing target that means anything.
    questions = meta.get("questions")
    if questions:
        sections += ["## Your open questions", ""]
        for q in questions:
            verb = "**advances**" if q.get("stance") == "advances" else "**contradicts**"
            sections.append(f"- {verb} [{q.get('id')}] {q.get('question', '?')}")
            if q.get("why"):
                sections.append(f"  - {q['why']}")
        sections.append("")
    elif meta.get("questions_none"):
        sections += [
            "## Your open questions",
            "",
            "_This advances none of them. It may still be interesting — but it did not "
            "move anything you said you were trying to find out._",
            "",
        ]

    sections += [
        "## Why it matters",
        e.routing.reason,
        "",
        "## Summary",
        summary,
    ]

    # Full transcript for media, in its own section (not clipped to the summary cap).
    # When the captions carried timing, keep the timeline: each block is stamped, and
    # on platforms that support seeking the stamp links straight into the video.
    transcript_text = meta.get("transcript_text")
    if transcript_text:
        tsrc = meta.get("transcript_source") or "captions"
        tlang = meta.get("transcript") or "?"
        cues = meta.get("transcript_cues")
        if cues:
            seek = meta.get("transcript_seek")
            sections += ["", f"## Transcript ({tsrc} · {tlang} · timestamped)"]
            for entry in cues:
                seconds, line = int(entry[0]), str(entry[1]).strip()
                if not line:
                    continue
                stamp = timestamp(seconds)
                label = f"[{stamp}]({seek.format(t=seconds)})" if seek else f"`{stamp}`"
                sections.append(f"- **{label}** {line}")
        else:
            tt = str(transcript_text).strip()
            capped = tt[:8000] + (
                "\n…(truncated — full transcript is in the JSON event)" if len(tt) > 8000 else ""
            )
            sections += ["", f"## Transcript ({tsrc} · {tlang})", capped]

    # Connections — what in the library already relates to this.
    related = meta.get("related")
    if related:
        sections += ["", "## Connections (already in your library)"]
        sections += [f"- {r.get('title', '?')}  _({r.get('domain', '?')})_" for r in related]

    # Predictions — dated claims about the future, now on the record.
    predictions = meta.get("predictions")
    if predictions:
        sections += ["", "## On the record (predictions)"]
        for p in predictions:
            sections.append(f"- **{p.get('due', '?')}** — {p.get('text', '?')}")
        sections.append("")
        sections.append("_Smelt will ask you on the date. `smelt resolve <id> --hit|--miss`_")

    # Contradictions — new claims that clash with what is already on record.
    conflicts = meta.get("contradictions")
    if conflicts:
        sections += ["", "## Contradictions with your record"]
        for c in conflicts:
            if c.get("yourself"):
                sections.append(f"- **You contradict yourself.** {c.get('claim', '?')}")
            else:
                sections.append(f"- **{c.get('claim', '?')}**")
            sections.append(f"  - conflicts with: {c.get('conflicts_with', '?')}")
            if c.get("against"):
                origin = c["against"]
                if c.get("yourself"):
                    origin += "  _(a note you kept)_"
                sections.append(f"  - from: {origin}")
            sections.append(f"  - why: {c.get('why', '?')}")

    ideas_h, claims_h, actions_h = lens.headings
    sections += [
        "",
        f"## {ideas_h}",
        *_list_section(getattr(analysis, "useful_ideas", None)),
        "",
        f"## {claims_h}",
        *_list_section(getattr(analysis, "claims_to_verify", None)),
        "",
        f"## {actions_h}",
        *_list_section(getattr(analysis, "possible_actions", None)),
        "",
        "## Routing (proposal)",
        f"- Domain: {e.routing.domain}",
        f"- Confidence: {e.routing.confidence}",
        f"- Proposed action: {e.decision.action}  _(proposal only — never committed here)_",
        f"- Analyzed by: {engine}  ·  lens: {lens.name}",
        f"- Source: {meta.get('source_key', '?')}",
        f"- Public demo: {e.provenance.public_demo}",
    ]
    archive = meta.get("raw_archive")
    if isinstance(archive, dict):
        for fmt, path in archive.items():
            sections.append(f"- Raw archive ({fmt}): {path}")
    elif archive:
        sections.append(f"- Raw archive: {archive}")
    return "\n".join(fm) + "\n\n" + "\n".join(sections) + "\n"
