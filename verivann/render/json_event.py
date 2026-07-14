"""Machine-readable JSON event - the exact contract shape."""

from __future__ import annotations

from ..schema import IntakeEvent


def render_json(event: IntakeEvent) -> str:
    return event.model_dump_json(indent=2)
