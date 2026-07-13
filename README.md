# Smelt

**Internet material → structured, routed notes.**

Capturing, archiving and summarizing are solved problems. **Judging is not.**
Smelt reads what you throw at it — articles, videos, screenshots, voice memos,
PDFs, feeds — and does the part no other tool does: it decides what the material
deserves to become, routes it, connects it to what you already have, notices when
it contradicts you, and remembers who told you.

It is not a bookmark manager, not a read-it-later app, not a YouTube summarizer.
It is the layer above those: **relevance, routing, and decision.**

```
Link in.  →  Meaning out.
```

## What it does that nothing else does

| | |
|---|---|
| **Measures itself** | Sources have a record. So does the router. `smelt calibrate` compares every proposal it ever made against your verdicts: *"it proposed keeping 40 notes; you kept 14 — and its confidence is not calibrated: being surer did not make it righter."* No other tool in this space will tell you how often it was wrong. |
| **Keeps score on your sources** | Every claim is filed under whoever made it. When a prediction fails or a claim is contradicted, that source carries it — permanently. `smelt sources` shows who has been right, who has been wrong, and whose 40-minute videos yield nothing. |
| **Learns without asking** | A note you accepted, highlighted, reopened or searched-and-clicked is a verdict you never had to type. A note ignored for 30 days is a quieter one. Explicit verdicts always outrank inferred ones. |
| **Keeps your disk off the cloud** | Anything from your own files — or carrying an IBAN, a salary, a diagnosis — is `sensitive`. Under the default policy it goes to a local model, or to nobody. It is never silently uploaded, and `smelt outbound` shows exactly what left and what it cost. |
| **Goes and finds the other side** | `smelt counter <id>` turns a note's weakest claims into counter-queries, fetches, and digests the results — so the claim ledger does the arguing. It never asks the accused for an alibi. |
| **Writes back into old notes** | `smelt refresh` — when a claim expires, a prediction fails, or a later source contradicts it, the old note gets a banner: *"Since you read this…"*. Obsidian notes are dead files; these are not. |
| **Puts predictions on the record** | "X will happen by Y" is stored with its due date and its author. On the date, Smelt asks you. `smelt predictions` · `smelt resolve <id> --miss` |
| **Argues with you** | New claims are checked against your claim ledger. When the contradiction is with a note **you kept**, the note says so: *you contradict yourself*. |
| **Shows you the mirror** | `smelt mirror` — hours consumed, notes produced, how many survived your own judgment, and which channel ate the time. There is no streak counter and no encouragement. |
| **Keeps the anti-library** | `smelt slag` — everything you threw away. The negative image of your taste. |
| **Catches manipulation** | Text aimed at the analyzer ("ignore all previous instructions"), text hidden from the human eye, invisible characters — detected, quoted in the note, and the source is marked `hostile`. Offline, no model needed. |
| **Names who profits** | Sponsorships, affiliate links, discount codes — rendered **above** the summary. You learn who paid before you learn what they claim. |
| **Watches for silent edits** | `smelt watch add <url>` → when the source is quietly rewritten, the note carries the diff. |
| **Routes to your questions, not to folders** | `smelt question add "..."` — every intake is read against what you are actually trying to find out. Material that advances none of it says so. `smelt question answer <id>` synthesizes everything you gathered, names where sources disagree, and states what is still missing. |
| **Reads your feeds for you** | `smelt feed run` — an editor, not a reader. Only what passes your learned filter surfaces. And when the filter is untrained, it says so instead of faking an opinion. |

## Core principles

- **Propose only, never commit.** The core never writes into a knowledge base. It
  emits a proposal (`note` / `task` / `drop`). `smelt accept <id> --to <dir>` is
  the one place a human turns that into a decision.
- **Untrusted by default.** Web material is data, never instruction. Every note
  carries `content_trust`; material that tries to steer the analyzer gets
  `hostile`.
- **Never fake a judgment.** No model configured → the yield of a source is
  reported as *unknown*, not as zero. No verdicts given → the feed filter says it
  is untrained. A tool that pretends to know is worse than one that admits it does not.
- **Orchestrate, don't rebuild.** yt-dlp, Whisper, gallery-dl, tesseract, ffmpeg,
  monolith, headless Chrome — all invoked as programs, never bundled. Their
  copyleft stays with them.
- **Local-first.** Library, ledgers and profile never leave the machine unless you
  configure a hosted model.
- **Degrade, never fail.** No network, no ffmpeg, no model → you still get a note.

## Quickstart

```bash
python -m venv .venv
.venv/Scripts/python -m pip install -e ".[dev]"      # Windows

smelt serve            # the inbox: paste, share or right-click a link
smelt doctor           # what is wired up, what is optional
```

