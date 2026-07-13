# Architecture

One pipeline, deliberately small. What it does **not** do is the point: it never
writes to memory and never touches a real knowledge structure. It proposes and
stages.

```
Capture     CLI · web inbox · browser extension · phone share sheet · bookmarklet
            folder watcher (screenshots, memos) · feeds (RSS/Atom)
        │
        ▼
Canonical   clean the string, canonicalize the URL → one source, one identity
        │
        ▼
Adapter     extract → Extracted{title, text, meta}
  ├── textdump   pasted text (always available, no network)
  ├── webpage    httpx + BeautifulSoup  (+ hidden text and links, for security)
  ├── media      yt-dlp: metadata + TIMED captions → Whisper only if none
  ├── gallery    gallery-dl + OCR          ├── vision   ffmpeg keyframes + OCR
  ├── local      screenshots (OCR) · voice memos (Whisper) · PDF · EPUB
  └── reddit     public JSON endpoint (OAuth pending)
        │
        ▼
Security    scan_injection() → text aimed at the ANALYZER  → content_trust: hostile
            scan_interest()  → sponsorships, affiliate funnels → “Who profits”
        │
        ▼
Relevance   load_profile() — what this reader has kept and dropped so far
        │
        ▼
Analyzer    heuristic (offline, default) · LLM (optional, lens-steered)
            → domain, confidence, reason, action, summary, ideas, claims,
              predictions (dated), shelf_life
        │     (a heuristic result is nudged by the learned profile)
        ▼
Registry    resolve domain → placeholder key or `inbox`
        │
        ▼
Enrichment  questions.match()         → does this advance anything you asked?
            retrieval.related()       → “Connections” (hybrid: words + meaning)
            claims.check_contradictions() → incl. “you contradict yourself”
            sources.identify()        → WHO said it, and their standing
            archive.archive_all()     → html / pdf / png evidence (opt-in)
        │
        ▼
Event       build IntakeEvent (the contract shape)
        │
        ├── render/markdown → human note (security → who profits → record → …)
        └── render/json     → machine event
        │
        ▼
Storage     write BOTH artifacts into staging — nothing else
        │
        ▼
Ledgers     library (notes, FTS5, vectors) · claims (+ shelf life) · predictions
            (+ due dates) · sources (hits/misses/hostile) · feedback · questions
        │
        ▼
Human       keep / drop  → the router learns
            accept       → the ONE place a proposal becomes a decision
```

## Modules

| Module | Responsibility |
|---|---|
| `schema.py` | The contract event (Pydantic). Single source of truth for shape. |
| `canonical.py` | The identity of a source: cleans pasted strings, canonicalizes URLs. Everything downstream (dedup, library, verdicts) keys on this. |
| `branding.py` | The mark, generated (stdlib zlib/struct) — no binary assets committed. |
| `adapters/` | `textdump`, `webpage`, `media`, `transcribe`, `gallery`, `vision`, `reddit`, `archive` — each returns `Extracted` (or, for `archive`, the raw evidence). Every external tool is a **subprocess**, never an import. |
| `analysis/analyzer.py` | Dispatcher + offline keyword heuristic (public default). Propose-only. |
| `analysis/llm.py` | Optional LLM backend (provider-neutral: OpenAI-compatible / Ollama / Anthropic). Configured privately; fills summary/ideas/claims/actions. Falls back to the heuristic on any failure. |
| `analysis/lenses.py` | Reading intents (`digest`, `wisdom`, `critique`, `study`, `actions`) — steer *what* the analysis looks for; never change the contract. |
| `relevance.py` | The learned profile: keep/drop verdicts → a mild prior on routing (and a hint for the LLM). Dormant below `MIN_SIGNAL`. |
| `security.py` | Injection / hidden-text / invisible-character detection (→ `hostile`), and who profits. Offline, no model. |
| `sources.py` | Who published it, their record (hits, misses, manipulation), and their yield. |
| `predictions.py` | Dated claims about the future → the scoreboard. `resolve` writes onto the source's record. |
| `questions.py` | The open-question register — the real routing target. Matching, evidence, synthesis. |
| `bias.py` | The bubble check: does your own material only agree with itself, and do the dissenters have the better record? |
| `stats.py` | The mirror (hours in / notes kept) and the anti-library. |
| `watchlist.py` | Silent-edit detection: re-read, diff, re-digest with the diff attached. |
| `feeds.py` | The editor: reads feeds, surfaces only what passes — and admits when the filter is untrained. |
| `watchfolder.py` | The folder that empties itself (screenshots, memos). Never moves or deletes a file. |
| `embed.py` · `retrieval.py` | Meaning search (any `/embeddings` endpoint) and hybrid rank fusion with FTS5. |
| `trace.py` | The index, read backwards: from something you wrote to the intakes it came from. |
| `accept.py` | The one committing act — proposal → decision, by human command. |
| `digest.py` | The week poured into one document; Anki cards from kept notes only. |
| `library.py` | SQLite + FTS5 + vectors: notes, claims, predictions, sources, feedback, questions, evidence, watchlist, feeds, files. |
| `ask.py` | Answers a question strictly from your own intake, with sources. |
| `claims.py` | Contradiction checking against the claim ledger (LLM), incl. self-contradiction. |
| `batch.py` | Bounded playlist/channel intake. |
| `registry.py` | Generic domain registry; placeholders public, real domains runtime. |
| `config.py` | Staging dir, domains, LLM slot, default lens — from env / private config. |
| `render/` | Markdown note + JSON event. |
| `storage/` | Staging writer + safe artifact naming. |
| `pipeline.py` | Orchestrates the above. |
| `web.py` | The local inbox (stdlib http.server): digest · library · keep/drop. |
| `cli.py` | `ingest-*`, `search`, `ask`, `claims`, `keep`/`drop`, `profile`, `lenses`, `serve`, `doctor`, `list`. |

## Why it holds together

The contract (`CONTRACT.md`) is the only thing the private layer depends on.
Everything above is replaceable behind it: a different analyzer, a different
lens, a different transcriber, a smarter relevance model — the event shape,
the propose-only rule, and `content_trust: unverified` do not move.

## Where the external tools plug in

The core **orchestrates**, it does not rebuild: yt-dlp (media + captions),
Whisper/whisper.cpp (missing transcripts), gallery-dl (images), ffmpeg +
tesseract (on-screen text), monolith/single-file and headless Chrome (raw
evidence), and any OpenAI-compatible or Anthropic model (analysis). Each is an
adapter or a post-stage consumer — none changes the contract.
