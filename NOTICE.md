# Third-party software

Verivann is licensed under the MIT License (see [LICENSE](LICENSE)).

## Python dependencies (bundled via pip)

Verivann's runtime dependencies are all permissively licensed:

| Package | License |
|---|---|
| pydantic | MIT |
| typer | MIT |
| httpx | BSD-3-Clause |
| beautifulsoup4 | MIT |
| pypdf (optional, `[documents]`) | BSD-3-Clause |
| faster-whisper (optional, `[whisper]`) | MIT |

Transitive dependencies (httpcore, anyio, certifi, click, rich, …) are MIT /
BSD / Apache-2.0 / ISC, with the sole exception of `certifi` (Mozilla Public
License 2.0), a certificate bundle used unmodified, which imposes no obligation
beyond this notice.

## External tools (invoked, never bundled)

Verivann *orchestrates* other programs, it calls them as separate processes and
never imports, links, ships, or mirrors them. The user installs whichever ones
they want; Verivann only detects and uses what is present. Because they are
separate programs, their licenses (including the copyleft ones below) do not
extend to Verivann's own code.

| Tool | What it does for Verivann | License |
|---|---|---|
| yt-dlp | video metadata + captions | Unlicense (PyInstaller builds: GPL-3.0) |
| gallery-dl | image galleries | GPL-2.0 |
| tesseract | OCR of images / video frames | Apache-2.0 |
| ffmpeg | keyframe extraction | LGPL-2.1+ / GPL-2+ |
| monolith | self-contained HTML archive | GPL-3.0 |
| single-file | self-contained HTML archive | AGPL-3.0 |
| whisper.cpp | local transcription | MIT |
| headless Chrome / Edge | PDF + screenshot archive | (system browser) |
| Ollama / LM Studio | local model serving | MIT / proprietary-freeware |
| SearXNG | counter-search backend | AGPL-3.0 |

Verivann **never bundles** any of these, and **never fetches media from a platform
that protects its stream** (see `verivann/mediapolicy.py`). Reading a video's
published caption track is not media download and touches no technological
protection measure.
