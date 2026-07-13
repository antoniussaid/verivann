"""Verivann CLI."""

from __future__ import annotations

import os
import shutil
import sys
from datetime import datetime
from pathlib import Path

import typer

from . import __version__
from .config import Config
from .pipeline import IntakeResult, run

app = typer.Typer(
    add_completion=False,
    help="Verivann — raw web material -> structured, routed notes.",
    invoke_without_command=True,
)


@app.callback()
def cockpit_default(ctx: typer.Context) -> None:
    """With no command, Verivann shows what is due — not a menu of thirty verbs."""
    if ctx.invoked_subcommand is not None:
        return

    from .cockpit import load, mark_seen

    view = load()
    typer.echo(f"\n  {view.headline()}\n")

    if view.due_predictions:
        typer.echo("  Due:")
        for p in view.due_predictions[:5]:
            typer.echo(f"    [{p.id}] {p.text[:60]}")
            typer.echo(f"         {p.source_label[:34]} · due {p.due} · verivann resolve {p.id} --hit|--miss")
    if view.hostile_sources:
        typer.echo("\n  Caught manipulating the analyzer:")
        for s in view.hostile_sources[:3]:
            typer.echo(f"    {s['label'][:44]} ({s['hostile']}×)")
    if view.changed_sources:
        typer.echo("\n  Changed after you read them:")
        for w in view.changed_sources[:3]:
            typer.echo(f"    {w['label'][:44]} ({w['changes']}×)  verivann watch run")
    if view.questions_moved:
        typer.echo("\n  Questions with evidence:")
        for q in view.questions_moved[:4]:
            typer.echo(f"    [{q.id}] {q.text[:52]}  ({q.evidence} for / {q.against} against)")
    if view.implied_drops or view.unjudged or view.stale_claims:
        typer.echo("\n  Waiting on you:")
        if view.unjudged:
            typer.echo(f"    {view.unjudged} note(s) never judged        verivann list")
        if view.implied_drops:
            typer.echo(f"    {view.implied_drops} note(s) ignored for 30+ days   verivann review")
        if view.stale_claims:
            typer.echo(f"    {view.stale_claims} claim(s) past their shelf life  verivann stale")
    if view.calibration:
        typer.echo(f"\n  The router itself: {view.calibration}")

    typer.echo("")
    mark_seen()


def _report(result: IntakeResult) -> None:
    e = result.event
    typer.echo(f"  id         : {e.id}")
    typer.echo(f"  domain     : {e.routing.domain}  (confidence {e.routing.confidence})")
    typer.echo(f"  proposal   : {e.decision.action}  (proposal only, never committed)")
    typer.echo(f"  reason     : {e.routing.reason}")
    typer.echo(f"  note       : {result.note_path}")
    typer.echo(f"  event      : {result.event_path}")


_LENS_OPT = typer.Option(None, "--lens", "-l", help="Reading intent: see `verivann lenses`.")


@app.command("setup")
def setup_cmd() -> None:
    """First run: connect a model, write your config, and open the inbox."""
    from .setup import PRESETS, compose_env, preset, write_env

    typer.echo("\n  Verivann setup\n")
    typer.echo("  Everything works offline without a model — but a model is where it comes alive")
    typer.echo("  (summaries, claims, predictions, the credibility ledger). Let's connect one.\n")
    typer.echo("  Providers (the free ones are first):\n")
    for i, p in enumerate(PRESETS, 1):
        tag = "free" if p.free else "paid"
        tag = "local · free" if p.local else tag
        typer.echo(f"    {i}) {p.label:<44} [{tag}]")
        typer.echo(f"       {p.hint}")
    typer.echo(f"    {len(PRESETS) + 1}) Skip — run offline on the heuristic for now\n")

    choice = typer.prompt("  Which one", default=str(len(PRESETS) + 1))
    if not choice.isdigit() or int(choice) > len(PRESETS):
        typer.echo("\n  No model configured — Verivann will run on the offline heuristic.")
        typer.echo("  Re-run `verivann setup` any time. Opening the inbox…\n")
        _maybe_serve()
        return

    p = PRESETS[int(choice) - 1]
    account = typer.prompt("  Cloudflare account id") if p.needs_account else ""
    api_key = typer.prompt(f"  {p.label} API key", hide_input=True) if p.needs_key else ""
    model = typer.prompt("  Model", default=p.default_model) if p.default_model else typer.prompt("  Model")

    values = compose_env(p.key, account=account, api_key=api_key, model=model)
    env_path = Path(".env")
    if env_path.is_file():
        typer.echo(f"\n  {env_path} already exists — your model settings will be merged in.")
    write_env(env_path, values)

    shown = {k: (v if not k.endswith("API_KEY") else "•" * 8) for k, v in values.items()}
    typer.echo(f"\n  Wrote {env_path}:")
    for k, v in shown.items():
        typer.echo(f"    {k}={v}")
    if preset(p.key) and not preset(p.key).default_embed:
        typer.echo("\n  (This provider has no embeddings endpoint, so meaning-search stays off.")
        typer.echo("   Add a local one any time: VERIVANN_EMBED_MODEL=nomic-embed-text via Ollama.)")

    # Make the new settings live in THIS process so the probe and the first note use
    # them without a reload, then prove the connection instead of just hoping.
    for key, val in values.items():
        os.environ[key] = val

    from .setup import verify_connection, welcome_text

    typer.echo("\n  Testing the connection…")
    probe = verify_connection(Config.load().llm)
    if not probe.ok:
        typer.echo(f"  ⚠ Could not reach the model: {probe.detail}")
        typer.echo("    Your .env is saved — fix the setting above and re-run `verivann doctor`.\n")
        _maybe_serve()
        return

    typer.echo(f"  ✓ Connected — {probe.model} answered.")
    # Cold-start reward: a real first note, so the inbox opens with something in it.
    typer.echo("  Making your first note so the inbox isn't empty…")
    try:
        _, text = welcome_text()
        first = run("text", ref="text", text=text)
        typer.echo(f"  ✓ First note ready: {first.event.extracted.title[:60]}")
    except Exception as exc:  # noqa: BLE001 - the connection is proven; a note hiccup is minor
        typer.echo(f"  (Skipped the sample note: {str(exc)[:80]})")
    typer.echo("\n  Done. Check it any time with `verivann doctor`.\n")
    _maybe_serve()


def _maybe_serve() -> None:
    if typer.confirm("  Open the inbox now?", default=True):
        from .web import serve

        serve()


@app.command("ingest-text")
def ingest_text(
    text: str = typer.Argument(..., help="Arbitrary text to digest."),
    lens: str = _LENS_OPT,
) -> None:
    """Digest a raw text dump."""
    _report(run("text", ref="text", text=text, lens=lens))


@app.command("ingest-url")
def ingest_url(
    url: str = typer.Argument(..., help="Webpage/article URL."),
    lens: str = _LENS_OPT,
) -> None:
    """Digest a webpage (fetch + readable text, graceful fallback)."""
    _report(run("url", ref=url, lens=lens))


@app.command("ingest-youtube")
def ingest_youtube(
    url: str = typer.Argument(..., help="YouTube URL."),
    lens: str = _LENS_OPT,
) -> None:
    """Digest a YouTube video (captions/transcript via yt-dlp, graceful fallback)."""
    _report(run("youtube", ref=url, lens=lens))


