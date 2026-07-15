# Contributing to Verivann

Thanks for looking. Verivann is a local-first intake router with a strong point of view,
and the point of view is the product, so the most useful contributions respect a few
invariants rather than working around them. This page is short on purpose.

## Getting set up

You need Python 3.10 or newer.

```bash
git clone <your-fork>
cd verivann
python -m venv .venv
. .venv/bin/activate            # Windows: .venv\Scripts\activate
pip install -e ".[dev]"
```

Run the checks before you push, CI runs exactly these:

```bash
ruff check .
pytest -q
```

Everything is offline and deterministic: the test suite never calls a real model or the
network (both are mocked), so it runs anywhere in seconds.

## The invariants (please don't break these)

These are not style preferences, they are what makes Verivann *Verivann*. A change that
crosses one of them will be asked to find another way.

1. **Propose-only.** Nothing is ever written into your knowledge base automatically. The
   router proposes; a human accepts. `accept` is the one committing act. New features
   propose; they do not commit.
2. **Untrusted by default.** Captured material is *data*, never instructions. It is
   scanned for injection, and every model call plants a canary so a successful hijack is
   observable from outside. Never feed material to a model as if it were a command.
3. **Orchestrate, don't bundle.** External tools (yt-dlp, gallery-dl, monolith, ffmpeg,
   tesseract, …) are *invoked as subprocesses, never imported*. That is deliberate: it
   keeps their copyleft licenses at arm's length and keeps their upgrade treadmill out of
   Verivann's release cycle. Always pass a user URL after `--`, and never `shell=True`.
4. **Local-first, no phone-home.** No account, no telemetry, no required cloud. Anything
   that leaves the machine is opt-in, routed by the privacy layer, and shows up in
   `vv outbound`. Sensitive material stays with the local model or the heuristic, it is
   never uploaded to earn a nicer summary.
5. **No lock-in.** Notes are plain Markdown in a folder you own. `export`, `backup`, and
   `purge` must keep that promise literally true.
6. **The media policy is not configurable.** For platforms with technical protection
   measures, Verivann works from captions/transcripts only. This is a legal boundary
   (§90c UrhG / InfoSoc Art. 6), not a setting.

## Sending a change

- Keep the diff focused; one idea per PR.
- Add or update tests, a behavior worth adding is worth a test, and a bug worth fixing is
  worth a regression test.
- Match the surrounding code: comment density, naming, and idiom. Comments explain *why*,
  not *what*.
- Make sure `ruff check .` and `pytest -q` are green.
- The pull-request template has a short checklist; filling it in speeds up review.

## Reporting bugs and ideas

- **Bugs / features:** open an issue, the templates ask for the few things that make a
  report actionable (including your `vv doctor` output, which answers half of them).
- **Security problems:** please do *not* open a public issue, see [SECURITY.md](SECURITY.md).

By contributing, you agree your work is licensed under the project's MIT license.
