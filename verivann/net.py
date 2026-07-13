"""The one door to the outside — and the guard on it.

Verivann fetches URLs a user pasted, a page linked to, or a feed listed. Without a
guard, a crafted link (or a redirect chain) could point the local server at
`http://169.254.169.254/…` (cloud metadata), `http://127.0.0.1:…` (other local
services), or a private-LAN host — a Server-Side Request Forgery. The server would
dutifully fetch it and hand the result back.

So every server-side HTTP fetch goes through `safe_get`, which:
  * allows only http/https,
  * resolves the host and refuses any IP that is not globally routable — a
    default-deny check (`is_global`), not a blocklist of known-bad ranges, so
    CGNAT/shared address space (incl. some clouds' metadata) and future special
    ranges are refused too, not just loopback/private/link-local, and
  * follows redirects **manually**, re-checking every hop — because a public URL
    that 302s to `http://127.0.0.1` would otherwise slip straight through.

Residual, documented: this does not defend against DNS rebinding (a host that
resolves to a public IP for the check and a private one for the connection). For a
local single-user tool that is an acceptable gap; closing it would mean pinning the
resolved IP per connection.
"""

from __future__ import annotations

import ipaddress
import socket
from urllib.parse import urlsplit

_SAFE_SCHEMES = ("http", "https")
_MAX_REDIRECTS = 5


class BlockedURLError(Exception):
    """A URL that a server-side fetch must refuse (SSRF guard)."""


def _blocked_ip(ip: ipaddress._BaseAddress) -> str | None:
    if getattr(ip, "ipv4_mapped", None):  # ::ffff:169.254.169.254 and friends
        ip = ip.ipv4_mapped
    if ip.is_loopback:
        return "loopback"
    if ip.is_link_local:
        return "link-local (e.g. the cloud metadata endpoint)"
    if ip.is_private:
        return "a private network"
    if ip.is_reserved:
        return "a reserved range"
    if ip.is_multicast:
        return "multicast"
    if ip.is_unspecified:
        return "the unspecified address"
    # Default-DENY, not deny-by-enumeration: refuse anything that is not globally
    # routable. The named checks above stay only to give a precise reason for the
    # common cases; this line is the real guard, and it also stops the ranges the
    # enumeration missed — CGNAT/shared address space (100.64.0.0/10, which holds
    # Alibaba Cloud's metadata at 100.100.100.200), 6to4 relay (192.88.99.0/24),
    # benchmarking, and any future special-use range.
    if not getattr(ip, "is_global", False):
        return "not a globally routable address"
    return None


def _blocked_host(host: str) -> str | None:
    try:
        return _blocked_ip(ipaddress.ip_address(host))  # a literal IP
    except ValueError:
        pass
    try:
        infos = socket.getaddrinfo(host, None)
    except socket.gaierror:
        return None  # cannot resolve — let the HTTP client fail normally; not SSRF
    for info in infos:
        addr = info[4][0].split("%", 1)[0]  # strip a zone id if present
        try:
            reason = _blocked_ip(ipaddress.ip_address(addr))
        except ValueError:
            continue
        if reason:
            return f"{host} resolves to {addr} ({reason})"
    return None


def check_url(url: str) -> str | None:
    """None if the URL is safe to fetch server-side; otherwise a human reason."""
    try:
        parts = urlsplit(url)
    except ValueError:
        return "unparseable URL"
    if parts.scheme not in _SAFE_SCHEMES:
        return f"scheme '{parts.scheme}' is not allowed (only http/https)"
    host = parts.hostname
    if not host:
        return "no host in URL"
    return _blocked_host(host)


def safe_get(url: str, *, headers: dict | None = None, timeout: float = 20.0):
    """An httpx GET that validates the target and every redirect hop against SSRF.

    Raises BlockedURLError if any hop points inward. Callers already degrade on
    exceptions, so a blocked URL simply yields a graceful fallback.
    """
    import httpx

    current = url
    for _ in range(_MAX_REDIRECTS + 1):
        reason = check_url(current)
        if reason:
            raise BlockedURLError(f"refused to fetch {current}: {reason}")
        resp = httpx.get(current, headers=headers, timeout=timeout, follow_redirects=False)
        location = resp.headers.get("location")
        if resp.is_redirect and location:
            current = str(resp.url.join(location))
            continue
        return resp
    raise BlockedURLError(f"too many redirects starting at {url}")
