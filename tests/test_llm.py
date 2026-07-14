import httpx

from verivann.analysis.analyzer import analyze
from verivann.config import Config, LLMConfig
from verivann.schema import Extracted


class _FakeResp:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload


def _openai(content):
    return _FakeResp({"choices": [{"message": {"content": content}}]})


def test_llm_fills_the_content_sections(monkeypatch):
    canned = (
        '{"domain":"research","confidence":0.9,"reason":"About AI systems.",'
        '"action":"note","summary":"A tool that wraps GUIs as CLIs.",'
        '"useful_ideas":["7-phase pipeline"],"claims_to_verify":["deterministic JSON"],'
        '"possible_actions":["try it"]}'
    )
    monkeypatch.setattr(httpx, "post", lambda *a, **k: _openai(canned))
    cfg = Config(llm=LLMConfig(provider="openai", model="test-model", base_url="http://x/v1", api_key="k"))
    result = analyze(Extracted(title="CLI-Anything", text="maps GUI actions to code"), cfg)
    assert result.engine == "llm:test-model"
    assert result.domain == "research"
    assert result.summary.startswith("A tool")
    assert result.useful_ideas == ["7-phase pipeline"]


def test_llm_never_proposes_memory(monkeypatch):
    monkeypatch.setattr(httpx, "post", lambda *a, **k: _openai('{"domain":"research","action":"memory","summary":"x"}'))
    cfg = Config(llm=LLMConfig(provider="openai", model="m", base_url="http://x/v1"))
    result = analyze(Extracted(title="t", text="content about ai systems here"), cfg)
    assert result.action != "memory"


def test_llm_failure_falls_back_to_heuristic(monkeypatch):
    def boom(*a, **k):
        raise httpx.ConnectError("no server")

    monkeypatch.setattr(httpx, "post", boom)
    cfg = Config(llm=LLMConfig(provider="ollama", model="llama3.2:3b", base_url="http://localhost:11434/v1"))
    result = analyze(Extracted(title="AI", text="local-first self-hosted automation llm memory"), cfg)
    assert result.engine == "heuristic"
    assert "heuristic fallback" in result.reason


def test_no_llm_configured_uses_heuristic():
    result = analyze(Extracted(title="AI", text="local-first self-hosted automation llm memory"))
    assert result.engine == "heuristic"
    assert result.domain == "research"


# --- Robust JSON parsing: models rarely hand back pristine JSON. -------------------

from verivann.analysis.llm import _parse_json  # noqa: E402


def test_parse_clean_json():
    assert _parse_json('{"domain":"research","action":"note"}')["domain"] == "research"


def test_parse_strips_code_fences():
    raw = '```json\n{"domain":"health","action":"task"}\n```'
    assert _parse_json(raw)["domain"] == "health"


def test_parse_ignores_surrounding_prose():
    raw = 'Sure! Here is the analysis you asked for:\n{"domain":"finance","action":"note"}\nHope that helps.'
    assert _parse_json(raw)["domain"] == "finance"


def test_parse_tolerates_a_trailing_comma():
    assert _parse_json('{"domain":"research","action":"note",}')["action"] == "note"


def test_parse_tolerates_trailing_comma_with_json_null():
    # json.loads fails (comma) and ast.literal_eval fails (null) - the repair pass wins.
    data = _parse_json('{"domain":"research","summary":null,"action":"note",}')
    assert data["action"] == "note" and data["summary"] is None


def test_parse_tolerates_python_literals_and_single_quotes():
    raw = "{'domain': 'research', 'action': 'note', 'ok': True, 'x': None}"
    data = _parse_json(raw)
    assert data["domain"] == "research" and data["ok"] is True and data["x"] is None


def test_parse_picks_the_answer_after_a_reasoning_object():
    raw = '{"thinking":"the source seems technical"}\n\n{"domain":"research","action":"note","summary":"ok"}'
    data = _parse_json(raw)
    assert data["summary"] == "ok" and data["domain"] == "research"


def test_parse_unwraps_a_single_object_array():
    assert _parse_json('[{"domain":"research","action":"note"}]')["domain"] == "research"


def test_parse_is_not_fooled_by_braces_inside_strings():
    raw = '{"domain":"research","summary":"use {curly} braces { unbalanced","action":"note"}'
    assert _parse_json(raw)["action"] == "note"


def test_parse_raises_on_unrecoverable_reply():
    import pytest

    with pytest.raises(ValueError):
        _parse_json("I cannot help with that request.")


def test_a_messy_but_valid_reply_still_beats_the_heuristic(monkeypatch):
    """The whole point: a fenced reply with a trailing comma must NOT fall to heuristic."""
    messy = '```json\n{"domain":"research","action":"note","summary":"A real summary.",}\n```'
    monkeypatch.setattr(httpx, "post", lambda *a, **k: _openai(messy))
    cfg = Config(llm=LLMConfig(provider="openai", model="m", base_url="http://x/v1"))
    result = analyze(Extracted(title="t", text="a piece about ai systems and tooling"), cfg)
    assert result.engine == "llm:m"  # recovered, not degraded
    assert result.summary == "A real summary."
