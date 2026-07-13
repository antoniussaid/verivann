# Smelt — Chrome extension

Capture is where tools like this die: nobody opens a terminal to save a video.
This removes that step. Right-click a page, a link, or a selection → it lands in
your own Smelt inbox, routed, with a proposal — and you can keep or drop it right
there, which is what teaches the router.

The extension talks **only** to your own Smelt server. There is no backend, no
account, no telemetry.

## Install (unpacked — it is not in the Web Store)

1. Start the inbox: `smelt serve` (leave it running).
2. Chrome → `chrome://extensions` → enable **Developer mode**.
3. **Load unpacked** → select this folder.
4. Optional: pin it, and use **Alt+S** to smelt the page you are on.

## Use

| | |
|---|---|
| Toolbar button / **Alt+S** | Digest the current page. Pick a lens, then Keep / Drop. |
| Right-click → *Smelt this page / link* | Send it without leaving the page. The badge shows the routed domain. |
| Right-click a selection → *Smelt selection* | Digest just the highlighted text. |

A red `!` badge means the inbox is not reachable — start `smelt serve`, or fix the
endpoint under *settings*.

## Settings

- **Endpoint** — `http://127.0.0.1:8130` by default. If you run `smelt serve --lan`
  (e.g. so your phone can reach it too), point the extension at that address; Chrome
  will ask you to grant permission for that host.
- **Token** — only needed in LAN mode; `smelt serve --lan` prints it.
- **Default lens** — `digest`, `wisdom`, `critique`, `study`, `actions`.

## Icons

Generated, not committed by hand — they come from the same mark the PWA uses:

```bash
python -c "from smelt.branding import icon_png; import pathlib; \
[pathlib.Path(f'extensions/chrome/icons/icon-{s}.png').write_bytes(icon_png(s)) for s in (16,32,48,128)]"
```
