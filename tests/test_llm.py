import httpx

from smelt.analysis.analyzer import analyze
from smelt.config import Config, LLMConfig
from smelt.schema import Extracted


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
