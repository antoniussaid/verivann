import httpx

from verivann.claims import check_contradictions
from verivann.config import Config, LLMConfig
from verivann.library import all_claims, index_claims


class _FakeResp:
    def __init__(self, payload):
        self._p = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self._p


def _openai(content):
    return _FakeResp({"choices": [{"message": {"content": content}}]})


def test_claims_recorded_and_listed(tmp_path):
    index_claims("note-1", ["Ollama runs fully offline.", "Whisper needs a GPU."], tmp_path)
    rows = all_claims(tmp_path)
    assert len(rows) == 2
    assert any("Ollama" in claim for claim, _ in rows)


def test_contradiction_is_flagged(monkeypatch, tmp_path):
    index_claims("note-1", ["Whisper needs a GPU."], tmp_path)
    monkeypatch.setattr(
        httpx,
        "post",
        lambda *a, **k: _openai(
            '{"conflict": true, "with": "Whisper needs a GPU.", '
            '"why": "One requires a GPU, the other says CPU suffices."}'
        ),
    )
    cfg = Config(staging_dir=tmp_path, llm=LLMConfig(provider="openai", model="m", base_url="http://x/v1"))
    out = check_contradictions(["Whisper runs fine on CPU."], cfg, tmp_path, exclude_note="note-2")
    assert out and out[0]["conflicts_with"].startswith("Whisper needs")


def test_no_llm_means_no_ledger_checks(tmp_path):
    index_claims("note-1", ["Whisper needs a GPU."], tmp_path)
    cfg = Config(staging_dir=tmp_path)  # no LLM configured
    assert check_contradictions(["Whisper runs fine on CPU."], cfg, tmp_path) == []