## Capture without typing

A tool like this dies at the capture step — nobody opens a terminal to save a
video. Four ways in, all pointing at your own server:

| | |
|---|---|
| **Browser extension** | `extensions/chrome` — right-click a page, link or selection, or **Alt+S**. Lens, keep, drop, done. [Install](extensions/chrome/README.md) |
| **Phone share sheet** | `smelt serve --lan` → open the printed URL on your phone → *Add to home screen*. Smelt now appears in the share sheet of every app. |
| **Bookmarklet** | Drag *Smelt this* from the inbox footer to your bookmarks bar. |
| **A folder** | `smelt folder ~/Pictures/Screenshots --watch` — the pile of screenshots you never open again, OCR'd and routed. Nothing is moved or deleted. |

`--lan` requires a token (generated for you). An intake endpoint anyone on the
café Wi-Fi can POST to is not a feature.

**One source, one note.** Links are canonicalized before anything is fetched
(`?t=78s`, `?si=…`, `utm_*`, `youtu.be`, and the parentheses copying drags along).
Digesting the same source twice re-reads it; it does not duplicate it.
`smelt dedupe` repairs older libraries.

## What it reads

Articles · videos (captions → **timestamped** transcript linking back into the
video; Whisper only when no captions exist) · TikTok/Instagram/X · image galleries
(gallery-dl + OCR) · on-screen text in videos (ffmpeg + OCR) · Reddit ·
**screenshots** (OCR) · **voice memos** (Whisper) · **PDFs and EPUBs** · **RSS/Atom**.

## Lenses — the same source, read with a different intent

```bash
smelt ingest-url "https://…" --lens critique
smelt lenses     # digest · wisdom · critique · study · actions
```

A lens steers *what the analysis looks for* and renames the note's sections. It
never changes the contract: routing, proposal-only, ledger and index stay identical.

## The commands

`smelt` on its own is the **cockpit**: what came due, what is rotting, what your
silence has already decided, and what the router itself got wrong. Everything else
is there when you want it.

```
smelt                                    what is due — the one screen
ingest-text/-url/-youtube/-file/-batch   digest something
import urls/obsidian/history             bring in what you already have
folder <dir> [--watch]                   digest a folder (screenshots, memos)
feed add/run/list                        the editor, not the reader
question add/list/answer                 what you are trying to find out
search · ask · trace · resurface         find it, ask it, trace it back, be handed what you forgot
sources · predictions · resolve          who said it, and were they right
calibrate                                …and how often were WE right?
mirror · slag · bias · outbound          the honest look: hours, waste, bubble, what left the machine
claims · stale · counter                 the ledger, what has gone off, and the other side
watch add/run · refresh                  silent edits, and notes that learn what happened since
keep · drop · review · clarify · profile teach the router (and let it ask, once)
accept --to <dir>                        the one committing act
alloy <id> <id>                          melt several sources into one
digest · export anki · log               the week, the cards, the furnace log
doctor · list · dedupe · reindex         housekeeping
```

## Optional power, all opt-in

Smelt runs free and offline out of the box (heuristic routing, no model). Every
heavier capability is a program it *invokes*:

| Capability | Enable with | Needs |
|---|---|---|
| Analysis, lenses, claims, predictions, questions, bias | `SMELT_LLM=ollama\|openai\|anthropic` + `SMELT_LLM_MODEL` | a model — local (Ollama) or hosted |
| Meaning search (hybrid) | `SMELT_EMBED_MODEL=nomic-embed-text` | any `/embeddings` endpoint |
| Transcription (no captions / voice memos) | `SMELT_WHISPER_MODEL=base` | `faster-whisper` or `whisper.cpp` |
| Screenshots, on-screen text | (automatic / `SMELT_VISUAL=1`) | `tesseract`, `ffmpeg` |
| Raw archive (evidence) | `SMELT_ARCHIVE=1`, `SMELT_ARCHIVE_FORMATS=html,pdf,png` | `monolith`/`single-file`; any Chrome/Edge for PDF+PNG |
| PDFs | (automatic) | `pdftotext` or `pip install pypdf` |

`smelt doctor` tells you which of these are actually live. See `.env.example`.

## Docs

[PLAN.md](PLAN.md) (what was built and why) · [ROADMAP.md](ROADMAP.md) ·
[ARCHITECTURE.md](ARCHITECTURE.md) · [CONTRACT.md](CONTRACT.md) ·
[PRIOR_ART.md](PRIOR_ART.md)

## License

To be finalized before public release — source-available intended (not MIT).
See [LICENSE](LICENSE).
