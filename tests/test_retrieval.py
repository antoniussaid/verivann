import httpx

from verivann.accept import accept
from verivann.config import Config, EmbedConfig
from verivann.digest import anki, digest
from verivann.embed import cosine, enabled, pack, unpack
from verivann.library import record_feedback
from verivann.pipeline import run
from verivann.retrieval import retrieve
from verivann.trace import trace


class _Embed:
    """A toy embedder: one dimension per keyword. Enough to prove the plumbing."""

    VOCAB = ["agent", "broker", "sovereignty", "local", "cost"]

    def __init__(self):
        self.calls = 0

    def __call__(self, url, headers=None, json=None, timeout=None):
        self.calls += 1
        inputs = json["input"]
        return _Resp({"data": [{"embedding": self._vec(t)} for t in inputs]})

    def _vec(self, text):
        low = text.lower()
        return [1.0 if word in low else 0.0 for word in self.VOCAB]


class _Resp:
    def __init__(self, payload):
        self._p = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self._p


def _embedding_config(tmp_path):
    return Config(
        staging_dir=tmp_path,
        embed=EmbedConfig(model="toy", base_url="http://localhost:11434/v1"),
    )


def test_vectors_survive_a_round_trip():
    vector = [0.5, -0.25, 1.0]
    assert unpack(pack(vector)) == vector
    assert cosine([1, 0], [1, 0]) == 1.0
    assert cosine([1, 0], [0, 1]) == 0.0


def test_search_stays_keyword_only_without_an_embedder(tmp_path):
    config = Config(staging_dir=tmp_path)
    assert enabled(config) is False
    run("text", ref="text", text="a piece about brokers and cost", config=config)
    assert retrieve("broker", config).engine == "fts"


def test_meaning_search_finds_what_the_words_missed(monkeypatch, tmp_path):
    monkeypatch.setattr(httpx, "post", _Embed())
    config = _embedding_config(tmp_path)

    run("text", ref="text", text="Owning your own infrastructure: local agent sovereignty.", config=config)
    run("text", ref="text", text="Completely unrelated piece about cooking pasta.", config=config)

    found = retrieve("sovereignty local agent", config)
    assert found.engine == "hybrid"
    assert "sovereignty" in found.hits[0].text.lower()


def test_tracing_finds_the_note_a_thought_came_from(tmp_path):
    config = Config(staging_dir=tmp_path)
    run("text", ref="text",
        text="Nobody decides what a source deserves to become. Archivers capture, they do not judge.",
        config=config)
    run("text", ref="text", text="A recipe for sourdough bread with a long fermentation.", config=config)

    origins = trace("The interesting part is that nobody decides what a source deserves.", config)
    assert origins
    assert "source deserves" in origins[0].note.text


def test_accepting_writes_a_decision_not_a_proposal(tmp_path):
    config = Config(staging_dir=tmp_path)
    result = run("text", ref="text", text="an automation pipeline worth keeping", config=config)

    vault = tmp_path / "vault"
    accepted = accept(result.event.id, vault, config)

    assert accepted is not None
    text = accepted.target.read_text(encoding="utf-8")
    assert "proposed_action:" not in text
    assert "action: " in text
    assert "accepted_by: human" in text
    assert "accepted by you on" in text

    from verivann.library import verdict_of

    assert verdict_of(result.event.id, tmp_path) == "kept"  # accepting IS keeping


def test_accepting_an_unknown_note_is_reported_not_guessed(tmp_path):
    assert accept("nope", tmp_path / "vault", Config(staging_dir=tmp_path)) is None


def test_the_digest_leads_with_what_survived(tmp_path):
    config = Config(staging_dir=tmp_path)
    kept = run("text", ref="text", text="local-first agent architecture notes", config=config)
    run("text", ref="text", text="crypto hype nonsense", config=config)
    record_feedback(kept.event.id, "kept", tmp_path)

    text = digest(config, days=7)
    assert "## What survived" in text
    assert "local-first agent architecture" in text
    assert "## The number" in text


def test_the_digest_says_so_when_nothing_survived(tmp_path):
    config = Config(staging_dir=tmp_path)
    run("text", ref="text", text="some material", config=config)
    assert "You kept nothing this week." in digest(config)


def test_anki_cards_come_only_from_kept_notes(tmp_path):
    config = Config(staging_dir=tmp_path)
    result = run("text", ref="text", text="an automation pipeline for agents", config=config)

    assert anki(config).strip().endswith("#tags column:3")  # nothing kept -> no cards

    note = tmp_path / "notes" / next(p.name for p in (tmp_path / "notes").glob("*.md"))
    note.write_text(
        note.read_text(encoding="utf-8").replace("- _(add on review)_", "- Orchestrate, do not rebuild."),
        encoding="utf-8",
    )
    record_feedback(result.event.id, "kept", tmp_path)

    cards = anki(config)
    assert "Orchestrate, do not rebuild." in cards
