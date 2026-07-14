"""Generic, runtime-populated domain registry.

The public core ships only neutral placeholder domains. The real the private domains
are injected at runtime from a private config the private layer owns - they are
never committed, and never appear in example outputs.
"""

from __future__ import annotations

# Neutral placeholders for the public demo. NOT the real private structure organs.
DEFAULT_PUBLIC_DOMAINS: list[str] = ["finance", "media", "research", "tasks", "inbox"]

# Where unknown / low-confidence routing lands.
FALLBACK_DOMAIN = "inbox"


class DomainRegistry:
    def __init__(self, domains: list[str] | None = None) -> None:
        self.domains = list(domains) if domains else list(DEFAULT_PUBLIC_DOMAINS)
        if FALLBACK_DOMAIN not in self.domains:
            self.domains.append(FALLBACK_DOMAIN)

    def has(self, key: str) -> bool:
        return key in self.domains

    def resolve(self, key: str | None) -> str:
        """Map a proposed key onto a known domain, or the fallback."""
        return key if (key and self.has(key)) else FALLBACK_DOMAIN