@app.command("ingest-file")
def ingest_any_file(
    path: Path = typer.Argument(..., exists=True, readable=True, help="Image, audio, PDF, EPUB or text."),
    lens: str = _LENS_OPT,
) -> None:
    """Digest a file on disk — screenshot (OCR), voice memo (Whisper), PDF, EPUB, text."""
    from .adapters.local import SUPPORTED

    if path.suffix.lower() in SUPPORTED:
        _report(run("file", ref=str(path), lens=lens))
    else:
        _report(run("text", ref=str(path), text=path.read_text(encoding="utf-8"), lens=lens))


@app.command("folder")
def folder_cmd(
    folder: Path = typer.Argument(..., exists=True, file_okay=False, help="e.g. your screenshots folder."),
    recursive: bool = typer.Option(False, "--recursive", "-r"),
    keep_watching: bool = typer.Option(False, "--watch", help="Keep polling for new files."),
    lens: str = _LENS_OPT,
) -> None:
    """Digest every new file in a folder. Nothing is moved, renamed or deleted."""
    from .watchfolder import run_once, watch

    def report(batch) -> None:
        for item in batch:
            typer.echo(f"  [{item.domain:<8}] {item.title[:52]:<52} → {item.action}")
        typer.echo(f"  {len(batch)} new file(s) digested.\n")

    if keep_watching:
        typer.echo(f"  watching {folder} — Ctrl+C to stop\n")
        try:
            watch(folder, recursive=recursive, lens=lens, on_batch=report)
        except KeyboardInterrupt:
            typer.echo("\n  stopped.")
        return

    batch = run_once(folder, recursive=recursive, lens=lens)
    if not batch:
        typer.echo("  nothing new.")
        return
    report(batch)


import_app = typer.Typer(help="Bring in what you already have — and judge it.")
app.add_typer(import_app, name="import")


def _run_import(candidates, limit: int, dry_run: bool, lens: str | None) -> None:
    from .importer import ingest

    if not candidates:
        typer.echo("  nothing to import.")
        return
    typer.echo(f"  {len(candidates)} candidate(s) found.")
    if dry_run:
        for c in candidates[:limit]:
            typer.echo(f"    {c.title[:44] or c.ref[:44]:<44} {c.hint}")
        typer.echo(f"\n  (dry run — nothing was digested. Drop --dry-run to import up to {limit}.)")
        return

    def report(candidate, result) -> None:
        event = result.event
        typer.echo(f"    [{event.routing.domain:<8}] {event.extracted.title[:52]:<52} → {event.decision.action}")

    typer.echo("")
    outcome = ingest(candidates, limit=limit, lens=lens, on_item=report)
    typer.echo(
        f"\n  {outcome.imported} imported · {outcome.skipped} already known · {outcome.failed} failed"
    )
    if outcome.domains:
        spread = ", ".join(f"{n}× {d}" for d, n in sorted(outcome.domains.items(), key=lambda x: -x[1]))
        typer.echo(f"  routed: {spread}")
    typer.echo("  Now judge them — `verivann list`, then `verivann keep|drop <id>`.")


@import_app.command("urls")
def import_urls_cmd(
    path: Path = typer.Argument(..., exists=True, readable=True, help="A Pocket/Raindrop export, or any list."),
    limit: int = typer.Option(50, help="Safety bound."),
    dry_run: bool = typer.Option(False, "--dry-run"),
    lens: str = _LENS_OPT,
) -> None:
    """Import every URL in a file (any export format — we just take the links)."""
    from .importer import from_urls

    _run_import(from_urls(path), limit, dry_run, lens)


@import_app.command("obsidian")
def import_obsidian_cmd(
    vault: Path = typer.Argument(..., exists=True, file_okay=False, help="Your vault."),
    limit: int = typer.Option(50, help="Safety bound."),
    dry_run: bool = typer.Option(False, "--dry-run"),
    lens: str = _LENS_OPT,
) -> None:
    """Import an Obsidian vault. It is read, never written to — and treated as sensitive."""
    from .importer import from_obsidian

    _run_import(from_obsidian(vault), limit, dry_run, lens)


@import_app.command("history")
def import_history_cmd(
    days: int = typer.Option(60, help="How far back."),
    min_visits: int = typer.Option(3, help="A page you came back to is a page that mattered."),
    limit: int = typer.Option(30, help="Safety bound."),
    dry_run: bool = typer.Option(False, "--dry-run"),
    lens: str = _LENS_OPT,
) -> None:
    """Import the pages you actually returned to. The browser file is copied, never touched."""
    from .importer import from_history

    candidates = from_history(days=days, min_visits=min_visits)
    if not candidates:
        typer.echo("  no browser history found (Chrome/Edge/Brave), or nothing met the threshold.")
        return
    _run_import(candidates, limit, dry_run, lens)


question_app = typer.Typer(help="Your open questions — the real routing target.")
app.add_typer(question_app, name="question")


@question_app.command("add")
def question_add_cmd(text: str = typer.Argument(..., help="Something you are trying to find out.")) -> None:
    """Register an open question. Every intake is read against it from now on."""
    from .questions import add

    q = add(text)
    typer.echo(f"  [{q.id}] {q.text}")
    typer.echo("  (material that advances this will say so; material that advances nothing will say that too)")


@question_app.command("list")
def question_list_cmd(
    all_questions: bool = typer.Option(False, "--all", help="Include answered ones."),
) -> None:
    """Your open questions, and how much evidence each has gathered."""
    from .questions import listing

    rows = listing(include_answered=all_questions)
    if not rows:
        typer.echo("(no questions — `verivann question add \"...\"`)")
        return
    for q in rows:
        typer.echo(f"  {q.line()}\n")


@question_app.command("answer")
def question_answer_cmd(question_id: int = typer.Argument(...)) -> None:
    """Everything you gathered on one question, synthesized — with the gaps named."""
    from .questions import answer

    result = answer(question_id)
    if result is None:
        typer.echo(f"(no question with id {question_id})")
        raise typer.Exit(1)
    typer.echo(f"\n  {result.question}\n")
    if result.answer:
        for line in result.answer.splitlines():
            typer.echo(f"  {line}")
        typer.echo("")
    if not result.sources:
        typer.echo("  (no evidence gathered yet — digest material that speaks to it)")
        return
    typer.echo("  Sources:")
    for i, (title, source) in enumerate(result.sources, 1):
        typer.echo(f"    [{i}] {title[:56]}  — {source[:26]}")
    if not result.answer:
        typer.echo("\n  (no LLM configured — evidence only. Set VERIVANN_LLM for the synthesis.)")


@question_app.command("close")
def question_close_cmd(question_id: int = typer.Argument(...)) -> None:
    """Mark a question answered — it stops competing for new material."""
    from .questions import close

    typer.echo("  closed." if close(question_id) else f"(no question with id {question_id})")


@question_app.command("remove")
def question_remove_cmd(question_id: int = typer.Argument(...)) -> None:
    """Drop a question and its evidence links (the notes themselves stay)."""
    from .questions import remove

    typer.echo("  removed." if remove(question_id) else f"(no question with id {question_id})")


feed_app = typer.Typer(help="Feeds — read for you, filtered by what you actually keep.")
app.add_typer(feed_app, name="feed")


@feed_app.command("add")
def feed_add_cmd(url: str = typer.Argument(..., help="RSS or Atom URL.")) -> None:
    """Follow a feed. Verivann reads it; you only see what gets through."""
    from .feeds import add

    typer.echo(f"  following: {add(url)}")


