"""The material is German. The tool was not. That cost something, silently."""

import httpx

from verivann.analysis.analyzer import heuristic_analyze
from verivann.config import Config, LLMConfig
from verivann.language import detect, instruction, name
from verivann.pipeline import run
from verivann.schema import Extracted


def test_german_is_recognized_as_german():
    text = (
        "Der Artikel beschreibt, wie man ein lokales System aufsetzt und warum das "
        "nicht nur eine technische, sondern auch eine politische Entscheidung ist."
    )
    assert detect(text) == "de"


def test_english_stays_english():
    text = (
        "The article describes how to set up a local system, and why that is not only "
        "a technical decision but also a political one."
    )
    assert detect(text) == "en"


def test_a_close_call_goes_to_english():
    assert detect("ok") == "en"          # too short to judge
    assert detect("data api json") == "en"  # no function words at all


def test_the_instruction_only_appears_for_foreign_material():
    assert instruction("en") == ""
    assert "German" in instruction("de")
    assert "JSON keys" in instruction("de")  # …but the schema must not be translated
    assert name("de") == "German"


def test_german_material_routes_on_german_words():
    """'Kündigungsfrist' should route as surely as 'deadline'."""
    german = Extracted(
        title="Versicherung wechseln",
        text=(
            "Die Kündigungsfrist für die Versicherung läuft ab, und die Prämie steigt. "
            "Ich sollte das Angebot vergleichen und rechtzeitig kündigen, sonst zahle "
            "ich weiter zu viel für die Vorsorge."
        ),
    )
    result = heuristic_analyze(german)

    assert result.language == "de"
    assert result.domain == "finance"
    assert result.action == "task"  # "kündigen", "Kündigungsfrist" are actions


def test_the_same_text_in_english_routes_the_same_way():
    english = Extracted(
        title="Switching insurance",
        text=(
            "The deadline for the insurance is running out and the price is going up. "
            "I should compare the offers and apply in time, or I will keep paying too much."
        ),
    )
    result = heuristic_analyze(english)
    assert result.language == "en"
    assert result.domain == "finance"
    assert result.action == "task"


def test_the_model_is_told_to_answer_in_german(monkeypatch, tmp_path):
    seen = {}

    class _Resp:
        def raise_for_status(self):
            return None

        def json(self):
            return {
                "choices": [{"message": {"content":
                    '{"domain":"research","action":"note",'
                    '"summary":"Der Artikel beschreibt eine lokale Architektur."}'}}]
            }

    def capture(url, headers=None, json=None, timeout=None):
        seen["system"] = json["messages"][0]["content"]
        return _Resp()

    monkeypatch.setattr(httpx, "post", capture)
    config = Config(
        staging_dir=tmp_path, llm=LLMConfig(provider="groq", model="m", base_url="http://x/v1")
    )
    result = run(
        "text", ref="text",
        text=(
            "Der Beitrag erklärt, wie eine lokale Architektur funktioniert und warum "
            "das für die Souveränität der eigenen Daten wichtig ist."
        ),
        config=config,
    )

    assert "LANGUAGE: the material is in German" in seen["system"]
    # …and the answer comes back in German, in the note that was actually written.
    note = result.note_path.read_text(encoding="utf-8")
    assert "Der Artikel beschreibt eine lokale Architektur." in note


def test_english_material_gets_no_language_instruction(monkeypatch, tmp_path):
    seen = {}

    class _Resp:
        def raise_for_status(self):
            return None

        def json(self):
            return {"choices": [{"message": {"content": '{"domain":"research","action":"note"}'}}]}

    def capture(url, headers=None, json=None, timeout=None):
        seen["system"] = json["messages"][0]["content"]
        return _Resp()

    monkeypatch.setattr(httpx, "post", capture)
    config = Config(
        staging_dir=tmp_path, llm=LLMConfig(provider="groq", model="m", base_url="http://x/v1")
    )
    run("text", ref="text",
        text="The article explains how a local architecture works and why it matters for sovereignty.",
        config=config)

    assert "LANGUAGE:" not in seen["system"]
