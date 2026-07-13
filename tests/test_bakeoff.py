"""A benchmark tells you which model is better at someone else's questions."""

import httpx

from verivann.bakeoff import MIN_JUDGED, results, run
from verivann.config import Config, LLMConfig
from verivann.library import record_feedback
from verivann.pipeline import run as digest


class _Resp:
    def __init__(self, content):
        self._c = content

    def raise_for_status(self):
        return None

    def json(self):
        return {"choices": [{"message": {"content": self._c}}]}


def _by_model(answers: dict[str, str]):
    def post(url, headers=None, json=None, timeout=None):
        return _Resp(answers[json["model"]])

    return post


def _library(tmp_path, n=10) -> Config:
    config = Config(staging_dir=tmp_path)
    for i in range(n):
        digest("text", ref="text", text=f"an automation pipeline for local agents, piece {i}", config=config)
    return config


def test_two_models_read_the_same_material(monkeypatch, tmp_path):
    config = _library(tmp_path, n=4)
    monkeypatch.setattr(
        httpx, "post",
        _by_model({
            "careful": '{"domain":"research","action":"note","confidence":0.8}',
            "trigger-happy": '{"domain":"research","action":"task","confidence":0.9}',
        }),
    )
    config.llm = LLMConfig(provider="groq", model="careful", base_url="http://x/v1")

    read = run(["careful", "trigger-happy"], config, limit=10)
    assert read == 4

    standings = results(config)
    assert {c.model for c in standings.contenders} == {"careful", "trigger-happy"}
    assert all(c.read == 4 for c in standings.contenders)
    assert standings.notes == 4


def test_a_winner_is_not_crowned_on_thin_evidence(monkeypatch, tmp_path):
    config = _library(tmp_path, n=3)
    monkeypatch.setattr(
        httpx, "post",
        _by_model({"a": '{"domain":"research","action":"note"}', "b": '{"domain":"research","action":"drop"}'}),
    )
    config.llm = LLMConfig(provider="groq", model="a", base_url="http://x/v1")
    run(["a", "b"], config)

    from verivann.library import recent

    for hit in recent(tmp_path, limit=3):
        record_feedback(hit.id, "kept", tmp_path)

    standings = results(config)
    assert standings.ready is False
    assert "Not decided" in standings.verdict()
    assert f"{MIN_JUDGED} are needed" in standings.verdict()


def test_your_verdicts_decide_the_winner(monkeypatch, tmp_path):
    config = _library(tmp_path, n=MIN_JUDGED)
    monkeypatch.setattr(
        httpx, "post",
        _by_model({
            "good": '{"domain":"research","action":"note"}',   # proposes keeping
            "bad": '{"domain":"research","action":"drop"}',    # proposes dropping
        }),
    )
    config.llm = LLMConfig(provider="groq", model="good", base_url="http://x/v1")
    run(["good", "bad"], config, limit=MIN_JUDGED)

    from verivann.library import recent

    for hit in recent(tmp_path, limit=MIN_JUDGED):
        record_feedback(hit.id, "kept", tmp_path)  # you kept everything

    standings = results(config)
    assert standings.ready
    by_model = {c.model: c.accuracy for c in standings.contenders}
    assert by_model["good"] == 1.0   # it proposed keeping; you kept
    assert by_model["bad"] == 0.0    # it proposed dropping; you did not
    assert "**good** agreed with you 100%" in standings.verdict()


def test_a_tie_is_reported_as_a_tie(monkeypatch, tmp_path):
    config = _library(tmp_path, n=MIN_JUDGED)
    monkeypatch.setattr(
        httpx, "post",
        _by_model({
            "cheap": '{"domain":"research","action":"note"}',
            "expensive": '{"domain":"research","action":"task"}',  # both mean "keep"
        }),
    )
    config.llm = LLMConfig(provider="groq", model="cheap", base_url="http://x/v1")
    run(["cheap", "expensive"], config, limit=MIN_JUDGED)

    from verivann.library import recent

    for hit in recent(tmp_path, limit=MIN_JUDGED):
        record_feedback(hit.id, "kept", tmp_path)

    verdict = results(config).verdict()
    assert "A tie" in verdict
    assert "the more expensive one is not buying you anything" in verdict


def test_one_model_is_not_a_competition(tmp_path):
    config = Config(staging_dir=tmp_path)
    assert run(["only-one"], config) == 0
    assert "nothing to compare" in results(config).verdict()