@feed_app.command("list")
def feed_list_cmd() -> None:
    """Your feeds — and the share of their output that ever passes your filter."""
    from .feeds import subscriptions

    rows = subscriptions()
    if not rows:
        typer.echo("(no feeds — `verivann feed add <url>`)")
        return
    for row in rows:
        seen, passed = row["seen"] or 0, row["passed"] or 0
        rate = f"{int(passed / seen * 100)}%" if seen else "—"
        typer.echo(f"  {(row['title'] or row['url'])[:50]:<50} {passed}/{seen} passed ({rate})")
        typer.echo(f"     {row['url'][:72]}")


@feed_app.command("run")
def feed_run_cmd(lens: str = _LENS_OPT) -> None:
    """Read every feed. Digest what is new. Show only what got through."""
    from .feeds import run as run_feeds

    results = run_feeds(lens=lens)
    if not results:
        typer.echo("  nothing new in any feed.")
        return
    total_seen = total_passed = 0
    for result in results:
        total_seen += result.seen
        total_passed += len(result.passed)
        typer.echo(f"\n  {result.feed[:60]}  —  {len(result.passed)}/{result.seen} got through")
        for item in result.passed:
            typer.echo(f"     [{item.domain:<8}] {item.title[:56]}")
            typer.echo(f"        {item.reason[:70]}")
            typer.echo(f"        {item.link[:70]}")

    mode = results[0].filter
    if mode == "untrained":
        typer.echo(
            f"\n  {total_seen} item(s) read, {total_passed} shown — but the filter is UNTRAINED."
        )
        typer.echo(
            "  Verivann has no basis for an editorial opinion yet, so it is not pretending to have one.\n"
            "  Give it one: `verivann keep|drop <id>` a few times, or register open questions\n"
            "  (`verivann question add \"...\"`) and configure a model."
        )
    else:
        basis = "your open questions" if mode == "questions" else "what you keep"
        typer.echo(f"\n  {total_seen} item(s) read, {total_passed} worth your attention (filtered by {basis}).")


@feed_app.command("remove")
def feed_remove_cmd(url: str = typer.Argument(...)) -> None:
    """Unfollow a feed."""
    from .feeds import remove

    typer.echo("  removed." if remove(url) else "  (not following that feed)")


@app.command("lenses")
def lenses_cmd() -> None:
    """The reading intents you can apply to any source."""
    from .analysis.lenses import DEFAULT_LENS, describe

    for name, description in describe():
        mark = "*" if name == DEFAULT_LENS else " "
        typer.echo(f"  {mark} {name:<9} {description}")
    typer.echo("\n  * default (VERIVANN_LENS overrides; --lens wins over both)")


@app.command("serve")
def serve_cmd(
    port: int = typer.Option(8130, help="Port for the local inbox."),
    host: str = typer.Option("127.0.0.1", help="Bind address (local only by default)."),
    lan: bool = typer.Option(False, "--lan", help="Also reachable from your phone (token-protected)."),
    token: str = typer.Option("", help="Token for LAN mode (generated if omitted)."),
    no_open: bool = typer.Option(False, "--no-open", help="Don't open the browser."),
) -> None:
    """Open the inbox: paste, share or right-click a link — see the digested note.

    With --lan it also listens on your local network, so the phone's share sheet can
    reach it (install the page as an app). LAN mode always requires a token.
    """
    from .web import serve

    serve(
        host="0.0.0.0" if lan else host,  # noqa: S104 - deliberate, and token-gated
        port=port,
        open_browser=not no_open,
        token=token or None,
    )


@app.command("ingest-batch")
def ingest_batch_cmd(
    url: str = typer.Argument(..., help="Playlist / channel URL."),
    limit: int = typer.Option(10, help="Max entries to digest (safety bound)."),
) -> None:
    """Digest a whole playlist or channel (bounded)."""
    from .batch import ingest_batch, list_entries

    entries = list_entries(url, limit)
    if not entries:
        typer.echo("(no entries found — is it a playlist/channel? is yt-dlp installed?)")
        return
    typer.echo(f"  {len(entries)} entr(ies) found — digesting…\n")
    for result in ingest_batch(url, limit):
        e = result.event
        typer.echo(f"  [{e.routing.domain}] {e.extracted.title[:60]}  → {e.decision.action}")


@app.command("search")
def search_cmd(
    query: str = typer.Argument(..., help="Search everything you've digested."),
    limit: int = typer.Option(10, help="Max results."),
) -> None:
    """Search the library — by word, and (with an embedder) by meaning."""
    from .retrieval import retrieve

    found = retrieve(query, Config.load(), limit)
    if not found.hits:
        typer.echo("(no matches)")
        return
    for h in found.hits:
        typer.echo(f"  [{h.domain}] {h.title}")
        typer.echo(f"     {h.created_at[:10]} · {h.source_ref[:70]}")
        if h.snippet:
            typer.echo(f"     …{h.snippet[:160]}")
        typer.echo("")
    if found.engine == "fts":
        typer.echo("  (keyword search only — set VERIVANN_EMBED_MODEL to also search by meaning)")


@app.command("reindex")
def reindex_cmd() -> None:
    """Embed every note that has no vector yet (meaning-search index)."""
    from .embed import enabled, reindex

    cfg = Config.load()
    if not enabled(cfg):
        typer.echo("  no embedder configured — set VERIVANN_EMBED_MODEL (e.g. nomic-embed-text on Ollama).")
        raise typer.Exit(1)
    typer.echo(f"  embedding with {cfg.embed.model}…")
    typer.echo(f"  {reindex(cfg)} note(s) indexed.")


@app.command("trace")
def trace_cmd(
    passage: str = typer.Argument(..., help="Something you wrote."),
    limit: int = typer.Option(5, help="Max origins."),
) -> None:
    """Where did this thought come from? The index, read backwards."""
    from .trace import trace

    origins = trace(passage, Config.load(), limit)
    if not origins:
        typer.echo("(nothing in your library looks like the source of this)")
        return
    for origin in origins:
        typer.echo(f"  {origin.line()}")
        typer.echo(f"     {origin.note.source_ref[:70]}  ({origin.score} match(es))")
        if origin.evidence:
            typer.echo(f"     “{origin.evidence[:110]}”")
        if origin.why:
            typer.echo(f"     {origin.why}")
        typer.echo("")


@app.command("accept")
def accept_cmd(
    note_id: str = typer.Argument(..., help="Note id (a prefix is enough)."),
    to: Path = typer.Option(None, "--to", help="Target folder (or set VERIVANN_ACCEPT_DIR)."),
) -> None:
    """Accept a proposal — copy the note into a real folder. The one committing act."""
    from .accept import accept, default_target

    target = to or default_target()
    if target is None:
        typer.echo("  where to? Pass --to <dir>, or set VERIVANN_ACCEPT_DIR.")
        raise typer.Exit(1)
    result = accept(note_id, target)
    if result is None:
        typer.echo(f"(no staged note with id starting '{note_id}')")
        raise typer.Exit(1)
    typer.echo(f"  accepted: {result.title[:60]}")
    typer.echo(f"  written : {result.target}")
    typer.echo("  (marked kept — the router learns from this)")


@app.command("digest")
def digest_cmd(
    days: int = typer.Option(7, help="Period to pour."),
    out: Path = typer.Option(None, "--out", help="Write to a file instead of the screen."),
) -> None:
    """The week, poured into one document — starting with what survived."""
    from .digest import digest

    text = digest(Config.load(), days)
    if out:
        out.write_text(text, encoding="utf-8")
        typer.echo(f"  written: {out}")
    else:
        typer.echo(text)


