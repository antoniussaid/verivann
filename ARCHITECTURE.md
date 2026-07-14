# Architecture

One pipeline, deliberately small. What it does **not** do is the point: it never
writes into a knowledge base and never commits. It proposes and stages; a human
accepts. Everything is local-first - nothing leaves the machine unless a hosted
model is configured, and then `verivann outbound` logs it.

```
Capture     CLI · web inbox · browser extension · folder watcher · feeds · importers
        │
        ▼
Canonical   clean the pasted string, canonicalize the URL → one source, one identity
        │
        ▼
Adapter     extract → Extracted{title, text, meta}
  ├── textdump   pasted text (always available, no network)
  ├── webpage    httpx + BeautifulSoup  (+ hidden text and links, for the security scan)
  ├── media      published captions (timed) → local transcription only if none,
  │              governed by mediapolicy: NEVER the media stream of a protected platform
  ├── gallery    images + OCR       ├── vision   ffmpeg keyframes + OCR
  ├── local      screenshots (OCR) · voice memos (transcribed) · PDF · EPUB
  └── reddit     public JSON endpoint
        │
        ▼
Security    scan_injection() → text aimed at the ANALYZER → content_trust: hostile
            scan_interest()  → sponsorships, affiliate funnels → "Who profits"
        │
        ▼
Privacy     classify() → public | sensitive.  Sensitive material (your files, an IBAN,
            a diagnosis) is routed to a LOCAL model, or redacted first, or to nobody -
            never silently uploaded. The chosen model + mode travel with the note.
        │
        ▼
Relevance   load_profile() - what this reader has kept and dropped so far (weighted)
        │
        ▼
Analyzer    heuristic (offline, default) · LLM (optional, lens-steered, language-aware)
            → domain, confidence, reason, action, summary, ideas, claims,
              predictions (dated), shelf_life
            + a planted canary token: if it comes back, the material HIJACKED the model
        │     (a heuristic result is nudged by the learned profile; the LLM call
        ▼      retries, falls back down a model chain, and is billed to the outbound ledger)
Registry    resolve domain → a routing key or `inbox`
        │
        ▼
Enrichment  questions.match()             → does this advance anything you asked?
            retrieval.related()           → "Connections" (hybrid: words + meaning)
            claims.check_contradictions() → incl. "you contradict yourself"
            sources.identify()            → WHO said it, and their standing
            archive.archive_all()         → html / pdf / png evidence (opt-in)
        │
        ▼
Event       build IntakeEvent (the contract shape)
        │
        ├── render/markdown → human note (security → who profits → record → …)
        └── render/json     → machine event
        │
        ▼
Storage     write BOTH artifacts into staging - nothing else
        │
        ▼
Ledgers     library (notes · FTS5 · vectors) · claims (+ shelf life) · predictions
            (+ due dates) · sources (hits/misses/hostile) · feedback (+ weight/origin)
            · questions · evidence · watchlist · feeds · files · outbound · bakeoff
        │
        ▼
Human       keep / drop / accept / highlight / clarify → the router learns
            calibrate / bakeoff → the router and the models are measured against you
            daemon → feeds, watchlist and living-note banners keep themselves current
```

## Modules

**Capture & identity**
| Module | Responsibility |
|---|---|
| `canonical.py` | The identity of a source: cleans pasted strings, canonicalizes URLs. Dedup, the library and every verdict key on this. |
| `adapters/` | `textdump`, `webpage`, `media`, `transcribe`, `gallery`, `vision`, `local`, `reddit`, `archive`, `search` - each returns `Extracted`. Every external tool is a **subprocess**, never an import. |
| `mediapolicy.py` | Whether a video's media file may be fetched - user-configurable, but with a non-overridable blocklist of platforms whose stream is protected (captions only). |
| `importer.py` · `watchfolder.py` | Bring in Obsidian vaults / read-later exports / browser history; digest a folder of files without ever moving them. |
| `feeds.py` | The editor: reads RSS/Atom, surfaces only what passes the learned filter, admits when untrained. |
| `branding.py` | The app mark, generated (stdlib zlib/struct) - no binary assets committed. |

