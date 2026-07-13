# Security Policy

Verivann runs on your own machine and is built to be defensive by design — local-first,
no account, no telemetry, and nothing leaves the machine unless you ask. Even so, it
fetches URLs you paste, runs a small local HTTP server for the inbox, invokes external
tools, and sends untrusted material to a model. Those are real surfaces, and reports
about them are welcome.

## Reporting a vulnerability

**Please do not open a public issue for a security problem.**

Use GitHub's private reporting instead: on this repository, go to the **Security** tab →
**Report a vulnerability** (GitHub Security Advisories). It reaches the maintainer
privately and needs no email address from either side.

When you report, it helps to include:

- what the weakness is and roughly how severe you think it is;
- a concrete reproduction — inputs, steps, and what happens versus what should;
- the affected version (`vv doctor` prints it) and your OS / Python version.

You can expect an acknowledgement within about a week, and a fix or a clear decision
before any public disclosure. This is a volunteer, donation-supported project, so please
be patient — but every genuine report will get a genuine answer.

## What is in scope

The hardened surfaces, and the kind of thing worth reporting:

- **The local inbox server** (`verivann/web.py`) — any way a website open in your browser
  could read your notes or trigger actions on the local server (CSRF / confused-deputy),
  or reach it without the token.
- **Server-side fetches** (`verivann/net.py`) — any way a crafted URL or redirect chain
  makes the server fetch an internal address (SSRF): cloud-metadata endpoints, loopback,
  private / shared / reserved ranges.
- **External-tool invocation** (`verivann/adapters/…`, `verivann/batch.py`) — any way a
  user-controlled URL becomes an argument/flag to yt-dlp, gallery-dl, monolith, ffmpeg,
  etc. (argument injection).
- **Prompt injection** (`verivann/analysis/llm.py`, `verivann/security.py`) — material
  that makes the analyzer follow instructions inside it, or that leaks / evades the
  control-token canary.
- **The commit gate and erasure** (`verivann/accept.py`, `verivann/vault.py`) — any way a
  note overwrites a different note in your vault, or a purge deletes the wrong thing.

## What is out of scope

- **DNS rebinding** against the SSRF guard — a documented residual for a single-user local
  tool (closing it means pinning the resolved IP per connection). Noted, not a surprise.
- Issues that require an attacker to already have local access to your machine, your
  filesystem, or your `.env`.
- The security of third-party tools Verivann only *invokes* (yt-dlp and friends) — report
  those upstream. Keeping them current is what `vv doctor` nudges you to do.
- Denial of service from feeding Verivann enormous inputs on your own machine.

Thank you for helping keep it trustworthy.
