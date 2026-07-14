"""The setup wizard's I/O-free core - the part that must never mangle a config."""

import httpx

from verivann.config import LLMConfig
from verivann.setup import (
    PRESETS,
    compose_env,
    preset,
    verify_connection,
    welcome_text,
    write_env,
)


def test_every_preset_is_coherent():
    for p in PRESETS:
        assert p.key and p.label
        # A hosted provider needs a key; a local one does not.
        assert p.needs_key != p.local or p.key == "lmstudio"
        # Only Cloudflare carries an account id.
        assert p.needs_account == (p.key == "cloudflare")


def test_a_hosted_provider_writes_the_chat_slot():
    env = compose_env("groq", api_key="gsk_secret", model="llama-3.3-70b-versatile")
    assert env["VERIVANN_LLM"] == "groq"
    assert env["VERIVANN_LLM_MODEL"] == "llama-3.3-70b-versatile"
    assert env["VERIVANN_LLM_API_KEY"] == "gsk_secret"
    assert "VERIVANN_LOCAL_LLM" not in env  # groq is not local


def test_cloudflare_carries_the_account_id():
    env = compose_env("cloudflare", account="abc123", api_key="tok")
    assert env["VERIVANN_CF_ACCOUNT_ID"] == "abc123"
    assert env["VERIVANN_LLM_MODEL"] == preset("cloudflare").default_model
    assert env["VERIVANN_EMBED_MODEL"]  # cloudflare has an embeddings endpoint


def test_a_local_provider_fills_both_slots_and_sets_strict_privacy():
    env = compose_env("ollama", model="llama3.2:3b")
    # Main slot reads public material; local slot reads sensitive material - both are
    # the same local model, so nothing ever leaves the machine either way.
    assert env["VERIVANN_LLM"] == "ollama"
    assert env["VERIVANN_LLM_MODEL"] == "llama3.2:3b"
    assert env["VERIVANN_LOCAL_LLM"] == "ollama"
    assert env["VERIVANN_LOCAL_LLM_MODEL"] == "llama3.2:3b"
    assert env["VERIVANN_PRIVACY"] == "strict"


def test_a_hosted_provider_has_no_local_slot():
    env = compose_env("groq", api_key="k")
    # No local model → sensitive material is NOT uploaded; it stays with the heuristic.
    assert "VERIVANN_LOCAL_LLM" not in env


def test_a_provider_without_embeddings_omits_the_embed_var():
    env = compose_env("groq", api_key="k")
    assert "VERIVANN_EMBED_MODEL" not in env  # groq has no embeddings endpoint


def test_writing_a_fresh_env(tmp_path):
    path = tmp_path / ".env"
    write_env(path, {"VERIVANN_LLM": "groq", "VERIVANN_LLM_API_KEY": "k"})
    text = path.read_text(encoding="utf-8")
    assert "VERIVANN_LLM=groq" in text
    assert "written by `verivann setup`" in text


def test_merging_preserves_the_users_other_lines(tmp_path):
    path = tmp_path / ".env"
    path.write_text(
        "# my notes\nVERIVANN_STAGING=/my/notes\nVERIVANN_LLM=openai\nVERIVANN_LENS=critique\n",
        encoding="utf-8",
    )
    write_env(path, {"VERIVANN_LLM": "groq", "VERIVANN_LLM_MODEL": "llama-3.3-70b-versatile"})
    text = path.read_text(encoding="utf-8")

    assert "# my notes" in text                    # comment kept
    assert "VERIVANN_STAGING=/my/notes" in text    # unrelated line kept
    assert "VERIVANN_LENS=critique" in text         # unrelated line kept
    assert "VERIVANN_LLM=groq" in text              # existing key UPDATED in place
    assert "VERIVANN_LLM=openai" not in text        # …not duplicated
    assert text.count("VERIVANN_LLM=") == 1
    assert "VERIVANN_LLM_MODEL=llama-3.3-70b-versatile" in text  # new key appended


def test_an_unknown_provider_writes_nothing():
    assert compose_env("nonesuch") == {}


# --- Connection verification: turn a silent misconfiguration into an answer. -------

class _Resp:
    def __init__(self, content):
        self._c = content

    def raise_for_status(self):
        return None

    def json(self):
        return {"choices": [{"message": {"content": self._c}}]}


def _llm():
    return LLMConfig(provider="openai", model="m", base_url="http://x/v1", api_key="k")


def test_verify_reports_a_reachable_model(monkeypatch):
    monkeypatch.setattr(httpx, "post", lambda *a, **k: _Resp("OK"))
    probe = verify_connection(_llm())
    assert probe.ok and probe.model == "m" and "OK" in probe.detail


def test_verify_reports_an_unconfigured_model():
    probe = verify_connection(LLMConfig())  # no provider
    assert not probe.ok and "no model configured" in probe.detail


def test_verify_translates_a_rejected_key(monkeypatch):
    def unauthorized(*a, **k):
        req = httpx.Request("POST", "http://x/v1")
        raise httpx.HTTPStatusError("401", request=req, response=httpx.Response(401, request=req))

    monkeypatch.setattr(httpx, "post", unauthorized)
    probe = verify_connection(_llm())
    assert not probe.ok and "key was rejected" in probe.detail


def test_verify_translates_an_unreachable_server(monkeypatch):
    def refused(*a, **k):
        raise httpx.ConnectError("connection refused")

    monkeypatch.setattr(httpx, "post", refused)
    probe = verify_connection(_llm())
    assert not probe.ok and "could not reach" in probe.detail


def test_verify_never_raises_on_an_odd_failure(monkeypatch):
    monkeypatch.setattr(httpx, "post", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("weird")))
    probe = verify_connection(_llm())
    assert not probe.ok and probe.detail  # a reason, not a traceback


def test_welcome_text_is_real_material_for_a_first_note():
    title, text = welcome_text()
    assert "Verivann" in title
    assert len(text) > 200 and "proposal" in text  # substantial enough to actually analyze
