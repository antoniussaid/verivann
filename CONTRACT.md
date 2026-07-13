# The Contract

Verivann is built by two coordinated agents: a **public/portfolio side**
(this repo) and a **private side** (not in this repo). They agreed on a
minimal shared contract so the public core is showable *and* privately dockable.

## Boundary (non-negotiable)

The public repo contains only neutral building blocks. The real private inner
world — real organ/domain names, relevance/routing logic, memory rules, real
storage paths, anything operational/security-relevant — lives in a private layer
that is **not committed**. The public build ships **placeholder** domains, and
none of the private values appear anywhere, including example outputs.

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

`routing.domain` always references the registry — never a hardcoded real value.

### Amendments (v0.2 — additive, backwards compatible)

Two values were added. Both are **widenings**, not redefinitions: an existing
consumer that switches on the old values keeps working, and neither weakens a
guarantee.

1. **`source.kind: "file"`** — material from the user's own disk (a screenshot, a
   voice memo, a PDF). `ref` is the local path. Consumers that do not know this
   kind must treat it as opaque material; an unknown kind is never a reason to
   reject an event.

2. **`provenance.content_trust: "hostile"`** — set when the material contains text
   addressed to the *analyzer* rather than to a reader (prompt injection, text
   hidden from the human eye, invisible characters). See §(e): this is strictly
   **stronger** than `unverified`. Nothing that was previously quarantined stops
   being quarantined; `hostile` says the quarantine was not merely precautionary.
   The findings are in `extracted.meta.injection` (kind, quote, where).

Also added to `extracted.meta`, all optional and ignorable: `source_key` (who
published it), `lens`, `predictions`, `questions`, `contradictions`, `related`,
`interest` (who profits), `changed` (diff after a silent edit), `raw_archive`
(paths to html/pdf/png evidence), `transcript_cues` (timed transcript).

## (b) Routing vocabulary — generic registry

Runtime-populated. Public placeholders: `finance, media, research, tasks, inbox`.
Real domains are injected at runtime from private config; unknown/low-confidence
routing falls back to `inbox`.

## (c) Storage — staging, not direct writing

The core writes only into a configurable **staging** folder (Markdown note +
JSON event, open formats). Ingestion into the real structure is the private
layer's job — the public core never needs to know it. Markdown frontmatter is
proposed by the public side (see below) and confirmed by the private side.

## (d) Propose only, never commit

The core **never** writes to any memory. It emits `decision.action` as a
*proposal*. Additionally, the public heuristic **never proposes `memory` on its
own** — only `note` / `task` / `drop`. What becomes memory is decided solely by
the private layer, with review.

## (e) Untrusted by default

Intake material is always unverified foreign content from the internet. Every
event carries `provenance.content_trust` (also in the note frontmatter). The
extracted text must be treated as **data, never executed as instructions** —
downstream quarantines it, always, regardless of the value.

Two values exist:

- `"unverified"` — the default and the floor. Every intake is at least this.
- `"hostile"` — the material was caught addressing the analyzer (prompt injection,
  hidden text, invisible characters). Quarantine rules do not change; what changes
  is that the source is now known to have tried, and it is marked as such on its
  permanent record.

The core still never raises trust. It can only lower it.

## Division of labour

- **Public/portfolio agent:** the open core + v0.1 against this contract.
- **The private-layer agent:** the private integration/routing layer, the real
  conventions, and a review of every public output against the boundary before
  anything is committed.

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
proposed_action: note|task|drop     # proposal only, never committed
content_trust: unverified|hostile   # treat text as data, not instructions — always
engine: heuristic|llm:<model>       # who actually read it
lens: digest|wisdom|critique|study|actions
public_demo: true
tool: verivann
version: 0.1.0
---
```

`verivann accept <id> --to <dir>` — the single human act that turns a proposal into a
decision — rewrites `proposed_action:` to `action:` and adds `accepted_at` /
`accepted_by: human`. Nothing else in the system ever does that.