@app.command("export")
def export_cmd(
    target: str = typer.Argument("notes", help="What to export: notes | anki"),
    out: Path = typer.Option(None, "--out", help="Output folder (notes) or file (anki)."),
) -> None:
    """Export your data — the readable notes, or Anki cards from what you kept."""
    config = Config.load()
    if target == "notes":
        from .vault import export_notes

        dest = out or Path("verivann-notes")
        n = export_notes(config.staging_dir, dest)
        typer.echo(f"  {n} note(s) → {dest}{os.sep}")
        if not n:
            typer.echo("  (nothing digested yet — run `verivann ingest-url/-text …` first)")
        return
    if target == "anki":
        from .digest import anki

        dest = out or Path("verivann-cards.txt")
        text = anki(config)
        dest.write_text(text, encoding="utf-8")
        cards = max(0, len(text.strip().splitlines()) - 3)
        typer.echo(f"  {cards} card(s) → {dest}")
        if not cards:
            typer.echo("  (nothing kept yet, or no LLM has extracted ideas — cards come from kept notes)")
        return
    typer.echo("  Unknown target — use 'notes' or 'anki'.")
    raise typer.Exit(1)


@app.command("backup")
def backup_cmd(
    out: Path = typer.Option(None, "--out", help="Where to write the .zip."),
) -> None:
    """Bundle your whole library into one portable .zip you can move or keep."""
    from .vault import backup

    dest = out or Path("verivann-backup.zip")
    path = backup(Config.load().staging_dir, dest)
    typer.echo(f"  Backed up → {path}  ({path.stat().st_size // 1024} KB)")
    typer.echo("  One file, everything in it: notes, events, the library, raw archives.")


@app.command("purge")
def purge_cmd(
    source: str = typer.Option("", "--source", help="Erase one source (its key from `verivann sources`)."),
    everything: bool = typer.Option(False, "--all", help="Erase the ENTIRE library."),
    yes: bool = typer.Option(False, "--yes", help="Skip the confirmation prompt."),
    do_backup: bool = typer.Option(True, "--backup/--no-backup", help="Write a safety .zip first."),
) -> None:
    """Erase your data — one source, or everything. Irreversible; backs up first by default."""
    config = Config.load()
    if bool(source) == everything:  # neither, or both
        typer.echo("  Choose exactly one: --source <key> OR --all.")
        raise typer.Exit(1)

    what = "your ENTIRE library" if everything else f"source '{source}'"
    if not yes and not typer.confirm(f"  Permanently erase {what}? This cannot be undone."):
        typer.echo("  Cancelled — nothing was touched.")
        return

    if do_backup:
        from .vault import backup

        path = backup(config.staging_dir, Path("verivann-backup-before-purge.zip"))
        typer.echo(f"  Safety backup → {path}")

    if everything:
        from .vault import erase

        result = erase(config.staging_dir)
    else:
        from .library import purge_source

        result = purge_source(source, config.staging_dir)
    typer.echo(f"  Erased {what}: {result['notes']} note(s), {result['files']} file(s) removed.")


@app.command("claims")
def claims_cmd(limit: int = typer.Option(30, help="Max claims to show.")) -> None:
    """The claim ledger — what your sources assert (needs an LLM to populate)."""
    from .library import all_claims

    rows = all_claims(Config.load().staging_dir, limit)
    if not rows:
        typer.echo("(no claims on record — claims are extracted by the LLM analyzer)")
        return
    for claim, src in rows:
        typer.echo(f"  • {claim}")
        typer.echo(f"      from: {src[:70]}")


@app.command("stale")
def stale_cmd(limit: int = typer.Option(20, help="Max claims to show.")) -> None:
    """Claims whose shelf life has run out — what you believe may no longer be true."""
    from .library import stale_claims

    rows = stale_claims(Config.load().staging_dir, limit)
    if not rows:
        typer.echo("(nothing has gone stale — or no claims carry a shelf life yet)")
        return
    for row in rows:
        typer.echo(f"  • {row['claim']}")
        typer.echo(f"      expired {row['expires_at'][:10]} · {row['source']} · {row['title'][:50]}")


@app.command("ask")
def ask_cmd(question: str = typer.Argument(..., help="Ask your own digested notes.")) -> None:
    """Answer a question from everything you have digested."""
    from .ask import ask

    res = ask(question)
    if not res.hits:
        typer.echo("(nothing in your library matches)")
        return
    if res.answer:
        typer.echo(res.answer)
        typer.echo("")
    typer.echo("Sources:")
    for i, h in enumerate(res.hits[:5], 1):
        typer.echo(f"  [{i}] {h.title}  ({h.source_ref[:60]})")
    if not res.answer:
        typer.echo("\n(no LLM configured — matches only. Set VERIVANN_LLM to get an answer.)")


watch_app = typer.Typer(help="Watch sources for silent edits.")
app.add_typer(watch_app, name="watch")


@watch_app.command("add")
def watch_add(url: str = typer.Argument(..., help="URL to keep under observation.")) -> None:
    """Take the source's current text as the baseline, and watch it from now on."""
    from .watchlist import add

    entry = add(url)
    typer.echo(f"  watching: {entry.label[:60]}")
    typer.echo("  baseline taken — `verivann watch run` will report what moves.")


@watch_app.command("list")
def watch_list() -> None:
    """What is under observation, and when it last moved."""
    from .watchlist import watched

    rows = watched()
    if not rows:
        typer.echo("(nothing under observation — `verivann watch add <url>`)")
        return
    for w in rows:
        moved = f"last changed {w.last_changed[:16]} ({w.changes}×)" if w.changes else "no change yet"
        typer.echo(f"  {w.label[:52]:<52} {moved}")
        typer.echo(f"     {w.url[:70]}  ·  checked {w.last_checked[:16]}")


@watch_app.command("run")
def watch_run(lens: str = _LENS_OPT) -> None:
    """Re-read every watched source. Whatever moved gets digested again, with the diff."""
    from .watchlist import run as run_watch

    moved = run_watch(lens=lens)
    if not moved:
        typer.echo("  nothing moved.")
        return
    for url, patch, lines in moved:
        typer.echo(f"\n  CHANGED ({lines} line(s)): {url}")
        for line in patch.splitlines()[:12]:
            typer.echo(f"    {line}")
    typer.echo(f"\n  {len(moved)} source(s) changed — the notes now carry the diff.")


@watch_app.command("remove")
def watch_remove_cmd(url: str = typer.Argument(...)) -> None:
    """Stop watching a source."""
    from .watchlist import remove

    typer.echo("  removed." if remove(url) else "  (not on the watchlist)")


@app.command("predictions")
def predictions_cmd(
    due: bool = typer.Option(False, "--due", help="Only what has come due."),
    status: str = typer.Option("", help="Filter: open | hit | miss | void."),
) -> None:
    """Claims about the future, on the record — with the date they come due."""
    from .predictions import listing

    items = listing(Config.load().staging_dir, status=status, due_only=due)
    if not items:
        typer.echo("(nothing on the record — predictions are extracted by the LLM analyzer)")
        return
    for p in items:
        marker = "!" if p.is_due else " "
        typer.echo(f"  {marker} {p.line()}\n")
    overdue = sum(1 for p in items if p.is_due)
    if overdue:
        typer.echo(f"  {overdue} prediction(s) have come due — judge them: verivann resolve <id> --hit|--miss")


