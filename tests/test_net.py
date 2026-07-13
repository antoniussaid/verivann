"""The SSRF guard: the server must never be tricked into fetching inward."""

import httpx
import pytest

from verivann.net import BlockedURLError, check_url, safe_get


def test_internal_addresses_are_refused():
    assert check_url("http://127.0.0.1/") is not None           # loopback
    assert check_url("http://169.254.169.254/latest/") is not None  # cloud metadata
    assert check_url("http://10.0.0.1/") is not None            # private
    assert check_url("http://192.168.1.1/") is not None         # private
    assert check_url("http://172.16.0.1/") is not None          # private
    assert check_url("http://[::1]/") is not None               # ipv6 loopback
    assert check_url("http://0.0.0.0/") is not None             # unspecified


def test_public_addresses_pass():
    assert check_url("http://1.1.1.1/") is None
    assert check_url("https://93.184.216.34/") is None


def test_non_http_schemes_are_refused():
    assert check_url("file:///etc/passwd") is not None
    assert check_url("ftp://host/") is not None
    assert check_url("gopher://host/") is not None
    assert check_url("http://") is not None  # no host


def test_a_hostname_that_resolves_inward_is_refused(monkeypatch):
    # A public-looking name that DNS points at a private IP must be blocked.
    monkeypatch.setattr(
        "verivann.net.socket.getaddrinfo",
        lambda host, *a, **k: [(2, 1, 6, "", ("10.1.2.3", 0))],
    )
    assert "10.1.2.3" in (check_url("http://inside.example.com/") or "")


def test_safe_get_refuses_an_internal_target():
    with pytest.raises(BlockedURLError):
        safe_get("http://169.254.169.254/latest/meta-data/")


def test_safe_get_follows_a_redirect_but_blocks_an_inward_hop(monkeypatch):
    """A public URL that 302s to 127.0.0.1 must not slip through."""
    def fake_get(url, headers=None, timeout=None, follow_redirects=None):
        req = httpx.Request("GET", url)
        if "1.1.1.1" in url:  # first hop: public, redirects inward
            return httpx.Response(302, headers={"location": "http://127.0.0.1/secret"}, request=req)
        return httpx.Response(200, text="should never get here", request=req)

    monkeypatch.setattr(httpx, "get", fake_get)
    with pytest.raises(BlockedURLError):
        safe_get("http://1.1.1.1/")


def test_safe_get_returns_a_normal_response(monkeypatch):
    def fake_get(url, headers=None, timeout=None, follow_redirects=None):
        return httpx.Response(200, text="hello", request=httpx.Request("GET", url))

    monkeypatch.setattr(httpx, "get", fake_get)
    resp = safe_get("http://1.1.1.1/")
    assert resp.status_code == 200 and resp.text == "hello"


def test_the_pipeline_refuses_an_internal_url_without_fetching(monkeypatch, tmp_path):
    from verivann.config import Config
    from verivann.pipeline import run

    def explode(url):
        raise AssertionError("the pipeline fetched an internal URL")

    monkeypatch.setattr("verivann.pipeline.extract_webpage", explode)
    result = run("url", ref="http://169.254.169.254/latest/", config=Config(staging_dir=tmp_path))

    meta = result.event.extracted.meta
    assert meta.get("blocked")
    assert "Refused to fetch" in result.event.extracted.text
