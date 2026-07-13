"""Verivann — raw web material -> structured, routed notes.

A local intake router: link/text in, structured Markdown note + JSON event out.
It does not store for its own sake; it decides what a source deserves to become
(note / task / drop) and proposes it. It never commits memory — that is the
private layer's job.
"""

__version__ = "0.1.0"