@app.command("resolve")
def resolve_cmd(
    prediction_id: int = typer.Argument(..., help="Prediction id (see `verivann predictions`)."),
    hit: bool = typer.Option(False, "--hit", help="It came true."),
    miss: bool = typer.Option(False, "--miss", help="It did not."),
    void: bool = typer.Option(False, "--void", help="Unjudgeable — no mark on the source."),
) -> None:
    """Judge a prediction. hit/miss goes onto that source's permanent record."""
    from .predictions import resolve

    chosen = [name for name, on in (("hit", hit), ("miss", miss), ("void", void)) if on]
    if len(chosen) != 1:
        typer.echo("  choose exactly one of --hit / --miss / --void")
        raise typer.Exit(1)

    cfg = Config.load()
    item = resolve(prediction_id, chosen[0], cfg.staging_dir)
    if item is None:
        typer.echo(f"(no prediction with id {prediction_id})")
        raise typer.Exit(1)
    typer.echo(f"  {chosen[0].upper()}: {item.text[:70]}")
    if chosen[0] == "void":
        typer.echo("  (no mark written — the source's record is unchanged)")
        return
    from .library import source_standing

    standing = source_standing(item.source_key, cfg.staging_dir)
    if standing:
        typer.echo(
            f"  {item.source_label}: {standing['hits']} right / {standing['misses']} wrong — on the record."
        )


@app.command("sources")
def sources_cmd(limit: int = typer.Option(20, help="Max sources to show.")) -> None:
    """The standing of every source you have digested — record, yield, verdict."""
    from .sources import standings

    rows = standings(Config.load().staging_dir, limit)
    if not rows:
        typer.echo("(no sources yet)")
        return
    for s in rows:
        flag = "  [HOSTILE]" if s.hostile else ""
        typer.echo(f"  {s.label[:44]:<44}{flag}")
        typer.echo(
            f"     {s.notes} note(s) · {s.kept} kept / {s.dropped} dropped · "
            f"{s.minutes:g} min in → {s.ideas} idea(s) ({s.yield_text()})"
        )
        typer.echo(f"     {s.verdict()}\n")


@app.command("dedupe")
def dedupe_cmd() -> None:
    """Collapse notes that are the same source under different URLs (?t=…, ?si=…, youtu.be)."""
    from .library import dedupe

    merged = dedupe(Config.load().staging_dir)
    if not merged:
        typer.echo("  nothing to merge — every source is already unique.")
        return
    for title, count in merged:
        typer.echo(f"  merged {count} duplicate(s) into: {title[:60]}")
    typer.echo("\n  (note files on disk were not touched — only the library index)")


@app.command("keep")
def keep_cmd(note_id: str = typer.Argument(..., help="Note id (a prefix is enough).")) -> None:
    """Mark a staged note as worth keeping — the router learns from it."""
    _feedback(note_id, "kept")


@app.command("drop")
def drop_cmd(note_id: str = typer.Argument(..., help="Note id (a prefix is enough).")) -> None:
    """Mark a staged note as noise — the router learns from it. (Nothing is deleted.)"""
    _feedback(note_id, "dropped")


def _feedback(note_id: str, verdict: str) -> None:
    from .library import record_feedback
    from .relevance import MIN_SIGNAL, load_profile

    cfg = Config.load()
    hit = record_feedback(note_id, verdict, cfg.staging_dir)
    if hit is None:
        typer.echo(f"(no staged note with id starting '{note_id}' — see `verivann list`)")
        raise typer.Exit(1)
    typer.echo(f"  {verdict}: {hit.title[:60]}  [{hit.domain}]")
    profile = load_profile(cfg.staging_dir)
    if profile.active:
        typer.echo(f"  profile: {profile.n_kept} kept / {profile.n_dropped} dropped — routing adapts.")
    else:
        typer.echo(
            f"  profile: {profile.judged}/{MIN_SIGNAL} verdicts — not enough signal to steer routing yet."
        )


@app.command("review")
def review_cmd(
    sweep: bool = typer.Option(False, "--sweep", help="Accept the implied drops in one pass."),
    days: int = typer.Option(30, help="Ignored for this many days counts as a verdict."),
) -> None:
    """The notes your silence has already judged. Confirm them, or rescue them."""
    from .signals import implied_drops
    from .signals import sweep as run_sweep

    cfg = Config.load()
    items = implied_drops(cfg.staging_dir, days)
    if not items:
        typer.echo("  nothing has been ignored long enough to count as a verdict.")
        return

    for item in items[:25]:
        typer.echo(f"  {item.id[:8]}  [{item.domain:<8}] {item.title[:48]}")
        typer.echo(f"     {item.source[:40]} · untouched for {item.days} days")
    typer.echo(f"\n  {len(items)} note(s) you have never judged and never opened again.")

    if not sweep:
        typer.echo("  `verivann review --sweep` records them as dropped (weakly — a shrug, not a verdict).")
        typer.echo("  Rescue any of them with `verivann keep <id>`; that always wins over an inferred drop.")
        return
    count = run_sweep(cfg.staging_dir, days)
    typer.echo(f"\n  {count} note(s) recorded as dropped by silence (weight 0.25 each).")


@app.command("counter")
def counter_cmd(
    note_id: str = typer.Argument(..., help="The note to argue with."),
    limit: int = typer.Option(6, help="Max sources to fetch."),
) -> None:
    """Go and find the other side. Fetched sources are digested like any other."""
    from .adapters.search import available
    from .counter import counter

    if not available():
        typer.echo("  no search backend — set VERIVANN_SEARCH_URL (SearXNG) or VERIVANN_SEARCH_KEY (Brave).")
        typer.echo("  Verivann does not scrape engines whose terms forbid it.")
        raise typer.Exit(1)

    result = counter(note_id, limit=limit)
    if result is None:
        typer.echo(f"(no note with id starting '{note_id}')")
        raise typer.Exit(1)

    typer.echo(f"\n  Arguing with: {result.title[:60]}\n")
    if result.queries:
        typer.echo("  searched for:")
        for q in result.queries:
            typer.echo(f"    · {q}")
    typer.echo("")
    for item in result.fetched:
        mark = "CONTRADICTS" if item["contradicts"] else "no conflict"
        typer.echo(f"    [{mark:<11}] {item['title'][:52]}")
        typer.echo(f"                  {item['source'][:40]}  {item['url'][:44]}")
        if item["why"]:
            typer.echo(f"                  {item['why'][:70]}")
    typer.echo(f"\n  {result.verdict()}\n")


@app.command("clarify")
def clarify_cmd() -> None:
    """The router guessed. Ask it to stop guessing — one keypress per note."""
    from .interview import answer, uncertain
    from .questions import listing

    cfg = Config.load()
    pending = uncertain(cfg.staging_dir, cfg.domains, listing(cfg))
    if not pending:
        typer.echo("  nothing is in doubt. (Notes you already judged are never asked about.)")
        return

    for item in pending:
        typer.echo(f"\n  {item.title[:64]}")
        typer.echo(f"  {item.reason}")
        for i, label in enumerate(item.labels, 1):
            typer.echo(f"    {i}) {label}")
        typer.echo("    s) skip · q) quit")
        choice = typer.prompt("  >", default="s").strip().lower()
        if choice == "q":
            break
        if choice == "s" or not choice.isdigit():
            continue
        index = int(choice) - 1
        if 0 <= index < len(item.options):
            typer.echo(f"  → {answer(item.note_id, item.options[index], cfg.staging_dir)}")


