"""The `verivann setup` wizard end to end: choose a provider, verify, first note.

Covers the interactive glue that the pure-function tests in test_setup.py cannot:
the env is written, made live, the connection is probed, and a first note lands.
"""

import os
from pathlib import Path

import httpx
from typer.testing import CliRunner

from verivann.cli import app


class _Resp:
    def raise_for_status(self):
        return None

    def json(self):
        return {"choices": [{"message": {"content": '{"domain":"research","action":"note","summary":"ok"}'}}]}


def test_setup_writes_env_verifies_and_makes_a_first_note(monkeypatch, tmp_path):
    monkeypatch.setattr(httpx, "post", lambda *a, **k: _Resp())
    monkeypatch.chdir(tmp_path)  # write .env / data into an isolated cwd (auto-restored)
    env_snapshot = dict(os.environ)
    try:
        # choose 2 (Groq) · api key · accept default model · decline "open inbox"
        result = CliRunner().invoke(app, ["setup"], input="2\ntest-key\n\nn\n")

        assert result.exit_code == 0, result.output
        assert "Wrote" in result.output
        assert "Connected" in result.output              # the probe passed
        assert "First note ready" in result.output       # cold-start reward landed
        assert Path(".env").is_file()
        env = Path(".env").read_text(encoding="utf-8")
        assert "VERIVANN_LLM=groq" in env
        assert "test-key" in env                          # the key was persisted
    finally:
        os.environ.clear()
        os.environ.update(env_snapshot)  # the wizard mutates os.environ; undo it


def test_setup_skip_runs_offline(monkeypatch, tmp_path):
    monkeypatch.setattr("verivann.cli._maybe_serve", lambda: None)
    monkeypatch.chdir(tmp_path)
    env_snapshot = dict(os.environ)
    try:
        result = CliRunner().invoke(app, ["setup"], input="9\n")  # 9 = "Skip"
        assert result.exit_code == 0, result.output
        assert "offline heuristic" in result.output
        assert not Path(".env").is_file()  # nothing written when skipping
    finally:
        os.environ.clear()
        os.environ.update(env_snapshot)
