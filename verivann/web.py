"""The inbox - and the capture surface.

No framework: stdlib http.server only.

  Digest   paste (or share, or right-click) a link -> the routed, proposal-only note
  Library  search everything you digested, or ask it a question
  Keep/Drop  the verdict that teaches the router (see relevance.py)

Capture friction is the thing that kills tools like this: nobody opens a terminal
to save a video. So the same server is also:

  * a share target - install it as an app on the phone (`verivann serve --lan`) and
    Verivann appears in the system share sheet;
  * an endpoint for the browser extension (extensions/chrome) and the bookmarklet,
    both of which just hand it a URL.

Local-first: binds to 127.0.0.1 by default. `--lan` opens it to your own network
and then REQUIRES a token - an open intake endpoint on a shared network would let
anyone put material into your library.
"""

from __future__ import annotations

import json
import secrets
import threading
import webbrowser
from functools import lru_cache
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from .analysis.lenses import DEFAULT_LENS, describe
from .branding import icon_png
from .canonical import canonical_url, clean_input
from .config import Config
from .pipeline import run
from .render import render_markdown

_LOOPBACK = ("127.0.0.1", "localhost", "::1")

_LENS_OPTIONS = "".join(
    f'<option value="{name}"{" selected" if name == DEFAULT_LENS else ""}>{name} - {desc}</option>'
    for name, desc in describe()
)

MANIFEST = {
    "name": "Verivann",
    "short_name": "Verivann",
    "description": "raw web material → structured, routed notes",
    "start_url": "./",
    "scope": "./",
    "display": "standalone",
    "background_color": "#0a0a0d",
    "theme_color": "#0a0a0d",
    "icons": [
        {"src": "icon-192.png", "sizes": "192x192", "type": "image/png", "purpose": "any"},
        {"src": "icon-512.png", "sizes": "512x512", "type": "image/png", "purpose": "any maskable"},
    ],
    # The share sheet hands us title/text/url as query params - no service-worker
    # POST plumbing needed; the page picks them up on load and digests them.
    "share_target": {
        "action": "./",
        "method": "GET",
        "params": {"title": "title", "text": "text", "url": "u"},
    },
}

SERVICE_WORKER = """// Minimal: exists so the inbox is installable as an app (and thus a share target).
self.addEventListener('install', () => self.skipWaiting());
self.addEventListener('activate', (e) => e.waitUntil(self.clients.claim()));
self.addEventListener('fetch', (e) => e.respondWith(fetch(e.request)));
"""

