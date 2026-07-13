# Verivann

**A local-first intake router. Everything you save, judged — and a record of which of your sources have lied to you.**

Capturing, archiving and summarizing are solved. **Judging is not.** Verivann reads
what you throw at it — articles, videos, screenshots, voice memos, PDFs, feeds — and
does the part no other tool does: it decides what the material deserves to become,
routes it, connects it to what you already have, notices when it contradicts you,
and keeps a permanent record of who told you.

It is not a bookmark manager, not a read-it-later app, not a YouTube summarizer, and
not a cloud service. It runs on your machine. Nothing leaves it unless you say so.

```
Link in.  →  Meaning out.
```

The name is *veri-* (verify, veritas) + *-vann* (vannus, the fan that winnows grain
from chaff): the two things it does — judge what is true, and sift signal from noise.

---

## Install

Verivann is a local program. It needs Python 3.10+.

```bash
pipx install verivann      # recommended — an isolated, always-available install
#   or:  pip install verivann
```

Then, once:

```bash
verivann setup             # pick a free model, write your config, launch the inbox
```

`setup` walks you through connecting a model (there are free options — Cloudflare,
Groq, Gemini, or a fully-local Ollama). Everything works without one too, on an
offline keyword heuristic — a model just makes it much better.

The daily command is **`vv`** (`verivann` also works):

```bash
vv                         # the cockpit: what is due, what is rotting, what you owe a verdict
vv serve                   # the inbox in your browser — paste, search, ask
vv ingest-url "https://…"  # digest something from the terminal
vv doctor                  # what is wired up, what is optional
```

## The first sixty seconds

1. `vv serve` opens a small dark page at `localhost:8130`.
2. Paste a link or any text → you get a **note**: a summary, the ideas worth keeping,
   the claims to check, where it should be routed — and a **Keep / Drop** button.
3. Keeping and dropping is the whole training loop. After a handful of verdicts the
   router starts to know your taste; `vv calibrate` will tell you how often it agreed
   with you, and admit when it didn't.

## What it does that nothing else does

| | |
|---|---|
| **Measures itself** | Sources have a record. So does the router. `vv calibrate` compares every proposal it ever made against your verdicts: *"it proposed keeping 40 notes; you kept 14 — and being surer did not make it righter."* No other tool tells you how often it was wrong. |
| **Keeps score on your sources** | Every claim is filed under whoever made it. When a prediction fails or a claim is contradicted, that source carries it — permanently. `vv sources` shows who has held up, who hasn't, and whose 40-minute videos yield nothing. |
| **Puts predictions on the record** | "X will happen by Y" is stored with its due date and its author. On the date, Verivann asks you. `vv predictions` · `vv resolve <id> --miss` |
| **Catches manipulation — and proves it landed** | Text aimed at the analyzer ("ignore all previous instructions"), hidden text, invisible characters — detected offline, quoted in the note, the source marked `hostile`. And a planted canary token catches a prompt-injection that actually *succeeded*, not just one that tried. |
| **Keeps your disk off the cloud** | Anything from your own files — or carrying an IBAN, a salary, a diagnosis — is `sensitive`. It goes to a local model, or to nobody, or (opt-in) to a hosted model only after names and numbers are **redacted on your machine**. `vv outbound` shows exactly what left. |
| **Learns without asking** | A note you accepted, highlighted, reopened or searched-and-clicked is a verdict you never had to type. A note ignored for 30 days is a quieter one. Explicit verdicts always outrank inferred ones. |
| **Goes and finds the other side** | `vv counter <id>` turns a note's weakest claims into counter-queries, fetches them, and digests the results — so the claim ledger does the arguing. It never asks the accused for an alibi. |
| **Writes back into old notes** | `vv refresh` — when a claim expires, a prediction fails, or a later source contradicts it, the old note gets a banner: *"Since you read this…"*. Obsidian notes are dead files; these are not. |
| **Argues with you** | When a new claim contradicts a note **you kept**, the note says so: *you contradict yourself*. |
| **Shows you the mirror** | `vv mirror` — hours consumed, notes produced, how many survived your own judgment, which channel ate the time. No streak counter, no encouragement. |
| **Reads your feeds for you** | `vv feed run` — an editor, not a reader. Only what passes your learned filter surfaces; when the filter is untrained, it says so instead of faking an opinion. |
| **Judges two models against each other** | `vv bakeoff --models a,b` — both read the same material; *your* verdicts decide which one is better at *your* material, in *your* language. |

## Core principles

- **Propose only, never commit.** The core never writes into a knowledge base. It
  emits a proposal (`note` / `task` / `drop`). `vv accept <id> --to <dir>` is the one
  place a human turns that into a decision.