@app.command("alloy")
def alloy_cmd(
    note_ids: list[str] = typer.Argument(..., help="Two or more note ids (prefixes are fine)."),
    title: str = typer.Option("", "--title", help="What the alloy is about."),
) -> None:
    """Melt several notes into one that says what none of them says alone."""
    from .alloy import alloy

    result = alloy(note_ids, title)
    if result is None:
        typer.echo("  an alloy needs at least two existing notes.")
        raise typer.Exit(1)
    typer.echo(f"  {result.title}")
    typer.echo(f"  melted from : {', '.join(s[:34] for s in result.sources)}")
    typer.echo(f"  engine      : {result.engine}")
    typer.echo(f"  note        : {result.note_path}")
    if result.engine == "assembly":
        typer.echo("\n  (no model configured — the sources were placed side by side, not synthesized.)")


@app.command("refresh")
def refresh_cmd() -> None:
    """Update every note that the world has moved on from. The banner, not the note."""
    from .refresh import refresh

    changed = refresh()
    if not changed:
        typer.echo("  nothing has happened to any note since you wrote it.")
        return
    for item in changed:
        typer.echo(f"  {item.title[:56]}")
        if item.contradicted:
            typer.echo(f"     contradicted by {len(item.contradicted)} later source(s)")
        if item.expired:
            typer.echo(f"     {len(item.expired)} claim(s) past their shelf life")
        if item.missed:
            typer.echo(f"     {len(item.missed)} prediction(s) did not come true")
        if item.source_note:
            typer.echo(f"     source: {item.source_note}")
    typer.echo(f"\n  {len(changed)} note(s) now carry a 'Since you read this' box.")


@app.command("resurface")
def resurface_cmd(limit: int = typer.Option(5, help="How many.")) -> None:
    """What you kept months ago that speaks to what you are doing now."""
    from .resurface import resurface

    items = resurface(limit=limit)
    if not items:
        typer.echo("  nothing forgotten is relevant right now — or nothing is old enough to be forgotten.")
        return
    for item in items:
        typer.echo(f"  {item.line()}")
        typer.echo(f"     because of {item.because}")
        typer.echo("")


@app.command("daemon")
def daemon_cmd(
    once: bool = typer.Option(False, "--once", help="One pass, then exit (what cron should call)."),
    force: bool = typer.Option(False, "--force", help="Run every job, due or not."),
    install: bool = typer.Option(False, "--install", help="Print the scheduler line for your OS."),
    interval: int = typer.Option(300, help="Seconds between passes when running continuously."),
) -> None:
    """Run the schedule: feeds, the watchlist, living notes, the silent verdicts.

    An editor you have to wake up every morning is not an editor.
    """
    from .daemon import install_hint, run_once, serve

    cfg = Config.load()
    if install:
        typer.echo(install_hint(sys.executable, str(Path.cwd())))
        return

    def report(name: str, summary: str) -> None:
        typer.echo(f"  [{datetime.now().strftime('%H:%M')}] {name:<8} {summary}")

    if once:
        result = run_once(cfg, force=force, on_job=report)
        if not result.done and not result.failed:
            typer.echo("  nothing was due.")
        return

    typer.echo("  Verivann daemon — feeds, watchlist, living notes. Ctrl+C to stop.")
    typer.echo("  (It never asks and never commits: everything it does is a proposal.)\n")
    try:
        serve(cfg, interval=interval, on_job=report)
    except KeyboardInterrupt:
        typer.echo("\n  stopped.")


@app.command("reanalyze")
def reanalyze_cmd(
    everything: bool = typer.Option(False, "--all", help="Re-read even notes a model already read."),
    limit: int = typer.Option(100, help="Safety bound."),
    lens: str = _LENS_OPT,
) -> None:
    """Read old notes again, properly, now that a model is configured. Nothing is re-fetched."""
    from .reanalyze import pending, reanalyze

    cfg = Config.load()
    if not (cfg.llm.enabled or cfg.local_llm.enabled):
        typer.echo("  no model configured — re-reading would just repeat the heuristic.")
        typer.echo("  `verivann models` shows the free options.")
        raise typer.Exit(1)

    todo = pending(cfg, everything)
    if not todo:
        typer.echo("  every note has already been read by a model.")
        return
    typer.echo(f"  {len(todo)} note(s) to re-read (from stored material — no source is touched).\n")

    def report(item) -> None:
        typer.echo(
            f"    [{item.domain:<8}] {item.title[:46]:<46} {item.was[:14]:<14} → {item.now[:18]}"
        )

    done = reanalyze(cfg, everything=everything, lens=lens, limit=limit, on_item=report)
    typer.echo(f"\n  {len(done)} note(s) re-read. Their ids, verdicts and highlights are unchanged.")


@app.command("bakeoff")
def bakeoff_cmd(
    models: str = typer.Option("", "--models", help="Comma-separated, e.g. 'llama-3.3-70b,gpt-4o-mini'."),
    notes: int = typer.Option(20, help="How many stored notes each model should read."),
    results_only: bool = typer.Option(False, "--results", help="Just show the standings."),
    lens: str = _LENS_OPT,
) -> None:
    """Two models read the same material. Your verdicts decide which one was right."""
    from .bakeoff import MIN_JUDGED, results, run

    cfg = Config.load()
    if not results_only:
        chosen = [m.strip() for m in models.split(",") if m.strip()]
        if len(chosen) < 2:
            typer.echo("  give at least two models: --models a,b")
            raise typer.Exit(1)
        if not cfg.llm.enabled:
            typer.echo("  no model endpoint configured — `verivann models` shows the free options.")
            raise typer.Exit(1)

        typer.echo(f"  {', '.join(chosen)} will each read the same stored notes (no re-fetch).\n")
        read = run(chosen, cfg, limit=notes, lens=lens, on_item=lambda n, m, a: None)
        typer.echo(f"  {read} note(s) read by each model.")
        typer.echo(f"  Now judge them (`verivann list`, then keep/drop). {MIN_JUDGED} verdicts and the")
        typer.echo("  standings mean something: `verivann bakeoff --results`\n")
        return

    standings = results(cfg)
    if not standings.contenders:
        typer.echo("  no bake-off has been run — `verivann bakeoff --models a,b`")
        return
    typer.echo("")
    for c in sorted(standings.contenders, key=lambda x: (x.accuracy or 0), reverse=True):
        agreement = f"{int((c.accuracy or 0) * 100)}%" if c.accuracy is not None else "—"
        typer.echo(f"    {c.model[:34]:<34} read {c.read:<4} judged {c.judged:<4} agreed {agreement}")
    typer.echo(f"\n  {standings.verdict()}\n")