**Judgment**
| Module | Responsibility |
|---|---|
| `analysis/analyzer.py` | Dispatcher + offline keyword heuristic (default). Propose-only, language-aware. |
| `analysis/llm.py` | Provider-neutral LLM backend (OpenAI-compatible / Anthropic / local). Retry + backoff + a fallback model chain; the injection canary; the outbound ledger. Falls back to the heuristic on total failure. |
| `analysis/lenses.py` | Reading intents (`digest`, `wisdom`, `critique`, `study`, `actions`) - steer *what* the analysis looks for; never change the contract. |
| `language.py` | Detects the material's language (offline) so the answer comes back in it; supplies German routing vocabulary. |
| `security.py` | Injection / hidden-text / invisible-char detection (→ `hostile`) and who-profits. Offline. |
| `privacy.py` · `redact.py` | Route material by sensitivity; strip identity locally so sensitive text can be analyzed without leaking it. |
| `relevance.py` · `signals.py` | The learned profile from explicit **and** implicit verdicts (accept/highlight/open/ignore); implicit never overrules explicit. |
| `registry.py` · `config.py` | Domain registry; runtime config (model slots, presets, privacy, lens). |

**Ledgers & intelligence**
| Module | Responsibility |
|---|---|
| `library.py` | SQLite + FTS5 + vectors. Every table: notes, claims, predictions, sources, feedback, questions, evidence, watchlist, feeds, files, outbound, bakeoff, signals, highlights, contradictions, state, events. |
| `sources.py` | Who published it, their record (hits/misses/hostile), and their yield. |
| `claims.py` | Contradiction checking, shelf life, self-contradiction. |
| `predictions.py` | Dated claims → a scoreboard; `resolve` writes onto the source's record. |
| `questions.py` | The open-question register - the real routing target. Matching, evidence, synthesis. |
| `watchlist.py` · `refresh.py` | Silent-edit detection with a diff; "since you read this" banners on old notes. |
| `counter.py` | Go and fetch the other side of a note's weakest claims. |
| `bias.py` · `stats.py` | The bubble check; the mirror and the anti-library. |
| `embed.py` · `retrieval.py` | Meaning search (any `/embeddings` endpoint), hybrid-ranked with FTS5. |
| `ask.py` · `trace.py` · `resurface.py` | Answer from your own intake; trace a thought back to its sources; hand back what you forgot. |
| `alloy.py` | Melt several sources into one. |
| `calibrate.py` · `bakeoff.py` | Measure the router against your verdicts; judge two models against each other. |
| `cockpit.py` | The daily "what is due" screen. |

**Output, orchestration, surfaces**
| Module | Responsibility |
|---|---|
| `schema.py` | The contract event (Pydantic). Single source of truth for shape. |
| `render/` · `storage/` | Markdown note + JSON event; staging writer + safe artifact naming. |
| `pipeline.py` | Orchestrates capture → judge → enrich → render → stage → index. `reanalyze.py` re-runs judgment on stored material without re-fetching. |
| `accept.py` | The one committing act - proposal → a note in a folder you chose, by human command. |
| `digest.py` | The week poured into one document; Anki cards from kept notes only. |
| `daemon.py` | Runs feeds / watchlist / refresh / silent-verdict sweeps on a schedule. Never asks, never commits. |
| `interview.py` | When routing is genuinely uncertain, ask the human once instead of guessing. |
| `web.py` | The local inbox (stdlib http.server): digest · library · mirror · read/highlight · keep/drop. |
| `setup.py` · `cli.py` | The first-run wizard; the `vv` / `verivann` command surface. |

## Why it holds together

The contract (`CONTRACT.md`) is the stable core. Everything above is replaceable
behind it: a different analyzer, a different lens, a different transcriber, a
smarter relevance model - the event shape, the propose-only rule, and
`content_trust` do not move. An optional private config file (never committed) can
inject a different domain registry, but the public build runs fully on its own.

## Where the external tools plug in

The core **orchestrates**, it does not rebuild: yt-dlp (metadata + captions),
Whisper/whisper.cpp (missing transcripts), gallery-dl (images), ffmpeg + tesseract
(on-screen text), monolith/single-file and headless Chrome (raw evidence), SearXNG
(counter-search), and any OpenAI-compatible or Anthropic model (analysis). Each is
a subprocess or a post-stage consumer, invoked and never bundled - so their
licenses stay with them (see [NOTICE.md](NOTICE.md)) and none changes the contract.
