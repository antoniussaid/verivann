import httpx
import pytest

from smelt.config import Config, LLMConfig
from smelt.library import outbound_rows, outbound_total
from smelt.pipeline import run
from smelt.privacy import PUBLIC, SENSITIVE, classify, config_for, is_local, policy
from smelt.render import render_markdown


class _Resp:
    def raise_for_status(self):
        return None

    def json(self):
        return {"choices": [{"message": {"content": '{"domain":"research","action":"note","summary":"s"}'}}]}


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    for key in ("SMELT_PRIVACY", "SMELT_PRICE_PER_MTOK"):
        monkeypatch.delenv(key, raising=False)


def _hosted():
    return LLMConfig(provider="openai", model="gpt", base_url="https://api.openai.com/v1", api_key="k")


def _local():
    return LLMConfig(provider="ollama", model="llama", base_url="http://localhost:11434/v1")


# ---------- classification ----------

def test_anything_off_your_own_disk_is_sensitive():
    assert classify("file", "a shopping list")[0] == SENSITIVE
    assert classify("url", "a public blog post about rust")[0] == PUBLIC


def test_private_life_is_recognized_in_text():
    assert classify("text", "IBAN: AT61 1904 3002 3457 3201")[0] == SENSITIVE
    assert classify("text", "Mein Gehalt beträgt 3400 EUR brutto")[0] == SENSITIVE
    assert classify("text", "Diagnose: Bluthochdruck, Rezept beiliegend")[0] == SENSITIVE
    assert classify("text", "password: hunter2")[0] == SENSITIVE
    assert classify("text", "an article about local-first software")[0] == PUBLIC


def test_a_local_endpoint_is_recognized_as_local():
    assert is_local(_local()) is True
    assert is_local(_hosted()) is False
    assert is_local(LLMConfig()) is True  # no model -> nothing leaves at all


# ---------- routing ----------

def test_sensitive_material_never_reaches_a_hosted_model_by_default():
    config = Config(llm=_hosted())  # hosted only, strict policy (the default)
    read_config, stayed_local = config_for(config, SENSITIVE)

    assert policy() == "strict"
    assert read_config.llm.enabled is False  # nobody reads it — but nobody uploads it either
    assert stayed_local is True


def test_sensitive_material_goes_to_the_local_slot_when_there_is_one():
    config = Config(llm=_hosted(), local_llm=_local())
    read_config, stayed_local = config_for(config, SENSITIVE)

    assert read_config.llm.model == "llama"
    assert stayed_local is True


def test_public_material_may_use_the_hosted_slot():
    config = Config(llm=_hosted())
    read_config, stayed_local = config_for(config, PUBLIC)
    assert read_config.llm.model == "gpt"
    assert stayed_local is False


def test_allow_policy_is_honoured_but_recorded(monkeypatch):
    monkeypatch.setenv("SMELT_PRIVACY", "allow")
    config = Config(llm=_hosted())
    read_config, stayed_local = config_for(config, SENSITIVE)

    assert read_config.llm.model == "gpt"  # your machine, your call
    assert stayed_local is False           # …and it is on the record


def test_a_screenshot_is_not_uploaded_and_the_note_says_so(monkeypatch, tmp_path):
    monkeypatch.setattr("smelt.adapters.vision.ocr_available", lambda: True)
    monkeypatch.setattr("smelt.adapters.vision.ocr_image", lambda p: "Kontoauszug: IBAN AT61 1904 3002 3457 3201")

    def explode(*args, **kwargs):
        raise AssertionError("a hosted model was called with sensitive material")

    monkeypatch.setattr(httpx, "post", explode)

    shot = tmp_path / "shot.png"
    shot.write_bytes(b"\x89PNG")
    config = Config(staging_dir=tmp_path, llm=_hosted())

    result = run("file", ref=str(shot), config=config)  # must not raise
    note = render_markdown(result.event)

    assert result.event.extracted.meta["sensitivity"] == SENSITIVE
    assert result.event.extracted.meta["analyzed_locally"] is True
    assert "## Privacy" in note
    assert "NOT sent anywhere" in note
    assert "sensitivity: sensitive" in note


# ---------- the outbound ledger ----------

def test_every_hosted_call_is_written_to_the_ledger(monkeypatch, tmp_path):
    monkeypatch.setattr(httpx, "post", lambda *a, **k: _Resp())
    config = Config(staging_dir=tmp_path, llm=_hosted())

    run("text", ref="text", text="a public article about local-first architecture", config=config)

    rows = outbound_rows(tmp_path)
    assert rows and rows[0]["provider"] == "openai"
    assert rows[0]["purpose"] == "analysis"
    chars, cost = outbound_total(tmp_path)
    assert chars > 0
    assert cost == 0.0  # no price configured -> we do NOT invent one


def test_cost_is_estimated_only_when_you_gave_us_a_price(monkeypatch, tmp_path):
    monkeypatch.setenv("SMELT_PRICE_PER_MTOK", "3.0")
    monkeypatch.setattr(httpx, "post", lambda *a, **k: _Resp())
    config = Config(staging_dir=tmp_path, llm=_hosted())

    run("text", ref="text", text="a public article about agents " * 50, config=config)
    _, cost = outbound_total(tmp_path)
    assert cost > 0
