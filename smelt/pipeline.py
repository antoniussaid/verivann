"""The pipeline: source -> extract -> analyze -> route -> propose -> render -> stage.

This is the whole orchestration. Note what it does NOT do: it does not write to
any memory, and it does not touch any real private structure path. It proposes and stages.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

from . import __version__
from .adapters import extract_media, extract_reddit, extract_text, extract_webpage
from .adapters.archive import archive_all
from .analysis.analyzer import analyze
from .canonical import canonical_url
from .config import Config
from .privacy import REDACTED, classify, explain, mode_for
from .redact import redact
from .registry import DomainRegistry
from .render import render_json, render_markdown
from .schema import Decision, Extracted, IntakeEvent, Provenance, Routing, Source
from .security import Finding, scan_injection, scan_interest, trust_level
from .sources import identify, material_minutes
from .storage import artifact_stem, write_artifacts

# URLs on these hosts are better read by yt-dlp than by the HTML webpage adapter
# (they are JS apps whose content isn't in the raw HTML).
_MEDIA_HOSTS = (
    "youtube.com", "youtu.be", "tiktok.com", "instagram.com",
    "twitter.com", "x.com", "facebook.com", "vimeo.com", "twitch.tv",
)


def _is_media_host(url: str) -> bool:
    host = (urlparse(url).hostname or "").lower()
    host = host[4:] if host.startswith("www.") else host
    return any(host == h or host.endswith("." + h) for h in _MEDIA_HOSTS)


def _is_reddit_host(url: str) -> bool:
    host = (urlparse(url).hostname or "").lower()
    return host == "reddit.com" or host.endswith(".reddit.com")


@dataclass
class IntakeResult:
    event: IntakeEvent
    note_path: Path
    event_path: Path


def _existing_id(ref: str, kind: str, config: Config) -> str | None:
    if kind == "text":
        return None
    try:
        from .library import find_by_ref

        return find_by_ref(ref, config.staging_dir)
    except Exception:  # noqa: BLE001 - dedup is an optimization, never a blocker
        return None


def _extract(kind: str, ref: str, text: str | None, subs_dir: Path) -> Extracted:
    if kind == "text":
        return extract_text(text or ref)
    if kind == "file":  # a screenshot, a voice memo, a PDF — see adapters/local.py
        from .adapters.local import extract_file

        return extract_file(Path(ref))
    if kind == "youtube":
        return extract_media(ref, subs_dir)
    if kind == "url":
        if _is_reddit_host(ref):
            return extract_reddit(ref)  # structured post + comments via JSON
        from .adapters.gallery import extract_gallery, is_gallery_url

        if is_gallery_url(ref):
            gallery = extract_gallery(ref, subs_dir)
            if gallery is not None:
                return gallery  # gallery-dl present → images (+ OCR); else fall through
        # Video platforms (TikTok, Instagram, X…) are JS apps — use yt-dlp for them.
        return extract_media(ref, subs_dir) if _is_media_host(ref) else extract_webpage(ref)
    raise ValueError(f"unknown source kind: {kind}")


def run(
    kind: str,
    ref: str,
    text: str | None = None,
    config: Config | None = None,
    lens: str | None = None,
    extra_meta: dict | None = None,
) -> IntakeResult:
    """Fetch the material, then judge it.

    `extra_meta` is how a caller adds context the extractor cannot know — e.g. the
    watchlist handing over the diff of what this source used to say.
    """
    config = config or Config.load()

    # One source, one identity: a link is cleaned of copy-paste debris and
    # tracking noise BEFORE it is fetched, stored, or compared (see canonical.py).
    if kind in ("url", "youtube"):
        ref = canonical_url(ref)

    extracted = _extract(kind, ref, text, subs_dir=config.staging_dir / ".subs")
    if extra_meta:
        extracted.meta.update(extra_meta)
    return judge(kind, ref, extracted, config, lens)


def judge(
    kind: str,
    ref: str,
    extracted: Extracted,
    config: Config | None = None,
    lens: str | None = None,
    note_id: str | None = None,
) -> IntakeResult:
    """Everything that happens AFTER the material is in hand.

    Split out from `run()` for one reason that turned out to matter: material that
    was already fetched can be judged again — by a better model, with a different
    lens — without going back to the network (see reanalyze.py). Nothing here
    touches a source; it only reads what we already have.
    """
    config = config or Config.load()
    registry = DomainRegistry(config.domains)

    # What is this material trying to do? Scanned BEFORE any model sees it: text
    # aimed at the analyzer (injection) downgrades trust to "hostile" and marks the
    # source permanently; sponsorships and affiliate funnels are surfaced above the
    # summary. Offline, no model needed — see security.py.
    meta = extracted.meta or {}
    injection = scan_injection(
        extracted.text,
        hidden_text=str(meta.get("hidden_text") or ""),
        links=str(meta.get("links") or ""),
        # Text that came out of an image or out of speech never passed a web
        # sanitizer. A poster in a video is an attack surface; so is a podcast.
        ocr_text=str(meta.get("onscreen_text") or meta.get("ocr_text") or ""),
        transcript=str(meta.get("transcript_text") or ""),
    )
    interest = scan_interest(extracted.text, str(meta.get("links") or ""))
    if injection:
        extracted.meta["injection"] = [vars(f) for f in injection]
    if interest:
        extracted.meta["interest"] = [vars(f) for f in interest]

    # Where is this material allowed to be read? Anything off your own disk, or
    # carrying an IBAN or a diagnosis, is `sensitive`: it goes to the local model, or
    # to a hosted one ONLY after local redaction, or to nobody. It is never silently
    # uploaded. See privacy.py and redact.py.
    sensitivity, why = classify(kind, extracted.text, extracted.meta)
    llm, stayed_local, mode = mode_for(config, sensitivity)
    read_config = replace(config, llm=llm)

    # Redaction happens HERE, on the way out — the analyzer sees the placeholder text,
    # the library keeps the original, and the mapping never leaves this function.
    redaction = None
    material = extracted
    if mode == REDACTED:
        redaction = redact(extracted.text)
        material = Extracted(
            title=redact(extracted.title).text, text=redaction.text, meta=dict(extracted.meta)
        )

    extracted.meta["sensitivity"] = sensitivity
    extracted.meta["privacy"] = explain(
        sensitivity, why, llm, stayed_local, mode, redaction.summary() if redaction else ""
    )
    extracted.meta["analyzed_locally"] = stayed_local
    extracted.meta["privacy_mode"] = mode

    # Learned relevance: what has this reader kept, what have they dropped?
    # (Silent until enough verdicts exist — see relevance.MIN_SIGNAL.)
    try:
        from .relevance import apply_profile, load_profile

        profile = load_profile(config.staging_dir)
    except Exception:  # noqa: BLE001 - the profile is an optimization, never a requirement
        profile = None

    analysis = analyze(
        material, read_config, lens=lens, preference=(profile.hint() if profile else "")
    )
    if redaction is not None:
        # The model answered in placeholders. Put the truth back — locally.
        analysis.summary = redaction.restore(analysis.summary)
        analysis.reason = redaction.restore(analysis.reason)
        for field_name in ("useful_ideas", "claims_to_verify", "possible_actions"):
            setattr(
                analysis, field_name,
                [redaction.restore(item) for item in getattr(analysis, field_name)],
            )
    if profile is not None and analysis.engine == "heuristic":
        analysis = apply_profile(analysis, extracted, profile)  # LLM runs get hint() instead
    extracted.meta["lens"] = analysis.lens
    if analysis.predictions:
        extracted.meta["predictions"] = analysis.predictions
    if analysis.shelf_life_days:
        extracted.meta["shelf_life_days"] = analysis.shelf_life_days
    domain = registry.resolve(analysis.domain)

    now = datetime.now(timezone.utc)
    stem = artifact_stem(now.strftime("%Y-%m-%d"), kind, extracted.title, ref)
    target = str(config.staging_dir / "notes" / f"{stem}.md")

    # Idempotency: the same source digested twice is the SAME note, re-read — not a
    # second one. The note file was always overwritten; the library used to grow a
    # duplicate row. Re-using the id keeps one row, one claim set, one verdict.
    note_id = note_id or _existing_id(ref, kind, config) or str(uuid.uuid4())

    # Optional raw archive of the page (opt-in; skipped for video-platform pages).
    # The note is an interpretation — this is the evidence it was made from.
    if kind == "url" and not _is_media_host(ref):
        snapshots = archive_all(ref, config.staging_dir / "raw", stem)
        if snapshots:
            extracted.meta["raw_archive"] = snapshots

    # Connections: what is already in the library that relates to this?
    try:
        from .retrieval import related as find_related

        related = find_related(
            f"{extracted.title} {extracted.text[:1200]}",
            config,
            exclude_ref=(ref if kind != "text" else ""),
            limit=3,
        )
        if related:
            extracted.meta["related"] = [
                {"title": h.title, "note": h.note_path, "domain": h.domain} for h in related
            ]
    except Exception:  # noqa: BLE001 - connections are best-effort
        pass

    # The real routing target: does this advance anything you are trying to find out?
    # An empty answer is not a failure — it is the honest verdict that this material,
    # whatever else it is, moved none of your open questions forward.
    # NOTE: every model call below uses `read_config`, not `config` — the privacy
    # slot decision must hold for the whole intake, not just for the summary. A
    # side door is still a door.
    try:
        from .questions import listing as open_questions
        from .questions import match as match_questions

        matches = match_questions(extracted, note_id, read_config)
        if matches:
            extracted.meta["questions"] = matches
        elif read_config.llm.enabled and open_questions(read_config):
            extracted.meta["questions_none"] = True
    except Exception:  # noqa: BLE001 - the register must never fail an intake
        pass

    # Claim ledger: does this contradict something already on record? (LLM only.)
    try:
        from .claims import check_contradictions

        conflicts = check_contradictions(
            analysis.claims_to_verify, read_config, config.staging_dir, exclude_note=note_id
        )
        if conflicts:
            extracted.meta["contradictions"] = conflicts
    except Exception:  # noqa: BLE001 - contradiction checking is best-effort
        pass

    # The canary came back (analysis/llm.py): the material did not merely TRY to give
    # the analyzer orders — it succeeded. That is no longer a suspicion, and the note
    # and the source's record both say so in the strongest terms we have.
    if extracted.meta.get("hijacked"):
        injection = list(injection) + [
            Finding(
                kind="ANALYZER HIJACKED (canary token leaked)",
                quote=str(extracted.meta["hijacked"].get("evidence", "")),
                where="text",
            )
        ]
        extracted.meta["injection"] = [vars(f) for f in injection]

    # The source's own record — what it has been right about, wrong about, and
    # whether it has ever tried to manipulate the analyzer. Read before the summary.
    source_key, source_label = identify(kind, ref, extracted)
    extracted.meta["source_key"] = source_key
    extracted.meta["source_label"] = source_label
    extracted.meta["minutes"] = material_minutes(extracted)
    try:
        from .library import mark_source, source_standing

        if injection:
            mark_source(source_key, "hostile", config.staging_dir)
        standing = source_standing(source_key, config.staging_dir)
        if standing and standing["notes"]:
            extracted.meta["source_record"] = standing
    except Exception:  # noqa: BLE001 - the record is context, never a blocker
        pass

    event = IntakeEvent(
        id=note_id,
        created_at=now.isoformat(),
        source=Source(kind=kind, ref="text" if kind == "text" else ref),
        extracted=extracted,
        routing=Routing(domain=domain, confidence=analysis.confidence, reason=analysis.reason),
        decision=Decision(action=analysis.action, target=target),
        provenance=Provenance(
            tool="smelt",
            version=__version__,
            public_demo=config.public_demo,
            content_trust=trust_level(injection),
        ),
    )

    note_path, event_path = write_artifacts(
        config.staging_dir, stem, render_markdown(event, analysis), render_json(event)
    )

    # Index into the searchable library + claim ledger (best-effort — never fail
    # an intake over bookkeeping).
    try:
        from .library import index_claims, index_event, log_event

        index_event(
            event,
            str(note_path),
            str(event_path),
            config.staging_dir,
            ideas=len(analysis.useful_ideas),  # the numerator of this source's yield
            engine=analysis.engine,  # …and whether anyone actually read it
            lens=analysis.lens,  # …with what intent (calibration compares lenses)
            sensitivity=str(extracted.meta.get("sensitivity", "public")),
        )
        log_event("intake", event.id, f"{kind}:{extracted.title[:60]}", config.staging_dir)
        index_claims(
            event.id,
            analysis.claims_to_verify,
            config.staging_dir,
            shelf_life_days=analysis.shelf_life_days,  # when this should be re-checked
        )
    except Exception:  # noqa: BLE001
        pass

    # Claims about the future go on the scoreboard, with a date and an owner.
    try:
        from .predictions import record as record_predictions

        record_predictions(event.id, source_key, analysis.predictions, config.staging_dir)
    except Exception:  # noqa: BLE001 - the ledger must never fail an intake
        pass

    # Meaning-search index (opt-in: SMELT_EMBED_MODEL). Best-effort by design.
    try:
        from .embed import index_note

        index_note(event.id, f"{extracted.title}\n{extracted.text[:4000]}", config)
    except Exception:  # noqa: BLE001
        pass

    return IntakeResult(event=event, note_path=note_path, event_path=event_path)
