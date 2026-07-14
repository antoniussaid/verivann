# Privacy

Verivann is local-first. The short version: it collects nothing about you, and
nothing leaves your machine unless you explicitly configure it to.

## The app (`verivann` / `vv`)

- No account, no sign-up, no telemetry, no analytics, no phone-home.
- Your library, your notes, your ledgers and your learned profile live only on your
  machine, in a folder you own.
- The only time anything leaves your machine is when you deliberately configure a
  hosted model (a cloud LLM). Even then, sensitive material is redacted or kept local
  first, and `vv outbound` logs exactly what was sent, to whom, and what it cost.
- Nothing is ever sent to the author of Verivann.

## The browser extension

- It talks ONLY to your own Verivann server running locally at `127.0.0.1`.
- It sends the page, link, or selection you choose to that local server, and nothing
  else, to no one else. No remote host is contacted by default.
- It stores only your own settings (your local inbox address, an optional access
  token, your reading preference) via the browser's sync storage. These are never
  transmitted anywhere except to your own server.
- No tracking, no analytics, no advertising, no data sold or shared.

## Third-party tools

Verivann can invoke external programs you install yourself (yt-dlp, Whisper,
tesseract, and so on). Those run on your machine under their own terms; Verivann does
not send them your data beyond the specific item you asked it to process.

## Questions

Open an issue at https://github.com/antoniussaid/verivann, or for anything sensitive
see [SECURITY.md](SECURITY.md).
