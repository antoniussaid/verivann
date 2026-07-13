"""The part that runs while you are not looking.

Three of the best things this tool does are, in practice, dead features: `feed run`,
`watch run` and `refresh` all require a human to remember to type them. A personal
editor you have to wake up every morning is not an editor.

    verivann daemon              run the schedule, forever (Ctrl+C to stop)
    verivann daemon --once       do one pass and exit — this is what a cron/Task
                              Scheduler entry should call
    verivann daemon --install    print the exact command for your OS's scheduler

What it does, on a schedule you can change:

    feeds     every 60 min   read the feeds, surface only what passes your filter
    watch     every 6 h      re-read watched sources; anything that moved gets a diff
    refresh   every 6 h      update the "since you read this" banners on old notes
    sweep     daily          record the quiet verdict on notes ignored for 30+ days

Two rules it never breaks:

* **It never asks anything.** `VERIVANN_MEDIA=ask` resolves to *no* in a background run,
  because nobody is there to answer, and silence is not consent (mediapolicy.py).
* **It never commits anything.** Everything it does is a proposal, exactly as if you
  had typed the command yourself. It cannot accept a note; only you can.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from datetime import datetime, timezone

from .config import Config

_MINUTE = 60


@dataclass
class Job:
    name: str
    every_seconds: int
    run: object  # callable(config) -> str  (a one-line summary of what happened)


@dataclass
class Pass:
    at: str
    done: dict[str, str] = field(default_factory=dict)
    failed: dict[str, str] = field(default_factory=dict)


def _feeds(config: Config) -> str:
    from .feeds import run as run_feeds

    results = run_feeds(config)
    seen = sum(r.seen for r in results)
    passed = sum(len(r.passed) for r in results)
    if not seen:
        return "nothing new"
    trained = results[0].trained if results else False
    basis = "your filter" if trained else "no filter yet (untrained)"
    return f"{seen} item(s) read, {passed} got through — {basis}"


def _watch(config: Config) -> str:
    from .watchlist import run as run_watch

    moved = run_watch(config)
    if not moved:
        return "nothing moved"
    return f"{len(moved)} source(s) changed after you read them"


def _refresh(config: Config) -> str:
    from .refresh import refresh

    changed = refresh(config)
    return f"{len(changed)} note(s) updated" if changed else "nothing to update"


def _sweep(config: Config) -> str:
    from .signals import sweep

    count = sweep(config.staging_dir)
    return f"{count} note(s) judged by your silence" if count else "nothing ignored long enough"


def schedule() -> list[Job]:
    return [
        Job("feeds", 60 * _MINUTE, _feeds),
        Job("watch", 6 * 60 * _MINUTE, _watch),
        Job("refresh", 6 * 60 * _MINUTE, _refresh),
        Job("sweep", 24 * 60 * _MINUTE, _sweep),
    ]


def due(config: Config, now: float | None = None) -> list[Job]:
    """Which jobs are due — persisted, so `--once` from cron behaves like a daemon."""
    from .library import get_state

    now = now if now is not None else time.time()
    out: list[Job] = []
    for job in schedule():
        last = get_state(f"daemon.{job.name}", config.staging_dir, "0")
        try:
            when = float(last)
        except ValueError:
            when = 0.0
        if now - when >= job.every_seconds:
            out.append(job)
    return out


def run_once(config: Config | None = None, force: bool = False, on_job=None) -> Pass:
    """One pass over everything that is due. This is what a cron entry calls."""
    config = config or Config.load()
    from .library import log_event, set_state

    result = Pass(at=datetime.now(timezone.utc).isoformat())
    jobs = schedule() if force else due(config)
    for job in jobs:
        try:
            summary = job.run(config)
            result.done[job.name] = summary
        except Exception as exc:  # noqa: BLE001 - one broken job must not stop the schedule
            result.failed[job.name] = str(exc)[:120]
            summary = f"failed: {exc}"
        set_state(f"daemon.{job.name}", str(time.time()), config.staging_dir)
        if on_job:
            on_job(job.name, summary)
    if jobs:
        log_event(
            "daemon", "", f"{len(result.done)} job(s) ran, {len(result.failed)} failed",
            config.staging_dir,
        )
    return result


def serve(config: Config | None = None, interval: int = 5 * _MINUTE, on_job=None) -> None:
    """Stay up and keep the schedule. Deliberately dumb: no threads, no queue, no state
    beyond a timestamp per job in the database."""
    config = config or Config.load()
    while True:
        run_once(config, on_job=on_job)
        time.sleep(interval)


def install_hint(python: str, staging: str) -> str:
    """The exact line to paste into the OS scheduler. We do not install it ourselves —
    writing to a user's task scheduler behind their back is not our business."""
    return f"""
  Windows (Task Scheduler) — every 30 minutes:

    schtasks /create /tn "Verivann" /sc minute /mo 30 ^
      /tr "{python} -m verivann.cli daemon --once"

  macOS / Linux (cron) — every 30 minutes:

    */30 * * * *  cd {staging} && {python} -m verivann.cli daemon --once

  Or just leave it running in a terminal:

    verivann daemon
"""