@app.command("models")
def models_cmd() -> None:
    """The model slots — and the free ways to fill them."""
    from .adapters.search import backend as search_backend
    from .privacy import policy
    from .redact import enabled as redact_on

    cfg = Config.load()
    typer.echo("\n  Configured\n")
    chain = cfg.llm.candidates()
    typer.echo(f"    analysis : {' → '.join(f'{s.provider}:{m}' for s, m in chain) if chain else 'none (heuristic)'}")
    typer.echo(f"    local    : {cfg.local_llm.model or 'none'}")
    typer.echo(f"    embedding: {cfg.embed.model or 'none (keyword search only)'}")
    typer.echo(f"    search   : {search_backend() or 'none'}")
    typer.echo(f"    privacy  : {policy()}{'  + local redaction' if redact_on() else ''}")

    typer.echo("""
  Free ways to fill them (all OpenAI-compatible — Verivann speaks that everywhere)

    cloudflare   you already have an account if antonius.app runs on it.
                 VERIVANN_LLM=cloudflare
                 VERIVANN_CF_ACCOUNT_ID=<id>
                 VERIVANN_LLM_MODEL=@cf/meta/llama-3.3-70b-instruct-fp8-fast
                 VERIVANN_LLM_API_KEY=<token>
                 VERIVANN_EMBED_MODEL=@cf/baai/bge-base-en-v1.5

    groq         fast, generous free tier.       VERIVANN_LLM=groq
    openrouter   many models, some ':free'.      VERIVANN_LLM=openrouter
    gemini       free tier, OpenAI endpoint.     VERIVANN_LLM=gemini
    ollama       local, private, free forever.   VERIVANN_LLM=ollama

  Free tiers rate-limit. Give the chain somewhere to fall:
    VERIVANN_LLM_MODELS=<second model on the same endpoint>,<third>
    VERIVANN_LLM_FALLBACK=groq   (a whole other provider)

  Sensitive material (your files, IBANs, diagnoses) never goes to a hosted model
  unless you say so: VERIVANN_LOCAL_LLM=..., or VERIVANN_REDACT=1, or VERIVANN_PRIVACY=allow.
""")


@app.command("calibrate")
def calibrate_cmd() -> None:
    """Measure the router against your own verdicts. It is allowed to look bad."""
    from .calibrate import calibrate

    report = calibrate(Config.load().staging_dir)
    typer.echo(f"\n  {report.headline()}\n")
    if not report.enough:
        return

    typer.echo(f"  judged notes   : {report.judged}  ({report.explicit} you decided yourself)")
    keeper = report.keeper_precision
    drop = report.drop_precision
    typer.echo(
        f"  proposed keep  : {report.keeper_proposed} → you kept {report.keeper_kept}"
        f"  (precision {keeper if keeper is not None else '—'})"
    )
    typer.echo(
        f"  proposed drop  : {report.drop_proposed} → you dropped {report.drop_dropped}"
        f"  (precision {drop if drop is not None else '—'})"
    )

    typer.echo("\n  survival by confidence:")
    for bucket in report.buckets:
        rate = bucket.survival
        bar = "—" if rate is None else f"{int(rate * 100):>3}% kept"
        typer.echo(f"     {bucket.label()}   n={bucket.n:<4} {bar}")
    calibrated = report.calibrated()
    if calibrated is False:
        typer.echo("     ↳ NOT calibrated: being surer did not make it righter.")
    elif calibrated:
        typer.echo("     ↳ calibrated: higher confidence really did survive more often.")

    if len(report.engines) > 1 or report.engines:
        typer.echo("\n  who read it:")
        for slice_ in report.engines:
            acc = slice_.accuracy
            typer.echo(f"     {slice_.name[:28]:<28} n={slice_.n:<4} agreed with you {acc if acc is not None else '—'}")
    if len(report.lenses) > 1:
        typer.echo("\n  with what intent:")
        for slice_ in report.lenses:
            acc = slice_.accuracy
            typer.echo(f"     {slice_.name[:28]:<28} n={slice_.n:<4} agreed with you {acc if acc is not None else '—'}")
    typer.echo("")


@app.command("log")
def log_cmd(limit: int = typer.Option(25, help="How far back.")) -> None:
    """The furnace log — every act, in order. Nothing here is ever rewritten."""
    from .library import event_rows

    rows = event_rows(Config.load().staging_dir, limit)
    if not rows:
        typer.echo("(the log is empty)")
        return
    for row in rows:
        typer.echo(f"  {row['at'][:16]}  {row['action']:<8} {(row['detail'] or row['subject'])[:60]}")


@app.command("profile")
def profile_cmd() -> None:
    """What the router has learned about what you keep."""
    from .relevance import MIN_SIGNAL, load_profile

    profile = load_profile(Config.load().staging_dir)
    typer.echo(f"  judged     : {profile.n_kept} kept / {profile.n_dropped} dropped")
    if not profile.active:
        typer.echo(f"  status     : dormant (needs {MIN_SIGNAL} verdicts; use `verivann keep|drop <id>`)")
        return
    keep = ", ".join(w for w, _ in profile.kept.most_common(10) if profile.dropped[w] == 0)
    drop = ", ".join(w for w, _ in profile.dropped.most_common(10) if profile.kept[w] == 0)
    domains = ", ".join(f"{d}×{n}" for d, n in profile.kept_domains.most_common(5))
    typer.echo(f"  keeps      : {keep or '(nothing distinctive yet)'}")
    typer.echo(f"  drops      : {drop or '(nothing distinctive yet)'}")
    typer.echo(f"  domains    : {domains or '—'}")


@app.command("mirror")
def mirror_cmd(days: int = typer.Option(30, help="Look back this many days.")) -> None:
    """How much you consumed, and how much of it survived your own judgment."""
    from .stats import mirror

    m = mirror(Config.load().staging_dir, days)
    typer.echo(f"\n  Last {days} days\n")
    typer.echo(f"  material in    : {m.hours} h  ({m.minutes:g} min)")
    kinds = ", ".join(f"{n}× {k}" for k, n in sorted(m.by_kind.items(), key=lambda x: -x[1]))
    typer.echo(f"  sources        : {kinds or '—'}")
    typer.echo(f"  notes out      : {m.notes}")
    typer.echo(f"  judged         : {m.kept} kept / {m.dropped} dropped / {m.unjudged} never judged")
    typer.echo(f"  analyzed       : {m.analyzed} of {m.notes} (an LLM actually read them)")
    typer.echo(f"  ideas kept     : {m.ideas}")
    typer.echo(f"  tasks proposed : {m.tasks}")
    if m.hostile:
        typer.echo(f"  manipulation   : {m.hostile} attempt(s) on record")
    from .library import outbound_total

    chars, cost = outbound_total(Config.load().staging_dir, days)
    if chars:
        spent = f"€{cost:.2f} (estimated)" if cost else f"{chars} chars sent to a model"
        typer.echo(f"  sent to models : {spent}")
    if m.time_sinks:
        typer.echo("\n  where the time went:")
        for source, minutes, kept in m.time_sinks:
            typer.echo(f"     {minutes:>6.1f} min  {source[:40]:<40} → {kept} kept")
    typer.echo(f"\n  {m.verdict()}\n")


@app.command("outbound")
def outbound_cmd(days: int = typer.Option(30, help="Look back this many days.")) -> None:
    """What left this machine, to whom, and what it cost. No guessing required."""
    from .library import outbound_rows, outbound_total
    from .privacy import is_local, policy

    cfg = Config.load()
    rows = outbound_rows(cfg.staging_dir, days)
    typer.echo(f"\n  privacy policy : {policy()}  (sensitive material stays local under `strict`)")
    typer.echo(f"  local slot     : {cfg.local_llm.model or 'not configured'}")
    typer.echo(f"  main slot      : {cfg.llm.model or 'not configured'}"
               f"{'  (local)' if cfg.llm.enabled and is_local(cfg.llm) else ''}")
    if not rows:
        typer.echo("\n  nothing has been sent to any model in this period.\n")
        return

    typer.echo(f"\n  Last {days} days:")
    for row in rows:
        left = "" if row["provider"] in ("ollama",) else "  → left this machine"
        typer.echo(
            f"    {row['provider']}:{row['model'][:22]:<22} {row['purpose'][:10]:<10} "
            f"{row['calls']:>4} call(s)  {row['chars']:>8} chars{left}"
        )
    chars, cost = outbound_total(cfg.staging_dir, days)
    if cfg.price_per_mtok:
        typer.echo(f"\n  estimated cost : €{cost:.4f}  (at €{cfg.price_per_mtok}/Mtok, chars÷4 — an estimate)")
    else:
        typer.echo(f"\n  {chars} characters sent. Set VERIVANN_PRICE_PER_MTOK to see what it cost.")
    typer.echo("")


