"""The inbox is a Python string that contains a JavaScript program.

That is a trap, and it sprang: a `\\n` written for the browser was eaten by Python,
which split a JS string literal across two lines. The result was a SyntaxError that
killed the *entire* script - so not one button on the page worked, and nothing said
so. The page rendered perfectly and did nothing.

So the script is now actually parsed, by an actual JavaScript engine, in CI. If
Node is not installed the check skips rather than pretending: a syntax test that
cannot parse is not a test.
"""

from __future__ import annotations

import re
import shutil
import subprocess

import pytest

from verivann.web import PAGE, SERVICE_WORKER, cors_origin, is_authorized

_SCRIPT = re.search(r"<script>(.*?)</script>", PAGE, re.DOTALL).group(1)


# ---------- the CSRF/CORS defense ----------

_TOKEN = "s3cret-token"


def test_a_website_cannot_reach_the_api_without_the_token():
    """The core threat: any site the user visits could fetch() the local API."""
    # evil.com, no token → rejected.
    assert is_authorized("https://evil.example.com", "", _TOKEN) is False
    # evil.com guessing a wrong token → rejected.
    assert is_authorized("https://evil.example.com", "wrong", _TOKEN) is False
    # the inbox page itself is same-origin and carries the token → allowed.
    assert is_authorized("http://127.0.0.1:8130", _TOKEN, _TOKEN) is True


def test_a_browser_extension_origin_is_trusted_without_a_token():
    """A web page cannot forge a chrome-extension:// origin - the browser sets it."""
    assert is_authorized("chrome-extension://abcdefg", "", _TOKEN) is True
    assert is_authorized("moz-extension://abcdefg", "", _TOKEN) is True
    assert is_authorized("safari-web-extension://x", "", _TOKEN) is True


def test_cors_never_reflects_a_website_origin():
    assert cors_origin("https://evil.example.com") is None
    assert cors_origin("http://127.0.0.1:8130") is None  # not even our own page
    assert cors_origin("chrome-extension://abcdefg") == "chrome-extension://abcdefg"
    assert cors_origin("") is None


def test_the_page_never_ships_a_wildcard_cors_header():
    # a regression guard: the old code sent access-control-allow-origin: *
    assert "access-control-allow-origin\", \"*\"" not in PAGE  # not in the page (belt)


def test_a_correct_token_authorizes_any_client():
    assert is_authorized("", _TOKEN, _TOKEN) is True           # curl / CLI, no origin
    assert is_authorized("https://example.com", _TOKEN, _TOKEN) is True  # token beats origin


def _check_js(source: str, tmp_path, name: str) -> None:
    node = shutil.which("node")
    if node is None:
        pytest.skip("node not installed - cannot parse the page's JavaScript")
    path = tmp_path / name
    path.write_text(source, encoding="utf-8")
    proc = subprocess.run([node, "--check", str(path)], capture_output=True, text=True, timeout=30)
    assert proc.returncode == 0, f"the page's JavaScript does not parse:\n{proc.stderr}"


def test_the_page_script_actually_parses(tmp_path):
    """The one test that would have caught a dead GUI before the user did."""
    _check_js(_SCRIPT, tmp_path, "page.js")


def test_the_service_worker_parses(tmp_path):
    _check_js(SERVICE_WORKER, tmp_path, "sw.js")


def test_the_lens_placeholder_was_substituted():
    assert "__LENS_OPTIONS__" not in PAGE
    assert '<option value="digest"' in PAGE


def test_every_element_the_script_reaches_for_exists_in_the_markup():
    referenced = set(re.findall(r"\$\('([\w-]+)'\)", _SCRIPT))
    runtime = {"keep", "drop"}  # created by the digest panel at runtime
    markup_ids = set(re.findall(r'id="([\w-]+)"', PAGE))
    missing = referenced - markup_ids - runtime
    assert not missing, f"the script addresses elements that do not exist: {missing}"


def test_every_endpoint_the_page_calls_is_actually_routed():
    called = set(re.findall(r"post\('(/[\w-]+)'", _SCRIPT))
    routed = {"/intake", "/search", "/ask", "/feedback", "/mirror", "/question", "/note", "/highlight"}
    assert called <= routed, f"the page calls endpoints that do not exist: {called - routed}"


def test_the_three_panels_and_their_tabs_agree():
    tabs = set(re.findall(r'data-panel="(\w+)"', PAGE))
    panels = set(re.findall(r'id="p-(\w+)"', PAGE))
    assert tabs == panels == {"digest", "library", "mirror"}
