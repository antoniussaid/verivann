# Verivann — Chrome extension

Capture is where tools like this die: nobody opens a terminal to save a video.
This removes that step. Right-click a page, a link, or a selection → it lands in
your own Verivann inbox, routed, with a proposal — and you can keep or drop it right
there, which is what teaches the router.

The extension talks **only** to your own Verivann server. There is no backend, no
account, no telemetry.

## Install (unpacked — it is not in the Web Store)

1. Start the inbox: `verivann serve` (leave it running).
2. Chrome → `chrome://extensions` → enable **Developer mode**.
3. **Load unpacked** → select this folder.
4. Optional: pin it, and use **Alt+S** to verivann the page you are on.

## Use

| | |
|---|---|
| Toolbar button / **Alt+S** | Digest the current page. Pick a lens, then Keep / Drop. |
| Right-click → *Verivann this page / link* | Send it without leaving the page. The badge shows the routed domain. |
| Right-click a selection → *Verivann selection* | Digest just the highlighted text. |

A red `!` badge means the inbox is not reachable — start `verivann serve`, or fix the
endpoint under *settings*.

## Settings

- **Endpoint** — `http://127.0.0.1:8130` by default. If you run `verivann serve --lan`
  (e.g. so your phone can reach it too), point the extension at that address; Chrome
  will ask you to grant permission for that host.
- **Token** — only needed in LAN mode; `verivann serve --lan` prints it.
- **Default lens** — `digest`, `wisdom`, `critique`, `study`, `actions`.

## Icons

Generated, not committed by hand — they come from the same mark the PWA uses:

```bash
python -c "from verivann.branding import icon_png; import pathlib; \
[pathlib.Path(f'extensions/chrome/icons/icon-{s}.png').write_bytes(icon_png(s)) for s in (16,32,48,128)]"
```
