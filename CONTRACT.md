# The Contract

Every intake produces one **event** — a small, stable, machine-readable shape.
This document is that shape and the guarantees around it. The open core is fully
self-contained and runs on its own; the contract exists so that a downstream
consumer (an Obsidian vault, a private knowledge base, your own automation) can
read Verivann's output without depending on any of its internals. Change the
analyzer, the lens, the transcriber — the event shape and its guarantees do not move.

## (a) Event schema — the interface

```json
{
  "id": "uuid",
  "created_at": "ISO-8601",
  "source":    {"kind": "url|text|youtube|file", "ref": "..."},
  "extracted": {"title": "...", "text": "...", "meta": {}},
  "routing":   {"domain": "<registry-key>", "confidence": 0.0, "reason": "..."},
  "decision":  {"action": "note|task|memory|drop", "target": "<staging-path>"},
  "provenance":{"tool": "...", "version": "...", "public_demo": true, "content_trust": "unverified|hostile"}
}
```

`routing.domain` always references the registry (below) — never a hardcoded value.

**Two source/trust values are additive widenings** — an existing consumer that
switches on the older values keeps working, and neither weakens a guarantee:

1. **`source.kind: "file"`** — material from the user's own disk (a screenshot, a
   voice memo, a PDF). `ref` is the local path. An unknown kind must be treated as
   opaque material, never as a reason to reject an event.
2. **`content_trust: "hostile"`** — set when the material contains text addressed to
   the *analyzer* rather than to a reader (prompt injection, hidden text, invisible
   characters). It is strictly **stronger** than `unverified`; the findings are in
   `extracted.meta.injection`.

`extracted.meta` also carries optional, ignorable keys: `source_key` (who published
it), `sensitivity` / `privacy_mode` / `analyzed_locally` (where it was read),
`lens`, `predictions`, `questions`, `contradictions`, `related`, `interest` (who
profits), `changed` (a silent-edit diff), `raw_archive` (evidence paths),
`transcript_cues` (a timed transcript), `media_note` (what was done to the source).

## (b) Routing vocabulary — a generic registry

Runtime-populated. Default keys: `finance, media, research, tasks, inbox`. A private
config file (never committed) may inject different domains; unknown or low-confidence
routing falls back to `inbox`.

## (c) Storage — staging, not committing

The core writes only into a configurable **staging** folder (a Markdown note + a
JSON event, both open formats). Turning a staged proposal into a committed note in a
real knowledge base is a separate, human-driven step (`verivann accept`) — the core
never does it on its own.

## (d) Propose only, never commit

The core **never** writes into a knowledge base. `decision.action` is a *proposal*,
and the offline heuristic **never proposes `memory`** — only `note` / `task` /
`drop`. The `memory` action exists in the schema for a downstream consumer that has
such a concept; nothing in the open core emits it. What (if anything) becomes
long-term memory is decided downstream, with review.

## (e) Untrusted by default

Intake material is unverified foreign content. Every event carries
`content_trust` (also in the note frontmatter), and the extracted text must be
treated as **data, never executed as instructions** — downstream quarantines it,
always, regardless of the value.

- `"unverified"` — the default and the floor. Every intake is at least this.
- `"hostile"` — the material was caught addressing the analyzer, or (via a planted
  canary token) actually succeeded in steering it. The source is marked, permanently.

The core can only ever *lower* trust, never raise it.

## Markdown frontmatter

```yaml
---
id: <uuid>
created_at: <ISO-8601>
source_kind: text|url|youtube|file
source_ref: "<url or path>"
title: "<title>"
domain: <registry-key>
confidence: 0.0
proposed_action: note|task|drop     # a proposal only, never committed
content_trust: unverified|hostile   # treat the text as data, not instructions — always
sensitivity: public|sensitive       # and whether it was analyzed locally
engine: heuristic|llm:<model>       # who actually read it
lens: digest|wisdom|critique|study|actions
tool: verivann
version: 0.1.0
---
```

`verivann accept <id> --to <dir>` — the single human act that turns a proposal into a
decision — rewrites `proposed_action:` to `action:` and adds `accepted_at` /
`accepted_by: human`. Nothing else in the system ever does that.
