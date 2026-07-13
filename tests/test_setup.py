"""The setup wizard's I/O-free core — the part that must never mangle a config."""

from verivann.setup import PRESETS, compose_env, preset, write_env


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
    # Main slot reads public material; local slot reads sensitive material — both are
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
