"""The intake event schema - the shared contract with the private layer.

This mirrors, field for field, the JSON event agreed in CONTRACT.md. The public
core builds exactly this; the private layer consumes it. `routing.domain`
always references the domain registry (a key), never a hardcoded real value.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

# "file" is additive: a screenshot, a voice memo, a PDF from the user's own disk.
# Consumers switch on `kind`; an unknown kind must be treated as opaque material,
# never as a reason to reject the event.
SourceKind = Literal["url", "text", "youtube", "file"]
# NOTE: "memory" is a valid *proposal* in the contract, but the public heuristic
# never proposes it on its own - memory stays entirely with the private layer.
Action = Literal["note", "task", "memory", "drop"]


class Source(BaseModel):
    kind: SourceKind
    ref: str


class Extracted(BaseModel):
    title: str = ""
    text: str = ""
    meta: dict[str, Any] = Field(default_factory=dict)


class Routing(BaseModel):
    domain: str  # references the registry; public = placeholder, real = private/runtime
    confidence: float = 0.0
    reason: str = ""


class Decision(BaseModel):
    action: Action  # PROPOSAL only - the core never commits anything
    target: str  # staging path where the artifacts were written


class Provenance(BaseModel):
    tool: str = "verivann"
    version: str
    public_demo: bool = True
    # Intake material is always unverified foreign content - the extracted text
    # must be treated as DATA, never executed as instructions. The core never
    # sets this to anything but "unverified"; downstream must quarantine.
    content_trust: str = "unverified"


class IntakeEvent(BaseModel):
    id: str
    created_at: str
    source: Source
    extracted: Extracted
    routing: Routing
    decision: Decision
    provenance: Provenance