@app.command("slag")
def slag_cmd(limit: int = typer.Option(30, help="Max entries.")) -> None:
    """The anti-library — everything you dropped. The negative image of your taste."""
    from .stats import slag

    rows = slag(Config.load().staging_dir, limit)
    if not rows:
        typer.echo("(you have dropped nothing yet — which is itself a finding)")
        return
    for s in rows:
        typer.echo(f"  {s.id[:8]}  [{s.domain:<8}] {s.title[:50]}")
        typer.echo(f"     {s.source[:50]} · {s.created_at[:10]}")


@app.command("bias")
def bias_cmd(topic: str = typer.Argument(..., help="A topic you think you understand.")) -> None:
    """Where your own material agrees with itself — and who dissents."""
    from .bias import bias

    split = bias(topic, Config.load())
    if not split.total:
        typer.echo("(nothing you kept speaks to this)")
        return
    if split.thesis:
        typer.echo(f"\n  your material converges on:\n    \"{split.thesis}\"\n")
    typer.echo(f"  supporting ({len(split.support)}):")
    for title, source in split.support:
        typer.echo(f"     · {title[:50]}  — {source[:28]}")
    if split.dissent:
        typer.echo(f"\n  dissenting ({len(split.dissent)}):")
        for title, source in split.dissent:
            typer.echo(f"     · {title[:50]}  — {source[:28]}")
    if split.blind_spot:
        typer.echo(f"\n  what is missing:\n    {split.blind_spot}")
    typer.echo(f"\n  {split.verdict()}\n")
    if split.engine == "inventory-only":
        typer.echo("  (no LLM configured — this is an inventory, not an audit. Set VERIVANN_LLM.)")


@app.command("doctor")
def doctor() -> None:
    """Check the environment and optional tools."""
    cfg = Config.load()
    typer.echo(f"verivann {__version__}")
    typer.echo(f"  python         : {sys.version.split()[0]}")
    typer.echo(f"  yt-dlp         : {'yes' if shutil.which('yt-dlp') else 'no (youtube falls back)'}")
    typer.echo(f"  staging dir    : {cfg.staging_dir}")
    typer.echo(f"  domains        : {', '.join(cfg.domains)}")
    typer.echo(f"  public_demo    : {cfg.public_demo}")
    analyzer = f"{cfg.llm.provider}:{cfg.llm.model}" if cfg.llm.enabled else "heuristic (no LLM configured)"
    typer.echo(f"  analyzer       : {analyzer}")
    typer.echo(f"  lens           : {cfg.lens}")
    from .adapters.archive import available_tool, chrome_binary, formats
    from .adapters.archive import enabled as archive_on
    from .adapters.transcribe import enabled as whisper_on
    transcription = f"whisper {os.environ.get('VERIVANN_WHISPER_MODEL', '')}" if whisper_on() else "captions only"
    if archive_on():
        tools = [available_tool() or "no html tool"]
        if {"pdf", "png"} & set(formats()):
            tools.append("headless chrome" if chrome_binary() else "no browser for pdf/png")
        raw_archive = f"{'+'.join(formats())} via {', '.join(tools)}"
    else:
        raw_archive = "off"
    typer.echo(f"  transcription  : {transcription}")
    typer.echo(f"  raw archive    : {raw_archive}")
    from .adapters.gallery import gallery_available
    from .adapters.vision import ocr_available, visual_enabled
    typer.echo(f"  images         : {'gallery-dl' if gallery_available() else 'no (gallery-dl absent)'}")
    typer.echo(f"  ocr            : {'tesseract' if ocr_available() else 'no'}")
    typer.echo(f"  video-visual   : {'on' if visual_enabled() else 'off (opt-in)'}")
    try:
        cfg.staging_dir.mkdir(parents=True, exist_ok=True)
        typer.echo("  staging write  : ok")
    except OSError as exc:
        typer.echo(f"  staging write  : FAILED ({exc})")
    from .adapters.search import backend as search_backend
    from .embed import enabled as embed_on
    from .privacy import policy
    typer.echo(
        f"  meaning search : {cfg.embed.model if embed_on(cfg) else 'off (keyword only — set VERIVANN_EMBED_MODEL)'}"
    )
    typer.echo(f"  local slot     : {cfg.local_llm.model or 'none — sensitive material stays unread, not uploaded'}")
    typer.echo(f"  privacy        : {policy()}")
    typer.echo(f"  counter-search : {search_backend() or 'off (set VERIVANN_SEARCH_URL or VERIVANN_SEARCH_KEY)'}")
    try:
        from .feeds import subscriptions
        from .library import count as library_count
        from .predictions import listing as predictions
        from .questions import listing as questions
        from .relevance import load_profile
        from .watchlist import watched

        profile = load_profile(cfg.staging_dir)
        state = "steering routing" if profile.active else "dormant (needs more verdicts)"
        due = [p for p in predictions(cfg.staging_dir) if p.is_due]
        typer.echo(f"  library        : {library_count(cfg.staging_dir)} note(s) indexed")
        typer.echo(f"  learned        : {profile.n_kept} kept / {profile.n_dropped} dropped — {state}")
        typer.echo(f"  questions      : {len(questions(cfg))} open")
        typer.echo(f"  predictions    : {len(due)} due to be judged")
        typer.echo(f"  feeds          : {len(subscriptions(cfg))} followed")
        typer.echo(f"  watchlist      : {len(watched(cfg))} source(s) watched for silent edits")
    except Exception as exc:  # noqa: BLE001
        typer.echo(f"  library        : unavailable ({exc})")


@app.command("list")
def list_intakes(limit: int = typer.Option(20, help="Max notes to show.")) -> None:
    """List staged intake notes — with the id that `keep` / `drop` take."""
    from .library import recent, verdict_of

    cfg = Config.load()
    hits = recent(cfg.staging_dir, limit)
    if not hits:
        notes = sorted((cfg.staging_dir / "notes").glob("*.md"))
        if not notes:
            typer.echo("(no staged intakes yet)")
            return
        for note in notes:  # notes on disk but not indexed (pre-library intakes)
            typer.echo(f"  {note.name}")
        return
    for h in hits:
        # ASCII only: the Windows console (cp1252) chokes on check marks.
        mark = {"kept": "  (kept)", "dropped": "  (dropped)"}.get(verdict_of(h.id, cfg.staging_dir), "")
        typer.echo(f"  {h.id[:8]}  [{h.domain:<8}] {h.title[:52]}{mark}")


def _load_dotenv() -> None:
    """Load a local .env (never committed) so config — incl. the LLM — is picked up."""
    path = Path(".env")
    if not path.is_file():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, val = line.partition("=")
        os.environ.setdefault(key.strip(), val.strip().strip('"').strip("'"))


def main() -> None:
    # The Windows console defaults to cp1252 and dies on an arrow or a check mark.
    # Notes are full of both; a router must not crash on its own output.
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass
    _load_dotenv()
    app()


if __name__ == "__main__":
    main()