- **Untrusted by default.** Web material is data, never instruction.
- **Never fake a judgment.** No model → a source's yield is *unknown*, not zero. Too
  few verdicts → the router refuses to report a score. A tool that pretends to know is
  worse than one that admits it doesn't.
- **Orchestrate, don't rebuild.** yt-dlp, Whisper, gallery-dl, tesseract, ffmpeg — all
  invoked as separate programs, never bundled (see [NOTICE.md](NOTICE.md)).
- **Local-first.** The library, the ledgers and your profile never leave the machine
  unless you configure a hosted model — and then `vv outbound` logs every byte.

## What it reads

Articles · videos (published **captions** → a timestamped transcript that links back
into the video) · TikTok/Instagram/X · image galleries (OCR) · on-screen text in
videos · Reddit · **screenshots** (OCR) · **voice memos** (transcribed) · **PDFs and
EPUBs** · **RSS/Atom feeds**.

On video: Verivann reads the **caption track** — plain text, published by the
platform, behind no protection. It downloads the media file only when there is no
caption and only to transcribe it, then deletes it — and on platforms that protect
their stream (YouTube, Netflix, Spotify…) it never does, because that would be
circumvention. That rule is not a setting. See `verivann/mediapolicy.py`.

## Capture without typing

| | |
|---|---|
| **Browser extension** | `extensions/chrome` — right-click a page, link or selection, or **Alt+S**. It talks only to your own local inbox. [Install](extensions/chrome/README.md) |
| **A folder** | `vv folder ~/Pictures/Screenshots --watch` — the screenshots you never open again, OCR'd and routed. Nothing is moved or deleted. |
| **Import what you have** | `vv import obsidian <vault>` · `vv import urls <pocket-export>` · `vv import history` — and it retro-judges your own archive. |
| **Bookmarklet** | Drag *Verivann this* from the inbox footer to your bookmarks bar. |

## Run it on a schedule (optional)

```bash
vv daemon --install        # prints the one line for your OS's task scheduler
```

Feeds, the silent-edit watchlist, and the "since you read this" banners then keep
themselves current in the background. It never asks and never commits — everything it
does is still a proposal.

## The commands

```
vv                     the cockpit — what is due
setup                  connect a model, write config
serve                  the inbox in your browser
ingest-text/-url/-youtube/-file/-batch    digest something
import urls/obsidian/history              bring in what you already have
folder <dir> [--watch]                    digest a folder of files
feed add/run/list                         the editor, not the reader
question add/list/answer                  what you are trying to find out
search · ask · trace · resurface          find it, ask it, trace it back, be handed what you forgot
sources · predictions · resolve           who said it, and were they right
calibrate · bakeoff · models              how good is the router — and which model suits you
mirror · slag · bias · outbound           the honest look: hours, waste, bubble, what left the machine
claims · stale · counter                  the ledger, what has gone off, and the other side
watch add/run · refresh                   silent edits, and notes that learn what happened since
keep · drop · review · clarify · profile  teach the router (and let it ask, once)
accept --to <dir>                         the one committing act
alloy <id> <id>                           melt several sources into one
reanalyze · digest · log                  re-read with a model, the week, the furnace log
export notes/anki · backup · purge        your data: a readable folder, one portable .zip, or gone
daemon · doctor · list · dedupe · reindex housekeeping
```

`dedupe --semantic` also catches the same content re-posted under a different URL:
same-source reposts are merged, cross-source echoes are flagged (that is corroboration,
not a duplicate) — one threshold that keeps the credibility ledger honest.

`export notes` writes a plain folder of Markdown you own; `backup` bundles the whole
library into one `.zip`; `purge --source <key>` or `purge --all` erases it (irreversibly,
after a confirmation and a safety backup). No lock-in is not a slogan here — it is a command.

## Is it private? Is it legal?

Yes to both, by design. It is local-first — no account, no telemetry, no phone-home.
Sensitive material never reaches a hosted model unless you explicitly allow it, and
even then it can be redacted first. It never bundles a media-downloader and never
circumvents a platform's stream protection. Reading a published caption track is not
media download.

## Contributing & support

Verivann is free and open source under the [MIT License](LICENSE). It is a
donation-supported project with no commercial tier and no cloud service — if it is
useful to you, a sponsorship keeps it going, but nothing is gated.

Issues and pull requests welcome — start with [CONTRIBUTING.md](CONTRIBUTING.md) for
setup and the invariants that keep Verivann itself. Found a security problem? Please
report it privately: [SECURITY.md](SECURITY.md). Everyone is expected to follow the
[Code of Conduct](CODE_OF_CONDUCT.md).

## Docs

[ARCHITECTURE.md](ARCHITECTURE.md) — how it fits together ·
[CONTRACT.md](CONTRACT.md) — the event/routing contract ·
[NOTICE.md](NOTICE.md) — third-party licenses ·
[CHANGELOG.md](CHANGELOG.md) — what shipped when