PAGE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8" />
<meta name="viewport" content="width=device-width, initial-scale=1" />
<meta name="theme-color" content="#0a0a0d" />
<link rel="manifest" href="manifest.webmanifest" />
<link rel="icon" href="icon-192.png" />
<title>Verivann</title>
<style>
  :root { color-scheme: dark; }
  * { box-sizing: border-box; margin: 0; }
  body {
    background: #0a0a0d; color: #e9e7e0;
    font-family: ui-monospace, "JetBrains Mono", Menlo, monospace;
    min-height: 100vh; display: flex; justify-content: center; padding: 6vh 20px 14vh;
  }
  main { width: min(780px, 100%); }
  .brand { letter-spacing: .34em; font-size: 13px; color: #cbcac4; }
  .sub { color: #6d6c74; font-size: 11px; letter-spacing: .18em; margin-top: 8px; text-transform: uppercase; }
  .tabs { display: flex; gap: 8px; margin-top: 30px; }
  .tab {
    background: none; border: 1px solid #26262c; color: #7d7c84; border-radius: 100px;
    padding: 9px 22px; font: inherit; font-size: 11px; letter-spacing: .12em;
    text-transform: uppercase; cursor: pointer; transition: border-color .25s, color .25s;
  }
  .tab.active { border-color: #e9e7e0; color: #e9e7e0; }
  .panel { display: none; margin-top: 24px; }
  .panel.on { display: block; }
  textarea, input[type=text], select {
    width: 100%; background: #111116; color: #e9e7e0; border: 1px solid #26262c;
    border-radius: 12px; padding: 15px; font: inherit; font-size: 14px; outline: none;
    transition: border-color .3s;
  }
  textarea { min-height: 128px; resize: vertical; }
  select { font-size: 12px; padding: 11px 14px; cursor: pointer; }
  textarea:focus, input:focus, select:focus { border-color: #6a6a72; }
  .row { display: flex; gap: 12px; margin-top: 13px; align-items: center; flex-wrap: wrap; }
  .row .grow { flex: 1; min-width: 180px; }
  button.go {
    background: #e9e7e0; color: #0a0a0d; border: none; border-radius: 100px;
    padding: 12px 26px; font: inherit; font-size: 12px; letter-spacing: .12em;
    text-transform: uppercase; cursor: pointer;
  }
  button.ghost {
    background: none; color: #cbc9c2; border: 1px solid #33333a; border-radius: 100px;
    padding: 12px 24px; font: inherit; font-size: 12px; letter-spacing: .12em;
    text-transform: uppercase; cursor: pointer; transition: border-color .25s;
  }
  button.ghost:hover { border-color: #6a6a72; }
  button:disabled { opacity: .4; cursor: default; }
  .hint { color: #55545c; font-size: 11px; line-height: 1.6; }
  .hint a { color: #8f8d95; }
  .badges { display: flex; gap: 10px; flex-wrap: wrap; margin: 24px 0 14px; align-items: center; }
  .badge { border: 1px solid #2a2a31; border-radius: 100px; padding: 6px 14px; font-size: 11px; letter-spacing: .1em; color: #b8b6b0; }
  .badge b { color: #ece9e1; font-weight: 600; }
  .warn { color: #b58b5a; }
  .again { color: #7d7c84; }
  .verdict { margin-left: auto; display: flex; gap: 8px; }
  .verdict button {
    background: none; border: 1px solid #33333a; color: #8f8d95; border-radius: 100px;
    padding: 6px 15px; font: inherit; font-size: 11px; letter-spacing: .08em; cursor: pointer;
  }
  .verdict button:hover { border-color: #6a6a72; color: #e9e7e0; }
  .verdict button.done { border-color: #e9e7e0; color: #e9e7e0; }
  pre {
    background: #111116; border: 1px solid #26262c; border-radius: 12px; padding: 20px;
    overflow-x: auto; white-space: pre-wrap; word-break: break-word;
    font-size: 12.5px; line-height: 1.6; color: #cbc9c2;
  }
  .answer {
    background: #13131a; border: 1px solid #33333a; border-radius: 12px; padding: 20px;
    font-size: 13.5px; line-height: 1.7; color: #ece9e1; margin: 22px 0 4px; white-space: pre-wrap;
  }
  .hit { border-bottom: 1px solid #1c1c22; padding: 15px 0; }
  .hit .t { color: #ece9e1; font-size: 13px; }
  .hit .m { color: #6d6c74; font-size: 11px; margin-top: 5px; }
  .hit .s { color: #8f8d95; font-size: 11.5px; margin-top: 7px; line-height: 1.55; }
  .err { color: #c96a6a; margin-top: 18px; font-size: 12px; }
  footer { margin-top: 40px; color: #45444b; font-size: 10.5px; letter-spacing: .04em; }
  footer a { color: #6d6c74; }
</style>
</head>
<body>
<main>
  <div class="brand">VERIVANN</div>
  <div class="sub">raw web material &rarr; structured, routed notes</div>

  <div class="tabs">
    <button class="tab active" data-panel="digest">Digest</button>
    <button class="tab" data-panel="library">Library</button>
    <button class="tab" data-panel="mirror">Mirror</button>
  </div>

  <section class="panel on" id="p-digest">
    <textarea id="v" placeholder="Paste a link, or any text&hellip;" autofocus></textarea>
    <div class="row">
      <button class="go" id="go">Digest</button>
      <select id="lens" class="grow" title="Reading intent">__LENS_OPTIONS__</select>
    </div>
    <div class="row"><span class="hint">Links are fetched. Everything digested is treated as untrusted data.</span></div>
    <div id="dres" style="display:none">
      <div class="badges" id="badges"></div>
      <pre id="note"></pre>
    </div>
  </section>

  <section class="panel" id="p-library">
    <input type="text" id="q" placeholder="Search your notes &mdash; or ask them a question&hellip;" />
    <div class="row">
      <button class="go" id="btn-ask">Ask</button>
      <button class="ghost" id="btn-search">Search</button>
      <span class="hint">Answers come only from what you have digested.</span>
    </div>
    <div id="lres" style="display:none">
      <div class="answer" id="answer" style="display:none"></div>
      <div id="hits"></div>
    </div>

    <div id="reader" style="display:none">
      <div class="row">
        <button class="ghost" id="back">&larr; back</button>
        <span class="hint" id="rmeta"></span>
      </div>
      <div class="answer" id="rhl" style="display:none"></div>
      <pre id="rbody"></pre>
      <div class="row">
        <button class="go" id="mark" disabled>Highlight selection</button>
        <span class="hint">A highlight is the strongest thing you can say about a source - the router counts it.</span>
      </div>
    </div>
  </section>

  <section class="panel" id="p-mirror">
    <div class="answer" id="verdict" style="display:block">…</div>
    <div id="stats"></div>
    <div class="row" style="margin-top:26px">
      <input type="text" id="newq" class="grow" placeholder="A question you are trying to answer&hellip;" />
      <button class="ghost" id="addq">Ask it</button>
    </div>
    <div id="questions"></div>
  </section>

  <div class="err" id="err"></div>
  <footer>
    Capture without typing: drag <a id="bm" href="#">Verivann this</a> to your bookmarks bar &middot;
    install this page as an app to get Verivann in the share sheet.
  </footer>
</main>

<script>
  const $ = (id) => document.getElementById(id);
  const params = new URLSearchParams(location.search);

  // Token: handed over in the URL once (LAN mode), then kept locally.
  const TOKEN = params.get('token') || localStorage.getItem('verivann_token') || '';
  if (TOKEN) localStorage.setItem('verivann_token', TOKEN);

  let lastId = null;

  if ('serviceWorker' in navigator) navigator.serviceWorker.register('sw.js').catch(() => {});

  document.querySelectorAll('.tab').forEach((t) => t.addEventListener('click', () => {
    document.querySelectorAll('.tab').forEach((x) => x.classList.remove('active'));
    document.querySelectorAll('.panel').forEach((x) => x.classList.remove('on'));
    t.classList.add('active');
    $('p-' + t.dataset.panel).classList.add('on');
    $('err').textContent = '';
    if (t.dataset.panel === 'mirror') loadMirror();
  }));

  // A first guess only - the server cleans the value and decides for real.
  function detectKind(s) {
    s = s.trim().replace(/^[("'`\\[<]+/, '');
    if (/^https?:\\/\\//i.test(s) && !/\\n/.test(s)) {
      return /youtube\\.com|youtu\\.be/i.test(s) ? 'youtube' : 'url';
    }
    return 'text';
  }

  function esc(s) {
    return String(s == null ? '' : s).replace(/[&<>"]/g, (c) =>
      ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
  }

  async function post(path, body) {
    const headers = { 'content-type': 'application/json' };
    if (TOKEN) headers['x-verivann-token'] = TOKEN;
    const res = await fetch(path, { method: 'POST', headers, body: JSON.stringify(body) });
    const data = await res.json();
    if (!res.ok || data.error) throw new Error(data.error || ('status ' + res.status));
    return data;
  }

  async function digest() {
    const value = $('v').value.trim();
    if (!value) return;
    $('err').textContent = '';
    $('go').disabled = true; $('go').textContent = 'Digesting…';
    try {
      const d = await post('/intake', { kind: detectKind(value), value, lens: $('lens').value });
      lastId = d.id;
      $('badges').innerHTML =
        '<span class="badge">domain <b>' + esc(d.domain) + '</b></span>' +
        '<span class="badge">proposal <b>' + esc(d.action) + '</b></span>' +
        '<span class="badge">confidence <b>' + esc(d.confidence) + '</b></span>' +
        '<span class="badge">lens <b>' + esc(d.lens) + '</b></span>' +
        '<span class="badge warn">content <b>unverified</b></span>' +
        (d.reingested ? '<span class="badge again">re-read <b>known source</b></span>' : '') +
        '<span class="verdict"><button id="keep">Keep</button><button id="drop">Drop</button></span>';
      $('note').textContent = d.markdown;
      $('dres').style.display = 'block';
      $('keep').addEventListener('click', () => verdict('kept', $('keep')));
      $('drop').addEventListener('click', () => verdict('dropped', $('drop')));
    } catch (ex) { $('err').textContent = 'Failed: ' + ex.message; }
    finally { $('go').disabled = false; $('go').textContent = 'Digest'; }
  }

  $('go').addEventListener('click', digest);

  async function verdict(v, btn) {
    if (!lastId) return;
    try {
      const d = await post('/feedback', { id: lastId, verdict: v });
      btn.classList.add('done');
      btn.textContent = (v === 'kept' ? 'Kept' : 'Dropped') + ' · ' + d.judged + ' judged';
    } catch (ex) { $('err').textContent = 'Failed: ' + ex.message; }
  }

  function renderHits(hits) {
    $('hits').innerHTML = hits.length ? hits.map((h, i) =>
      '<div class="hit" data-id="' + esc(h.id) + '" style="cursor:pointer">' +
      '<div class="t">[' + (i + 1) + '] ' + esc(h.title) + '</div>' +
      '<div class="m">' + esc(h.domain) + ' · ' + esc((h.created_at || '').slice(0, 10)) +
      ' · ' + esc((h.source_ref || '').slice(0, 70)) + '</div>' +
      (h.snippet ? '<div class="s">' + esc(h.snippet) + '</div>' : '') + '</div>'
    ).join('') : '<div class="hit"><div class="m">(nothing in your library matches)</div></div>';
    $('lres').style.display = 'block';
    $('reader').style.display = 'none';
    document.querySelectorAll('#hits .hit[data-id]').forEach((el) =>
      el.addEventListener('click', () => openNote(el.dataset.id)));
  }

  // The reader. Clicking a hit is itself a signal - you searched, and you chose this one.
  let readingId = null;

  async function openNote(id) {
    try {
      const d = await post('/note', { id });
      readingId = d.id;
      $('lres').style.display = 'none';
      $('reader').style.display = 'block';
      $('rmeta').textContent = d.title + '  ·  ' + d.source + '  ·  ' + (d.source_ref || '');
      $('rbody').textContent = d.text || d.markdown;
      renderHighlights(d.highlights || []);
    } catch (ex) { $('err').textContent = 'Failed: ' + ex.message; }
  }

  // NOTE: this page is a Python string. Every backslash meant for the BROWSER must
  // be doubled in the Python source, or Python eats it and splits the JS literal in
  // half - which is exactly how this whole script once died, in silence.
  function renderHighlights(list) {
    if (!list.length) { $('rhl').style.display = 'none'; return; }
    $('rhl').style.display = 'block';
    $('rhl').textContent = 'Your highlights:\\n\\n' + list.map((h) => '· ' + h).join('\\n');
  }

  $('back').addEventListener('click', () => {
    $('reader').style.display = 'none';
    $('lres').style.display = 'block';
    readingId = null;
  });

  document.addEventListener('selectionchange', () => {
    const text = String(document.getSelection() || '').trim();
    $('mark').disabled = !(readingId && text.length > 8);
  });

  $('mark').addEventListener('click', async () => {
    const text = String(document.getSelection() || '').trim();
    if (!readingId || text.length < 9) return;
    try {
      const d = await post('/highlight', { id: readingId, text });
      renderHighlights(d.highlights);
      $('mark').disabled = true;
    } catch (ex) { $('err').textContent = 'Failed: ' + ex.message; }
  });

  async function query(path, btn) {
    const q = $('q').value.trim();
    if (!q) return;
    $('err').textContent = '';
    const label = btn.textContent;
    btn.disabled = true; btn.textContent = '…';
    try {
      const d = await post(path, { query: q, question: q });
      if (d.answer) { $('answer').textContent = d.answer; $('answer').style.display = 'block'; }
      else { $('answer').style.display = 'none'; }
      renderHits(d.hits || []);
    } catch (ex) { $('err').textContent = 'Failed: ' + ex.message; }
    finally { btn.disabled = false; btn.textContent = label; }
  }

  $('btn-ask').addEventListener('click', () => query('/ask', $('btn-ask')));
  $('btn-search').addEventListener('click', () => query('/search', $('btn-search')));
  $('q').addEventListener('keydown', (e) => { if (e.key === 'Enter') query('/ask', $('btn-ask')); });

  // The mirror: hours in, notes kept, where the time went - and your open questions.
  async function loadMirror() {
    try {
      const d = await post('/mirror', {});
      $('verdict').textContent = d.verdict;
      const rows = [
        ['material in', d.hours + ' h'],
        ['notes', d.notes],
        ['kept / dropped / unjudged', d.kept + ' / ' + d.dropped + ' / ' + d.unjudged],
        ['read by a model', d.analyzed + ' of ' + d.notes],
      ];
      $('stats').innerHTML = rows.map(([k, v]) =>
        '<div class="hit"><div class="m">' + esc(k) + '</div><div class="t">' + esc(v) + '</div></div>'
      ).join('') + (d.sinks || []).map((s) =>
        '<div class="hit"><div class="t">' + esc(s[0]) + '</div><div class="m">' +
        esc(s[1]) + ' min · ' + esc(s[2]) + ' kept</div></div>'
      ).join('');
      renderQuestions(d.questions || []);
    } catch (ex) { $('err').textContent = 'Failed: ' + ex.message; }
  }

  function renderQuestions(list) {
    $('questions').innerHTML = list.length ? list.map((q) =>
      '<div class="hit"><div class="t">[' + q.id + '] ' + esc(q.text) + '</div>' +
      '<div class="m">' + q.evidence + ' advancing · ' + q.against + ' contradicting</div></div>'
    ).join('') : '<div class="hit"><div class="m">(no open questions - material is routed to folders, ' +
      'which tells you where a thing went, never why it mattered)</div></div>';
  }

  $('addq').addEventListener('click', async () => {
    const text = $('newq').value.trim();
    if (!text) return;
    try {
      const d = await post('/question', { text });
      $('newq').value = '';
      renderQuestions(d.questions);
    } catch (ex) { $('err').textContent = 'Failed: ' + ex.message; }
  });
  $('newq').addEventListener('keydown', (e) => { if (e.key === 'Enter') $('addq').click(); });

  // The bookmarklet: any page -> back here with the URL already in the box.
  const here = location.origin + location.pathname;
  $('bm').href = "javascript:(()=>{location.href='" + here +
    "?u='+encodeURIComponent(location.href)+'&title='+encodeURIComponent(document.title)})()";
  $('bm').addEventListener('click', (e) => e.preventDefault());

  // Shared in from the phone, the extension, or the bookmarklet: pre-fill and wait for
  // one click. We do NOT auto-digest: a cross-site link to /?u=… is indistinguishable
  // from a genuine share, so auto-firing would let any website drive this page (which
  // holds the token) into fetching a URL and staging a note - a confused-deputy. One
  // deliberate press closes that, and the shared value is already in the box, ready.
  const shared = (params.get('u') || params.get('text') || '').trim();
  if (shared) {
    $('v').value = shared;
    if (params.get('lens')) $('lens').value = params.get('lens');
    history.replaceState({}, '', here);  // don't leave the URL (or token) in the bar
    $('go').focus();  // Enter or click digests - a conscious commit, not a drive-by
  }
</script>
</body>
</html>
""".replace("__LENS_OPTIONS__", _LENS_OPTIONS)


@lru_cache(maxsize=4)
def _icon(size: int) -> bytes:
    return icon_png(size)


def _kind_of(value: str, claimed: str) -> str:
    """A single cleaned URL is a link, whatever the caller called it."""
    if "\n" in value or not value.lower().startswith(("http://", "https://")):
        return "text"
    low = value.lower()
    if "youtube.com" in low or "youtu.be" in low:
        return "youtube"
    return "url" if claimed == "text" else claimed


# ---------- request authorization (the CSRF/CORS defense) ----------
#
# The inbox is an HTTP API on localhost. Without a guard, ANY website the user
# visits could `fetch()` /ask (to read the whole library) or /intake (to poison
# it) - a classic cross-site attack against a local server. So every API call must
# prove one of two things:
#
#   * it carries the session token (the page has it from the URL; a CLI/curl user
#     passes it) - a website cannot know it; or
#   * it comes from a browser-extension origin (chrome-extension://…), which the
#     browser sets and a web page CANNOT forge - so our own extension works
#     zero-config while websites stay locked out.
#
# CORS is never `*`: only extension origins are reflected, so even a "simple"
# cross-origin POST from a website cannot read a response.

_EXTENSION_PREFIXES = ("chrome-extension://", "moz-extension://", "safari-web-extension://")


def _is_extension_origin(origin: str) -> bool:
    return bool(origin) and origin.startswith(_EXTENSION_PREFIXES)


def is_authorized(origin: str, given_token: str, configured_token: str) -> bool:
    if _is_extension_origin(origin):
        return True
    if not configured_token:
        return True  # only when explicitly run without a token
    return bool(given_token) and secrets.compare_digest(given_token, configured_token)


def cors_origin(origin: str) -> str | None:
    """The only origins we ever reflect - never a wildcard."""
    return origin if _is_extension_origin(origin) else None


class _Handler(BaseHTTPRequestHandler):
    token = ""  # set by serve(); empty = loopback, no auth

    # ---------- plumbing ----------

    def _send(self, code: int, body: bytes | str, ctype: str = "text/html; charset=utf-8") -> None:
        data = body.encode("utf-8") if isinstance(body, str) else body
        self.send_response(code)
        self.send_header("content-type", ctype)
        self.send_header("content-length", str(len(data)))
        # CORS: reflect ONLY a browser-extension origin, never a wildcard, so a
        # website can never read a response cross-origin.
        allowed = cors_origin(self.headers.get("origin", ""))
        if allowed:
            self.send_header("access-control-allow-origin", allowed)
            self.send_header("access-control-allow-headers", "content-type, x-verivann-token")
            self.send_header("access-control-allow-methods", "GET, POST, OPTIONS")
        self.send_header("vary", "Origin")
        # Don't let another page frame the inbox (clickjacking), and no MIME sniffing.
        self.send_header("x-frame-options", "DENY")
        self.send_header("x-content-type-options", "nosniff")
        self.send_header("referrer-policy", "no-referrer")
        self.end_headers()
        self.wfile.write(data)

    def _json(self, code: int, obj: dict) -> None:
        self._send(code, json.dumps(obj), "application/json")

    def _body(self) -> dict:
        length = int(self.headers.get("content-length", 0) or 0)
        raw = self.rfile.read(length).decode("utf-8") if length else "{}"
        try:
            return json.loads(raw)
        except ValueError:
            return {}

    def _authorized(self) -> bool:
        given = self.headers.get("x-verivann-token", "")
        if not given and "token=" in self.path:
            given = self.path.split("token=", 1)[1].split("&", 1)[0]
        return is_authorized(self.headers.get("origin", ""), given, self.token)

    def do_OPTIONS(self) -> None:  # noqa: N802 - CORS preflight from the extension
        self._send(204, b"", "text/plain")

    def do_GET(self) -> None:  # noqa: N802
        # GET serves only the static shell (page, manifest, worker, icons, health).
        # It carries no library data, so it needs no token; the API (POST) is gated.
        path = self.path.split("?", 1)[0]
        if path in ("/", "/index.html"):
            return self._send(200, PAGE)
        if path == "/manifest.webmanifest":
            return self._send(200, json.dumps(MANIFEST), "application/manifest+json")
        if path == "/sw.js":
            return self._send(200, SERVICE_WORKER, "text/javascript")
        if path in ("/icon-192.png", "/icon-512.png"):
            return self._send(200, _icon(192 if "192" in path else 512), "image/png")
        if path == "/health":
            return self._json(200, {"ok": True, "tool": "verivann"})
        self._send(404, "not found", "text/plain")

    def do_POST(self) -> None:  # noqa: N802
        routes = {
            "/intake": self._intake,
            "/search": self._search,
            "/ask": self._ask,
            "/feedback": self._feedback,
            "/mirror": self._mirror,
            "/question": self._question,
            "/note": self._note,
            "/highlight": self._highlight,
        }
        handler = routes.get(self.path.split("?", 1)[0])
        if handler is None:
            return self._send(404, "not found", "text/plain")
        if not self._authorized():
            return self._json(401, {"error": "unauthorized"})
        try:
            handler()
        except Exception as exc:  # noqa: BLE001 - report any failure to the page
            self._json(500, {"error": str(exc)})

    # ---------- endpoints ----------

    def _intake(self) -> None:
        payload = self._body()
        value = clean_input(payload.get("value") or "")
        lens = (payload.get("lens") or "").strip() or None
        if not value:
            return self._json(400, {"error": "empty"})
        # The server decides what this is, not the caller: a URL pasted out of
        # Markdown ("(https://…)") reached the old client-side check as "text" and
        # became a note whose title was the raw string. Clean first, then classify.
        kind = _kind_of(value, payload.get("kind", "text"))

        known = None
        if kind in ("url", "youtube"):
            from .library import find_by_ref

            known = find_by_ref(canonical_url(value), Config.load().staging_dir)
            result = run(kind, ref=value, lens=lens)
        else:
            result = run("text", ref="text", text=value, lens=lens)

        event = result.event
        self._json(200, {
            "id": event.id,
            "domain": event.routing.domain,
            "confidence": event.routing.confidence,
            "action": event.decision.action,
            "reason": event.routing.reason,
            "lens": (event.extracted.meta or {}).get("lens", DEFAULT_LENS),
            "reingested": bool(known),
            "markdown": render_markdown(event),
            "note_path": str(result.note_path),
        })

    @staticmethod
    def _serialize(hits) -> list[dict]:
        return [
            {"id": h.id, "title": h.title, "domain": h.domain, "created_at": h.created_at,
             "source_ref": h.source_ref, "snippet": h.snippet}
            for h in hits
        ]

    def _note(self) -> None:
        """Open a note for reading. Opening it is itself a (weak) verdict."""
        from .library import highlights_of, note_row, source_of
        from .signals import observe

        note_id = (self._body().get("id") or "").strip()
        staging = Config.load().staging_dir
        row = note_row(note_id, staging)
        if row is None:
            return self._json(404, {"error": "unknown note"})

        observe(row["id"], "click", staging)  # you searched, and you chose this one
        markdown = ""
        try:
            markdown = Path(row["note_path"]).read_text(encoding="utf-8")
        except OSError:
            pass
        self._json(200, {
            "id": row["id"],
            "title": row["title"],
            "source": source_of(row["id"], staging),
            "source_ref": row["source_ref"],
            "text": row["text"],
            "markdown": markdown,
            "highlights": highlights_of(row["id"], staging),
        })

    def _highlight(self) -> None:
        """A highlight is the strongest signal a human emits. We used to throw it away."""
        from .library import add_highlight, highlights_of
        from .signals import observe

        payload = self._body()
        note_id = (payload.get("id") or "").strip()
        text = (payload.get("text") or "").strip()
        if not note_id or len(text) < 9:
            return self._json(400, {"error": "id and a real selection required"})
        staging = Config.load().staging_dir
        add_highlight(note_id, text, staging)
        observe(note_id, "highlight", staging)
        self._json(200, {"highlights": highlights_of(note_id, staging)})

    def _search(self) -> None:
        from .library import keywords, search

        query = (self._body().get("query") or "").strip()
        if not query:
            return self._json(400, {"error": "empty"})
        hits = search(keywords(query) or query, Config.load().staging_dir, limit=12)
        self._json(200, {"answer": None, "hits": self._serialize(hits)})

    def _ask(self) -> None:
        from .ask import ask

        question = (self._body().get("question") or "").strip()
        if not question:
            return self._json(400, {"error": "empty"})
        result = ask(question)
        self._json(200, {
            "answer": result.answer or None,
            "hits": self._serialize(result.hits),
            "engine": result.engine,
        })

    def _feedback(self) -> None:
        from .library import record_feedback
        from .relevance import load_profile

        payload = self._body()
        note_id = (payload.get("id") or "").strip()
        verdict = (payload.get("verdict") or "").strip()
        if not note_id or verdict not in ("kept", "dropped"):
            return self._json(400, {"error": "id and verdict (kept|dropped) required"})
        staging = Config.load().staging_dir
        if record_feedback(note_id, verdict, staging) is None:
            return self._json(404, {"error": "unknown note"})
        profile = load_profile(staging)
        self._json(200, {"verdict": verdict, "judged": profile.judged, "active": profile.active})

    def _mirror(self) -> None:
        from .stats import mirror

        config = Config.load()
        m = mirror(config.staging_dir, days=30)
        self._json(200, {
            "verdict": m.verdict(),
            "hours": m.hours,
            "notes": m.notes,
            "kept": m.kept,
            "dropped": m.dropped,
            "unjudged": m.unjudged,
            "analyzed": m.analyzed,
            "sinks": [[s, minutes, kept] for s, minutes, kept in m.time_sinks],
            "questions": self._questions(config),
        })

    def _question(self) -> None:
        from .questions import add

        text = (self._body().get("text") or "").strip()
        if not text:
            return self._json(400, {"error": "empty"})
        add(text)
        self._json(200, {"questions": self._questions(Config.load())})

    @staticmethod
    def _questions(config) -> list[dict]:
        from .questions import listing

        return [
            {"id": q.id, "text": q.text, "evidence": q.evidence, "against": q.against}
            for q in listing(config)
        ]

    def log_message(self, *args, **kwargs) -> None:  # keep the console quiet
        pass


def _lan_ip() -> str:
    import socket

    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as probe:
        try:
            probe.connect(("10.255.255.255", 1))  # no packet is sent; just picks the route
            return probe.getsockname()[0]
        except OSError:
            return "127.0.0.1"


def serve(
    host: str = "127.0.0.1",
    port: int = 8130,
    open_browser: bool = True,
    token: str | None = None,
) -> None:
    exposed = host not in _LOOPBACK
    # A token is ALWAYS required - even on loopback. Any website the user visits can
    # reach 127.0.0.1, so the token is what keeps a web page out of the library. The
    # page picks it up from the URL we open; the browser extension is trusted by its
    # origin and needs no token.
    if not token:
        token = secrets.token_urlsafe(12)
    _Handler.token = token

    server = ThreadingHTTPServer((host, port), _Handler)
    suffix = f"?token={token}"
    local = f"http://{'127.0.0.1' if exposed else host}:{port}/{suffix}"

    print(f"Verivann inbox -> {local}")
    print("  (the token in that URL is required - open it, don't just type the address)")
    if exposed:
        print(f"  on your phone -> http://{_lan_ip()}:{port}/{suffix}")
        print("  (open it once, then 'Add to home screen' - Verivann joins the share sheet)")
    print("  Ctrl+C to stop")

    if open_browser:
        threading.Timer(0.6, lambda: webbrowser.open(local)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nstopped.")
    finally:
        server.server_close()
