"""Raw archive - a faithful offline snapshot of a page, via external tools.

Opt-in (`VERIVANN_ARCHIVE` truthy). A note is an interpretation; the archive is the
evidence. Three formats, each from a tool that is *invoked*, never imported:

  html  monolith (GPL-2.0) or single-file (AGPL) -> one self-contained file
  pdf   headless Chrome/Edge (--print-to-pdf)    -> a printable record
  png   headless Chrome/Edge (--screenshot)      -> what the page looked like

Because these are separate programs, their copyleft licenses do not reach Verivann's
own license: the user installs them, Verivann orchestrates them.

Which formats are produced is `VERIVANN_ARCHIVE_FORMATS` (default "html"), e.g.
"html,pdf,png". Missing tools are skipped silently - archiving never fails an
intake.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

_DEFAULT_FORMATS = "html"

# Where a headless browser usually lives on Windows/macOS/Linux. VERIVANN_CHROME wins.
_CHROME_CANDIDATES = (
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
)
_CHROME_ON_PATH = ("chrome", "google-chrome", "chromium", "chromium-browser", "msedge")


def enabled() -> bool:
    return os.environ.get("VERIVANN_ARCHIVE", "").strip().lower() in ("1", "true", "yes", "on")


def formats() -> list[str]:
    raw = os.environ.get("VERIVANN_ARCHIVE_FORMATS", _DEFAULT_FORMATS)
    wanted = [f.strip().lower() for f in raw.split(",") if f.strip()]
    return [f for f in wanted if f in ("html", "pdf", "png")] or ["html"]


def available_tool() -> str | None:
    """The HTML snapshot tool, if the user installed one."""
    for tool in ("monolith", "single-file"):
        if shutil.which(tool):
            return tool
    return None


def chrome_binary() -> str | None:
    """A headless-capable browser for pdf/png - already on nearly every machine."""
    explicit = os.environ.get("VERIVANN_CHROME", "").strip()
    if explicit:
        return explicit if Path(explicit).is_file() else None
    for name in _CHROME_ON_PATH:
        found = shutil.which(name)
        if found:
            return found
    for path in _CHROME_CANDIDATES:
        if Path(path).is_file():
            return path
    return None


def archive_url(url: str, dest_dir: Path, stem: str) -> Path | None:
    """The self-contained HTML snapshot (the original, still the default format)."""
    if not enabled():
        return None
    tool = available_tool()
    if tool is None:
        return None
    try:
        dest_dir.mkdir(parents=True, exist_ok=True)
    except OSError:
        return None
    out = dest_dir / f"{stem}.html"
    # `--` ends options so a hostile "URL" cannot be read as a flag (the URL is also
    # already validated by archive_all's check_url guard).
    cmd = (
        ["monolith", "-o", str(out), "--", url]
        if tool == "monolith"
        else ["single-file", "--", url, str(out)]
    )
    return _run(cmd, out, timeout=180)


def archive_all(url: str, dest_dir: Path, stem: str) -> dict[str, str]:
    """Every requested format that a tool is actually available for: {format: path}."""
    if not enabled():
        return {}
    from ..net import check_url  # never let the archiver reach an internal address

    if check_url(url):
        return {}
    wanted = formats()
    made: dict[str, str] = {}

    if "html" in wanted:
        snapshot = archive_url(url, dest_dir, stem)
        if snapshot:
            made["html"] = str(snapshot)

    if not ({"pdf", "png"} & set(wanted)):
        return made
    browser = chrome_binary()
    if browser is None:
        return made
    try:
        dest_dir.mkdir(parents=True, exist_ok=True)
    except OSError:
        return made
    # Headless Chrome resolves output paths against its own working directory,
    # not ours - always hand it an absolute one.
    dest = dest_dir.resolve()

    if "pdf" in wanted:
        out = dest / f"{stem}.pdf"
        if _run(_chrome_cmd(browser, url, f"--print-to-pdf={out}"), out):
            made["pdf"] = str(out)
    if "png" in wanted:
        out = dest / f"{stem}.png"
        if _run(_chrome_cmd(browser, url, f"--screenshot={out}", "--window-size=1280,2400"), out):
            made["png"] = str(out)
    return made


def _chrome_cmd(browser: str, url: str, *extra: str) -> list[str]:
    return [
        browser, "--headless=new", "--disable-gpu", "--no-sandbox",
        "--hide-scrollbars", "--virtual-time-budget=8000", *extra, url,
    ]


def _run(cmd: list[str], out: Path, timeout: int = 120) -> Path | None:
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    except Exception:  # noqa: BLE001 - archiving is best-effort, never fatal
        return None
    if proc.returncode == 0 and out.is_file() and out.stat().st_size > 0:
        return out
    return None
