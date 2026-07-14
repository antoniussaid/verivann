# Roadmap

The core rule holds at every step: **orchestrate, don't rebuild; propose, don't
commit.** External tools are invoked as subprocesses (never bundled/imported), so
their licenses stay with them and Verivann keeps its own. Each capability degrades
cleanly when its tool is absent.

## Done

- **v0.1 - Foundation:** text / webpage / video intake → Markdown note + JSON
  event. Heuristic relevance + routing, propose-only, untrusted-by-default,
  staging output, local web inbox (`serve`) + CLI, tests.
- **v0.2 - Transcription:** video captions fetched via yt-dlp (json3); when a
  video has **no** captions, local Whisper transcribes it (faster-whisper /
  whisper.cpp, opt-in via `VERIVANN_WHISPER_MODEL`). Live-verified on Python 3.14.
- **v0.3 - Raw archive:** the evidence a note was made from - self-contained HTML
  (`monolith` / `single-file`) plus PDF and screenshot via headless Chrome/Edge.
  Opt-in: `VERIVANN_ARCHIVE`, `VERIVANN_ARCHIVE_FORMATS`.
- **v0.4 - Images & galleries:** `gallery-dl` (GPL, external CLI) for Pinterest
  and image sources, with OCR over what it downloads.
- **v0.6 - Visual extraction:** `ffmpeg` keyframes + `tesseract` OCR - what a
  video *shows*, not just what it says (opt-in `VERIVANN_VISUAL`).
- **Reddit adapter:** structured post + top comments via the public JSON
  endpoint. Parsing verified; *note:* Reddit now hard-blocks unauthenticated
  JSON, so live use will need OAuth (see below).
- **LLM analyzer:** provider-neutral (OpenAI-compatible / Ollama / Anthropic),
  fills summary / ideas / claims / actions. Default = offline heuristic.
- **Library:** SQLite + FTS5 index over everything digested - `verivann search`.
- **Ask your intake:** `verivann ask` answers strictly from your own notes, with
  sources (LLM optional; without one it returns the matches).
- **Connections:** every fresh note names the older notes it relates to.
- **Claim ledger:** claims are recorded across sources; a new claim that cannot
  both be true with an old one surfaces as a **contradiction** in the note.
- **Batch intake:** `verivann ingest-batch` over a playlist or channel (bounded).
- **Timestamped transcripts:** caption timing is preserved - each block is
  stamped and, where the platform allows it, links straight back into the video.
- **Lenses:** `--lens digest|wisdom|critique|study|actions` - the same source read
  with a different intent, without changing the routing contract.
- **Learned relevance:** `verivann keep|drop <id>` teaches the router what this
  reader actually wants; the profile nudges confidence and can *propose* a drop.
  Dormant until enough verdicts exist (`verivann profile`).
- **Capture surface:** the friction that kills tools like this. Chrome extension
  (right-click / Alt+S / lens / keep-drop), phone share sheet via an installable
  PWA (`verivann serve --lan`, token-gated), bookmarklet - all pointing at your own
  server, no account, no backend.
- **One source, one identity:** URLs are canonicalized before fetch (tracking
  params, share forms, `?t=` positions, copy-paste debris), so re-digesting a
  source updates its note instead of duplicating it. `verivann dedupe` repairs older
  libraries.

## Next

- **v0.5 - Reddit via OAuth:** authenticated access for reliable threads.
- **Hosted portfolio demo:** the inbox deployed with a cloud LLM (Cloudflare
  Workers AI) behind a hard per-visitor cap (a taste, not a service).
- **Vision descriptions:** describing images (not just OCR-ing them) once a
  vision model is wired into the LLM slot.

Anything touching real domains, memory, or private infrastructure stays in the
private layer, never in this repo.
