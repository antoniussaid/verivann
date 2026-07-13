# Changelog

## v0.1.0 — first public release

The whole of Verivann, built in the open. Grouped by what it gives you rather than
by the order it was written.

### Read almost anything
- Articles (readable text), web pages, raw text and local files.
- Video via the platform's published **captions** → a timestamped transcript that
  links back into the video; local transcription (Whisper) only when there are no
  captions, governed by an explicit media policy that never circumvents a protected
  stream.
- TikTok / Instagram / X, image galleries (OCR), on-screen text in videos
  (ffmpeg + OCR), Reddit, **screenshots** (OCR), **voice memos**, **PDFs and EPUBs**,
  **RSS/Atom feeds**.
- German and English are detected; the analyzer answers in the language of the source.

### Judge it, and route it
- Relevance + routing with a proposal (`note` / `task` / `drop`) — never a commit.
- Reading **lenses** (digest / wisdom / critique / study / actions) that steer what
  the analysis looks for without changing the contract.
- Routing to your **open questions** instead of folders: material that advances none
  of them says so.

### Keep a record that holds people to account
- A **source-credibility ledger**: every claim filed under whoever made it; sources
  carry their hits, misses and manipulation attempts permanently.
- A **prediction ledger**: dated claims stored and brought back to you on the day.
- A **claim ledger** with shelf-life and contradiction detection — including when you
  contradict a note you yourself kept.
- **Living notes**: old notes get a "since you read this" banner when the world moves.

### Measure yourself, honestly
- `calibrate` scores the router against your own verdicts and admits when it was wrong.
- `bakeoff` runs two models on the same material and lets your verdicts pick the winner.
- `mirror` — hours in, notes kept, where the time went. `slag` — the anti-library.
- `bias` — whether your own library only agrees with itself.

### Security & privacy
- Prompt-injection detection (offline) plus a **canary** that catches a *successful*
  hijack, not just an attempt.
- "Who profits" — sponsorships and affiliate funnels surfaced above the summary.
- **Privacy routing**: sensitive material (your files, IBANs, diagnoses) never reaches
  a hosted model by default; optional local **redaction** lets it be analyzed without
  leaking identity; `outbound` logs every byte and its estimated cost.

### Find it and use it
- Full-text + optional **meaning search** (embeddings), hybrid-ranked.
- `ask` your own intake; `trace` a thought back to the notes it came from;
  `resurface` what you kept months ago and forgot.
- `accept` — the one place a proposal becomes a committed note in a folder you choose.
- `counter` — go and fetch the other side of a claim. `alloy` — melt several sources
  into one.

### Capture & keep it current
- Local web inbox, a Chrome extension (talks only to your own machine), a folder
  watcher, a bookmarklet, and importers for Obsidian / read-later exports / browser
  history.
- Learned relevance from explicit **and** implicit verdicts (accept, highlight, open,
  ignore) — the implicit ones never overrule the explicit ones.
- A **daemon** that keeps feeds, the watchlist and living-note banners current in the
  background — proposing, never committing.

### Foundations
- Local-first SQLite library. Provider-neutral model slot (OpenAI-compatible,
  Anthropic, Ollama, and presets for Cloudflare / Groq / OpenRouter / Gemini) with
  retry, backoff and a fallback chain for free tiers.
- Degrades cleanly at every step: no network, no ffmpeg, no model → you still get a note.
- 222 tests.
