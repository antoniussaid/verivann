"""First run - connect a model without reading the manual.

Everything in Verivann works offline on a keyword heuristic, but a model is where it
comes alive: summaries, claims, predictions, lenses, the credibility ledger. The
barrier is that a newcomer has no idea how to connect one. This removes that barrier.

`verivann setup` asks a few plain questions, writes a `.env`, and offers to launch the
inbox. The env-composition is a pure function (`compose_env`) so it can be tested;
the prompting lives in the CLI.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Preset:
    key: str
    label: str
    free: bool
    local: bool
    needs_key: bool
    needs_account: bool  # Cloudflare's endpoint carries an account id
    default_model: str
    default_embed: str  # "" = this provider has no embeddings endpoint
    hint: str


# Ordered as they should be offered: free first, local prominent, paid last.
PRESETS: list[Preset] = [
    Preset("cloudflare", "Cloudflare Workers AI", True, False, True, True,
           "@cf/meta/llama-3.3-70b-instruct-fp8-fast", "@cf/baai/bge-base-en-v1.5",
           "Free tier. If antonius.app runs on Cloudflare you already have an account + token."),
    Preset("groq", "Groq", True, False, True, False,
           "llama-3.3-70b-versatile", "",
           "Free tier, very fast. Get a key at console.groq.com."),
    Preset("gemini", "Google Gemini", True, False, True, False,
           "gemini-2.0-flash", "text-embedding-004",
           "Free tier. Get a key at aistudio.google.com."),
    Preset("openrouter", "OpenRouter", True, False, True, False,
           "meta-llama/llama-3.3-70b-instruct:free", "",
           "Many models, some marked ':free'. Get a key at openrouter.ai."),
    Preset("ollama", "Ollama (fully local, private, free forever)", True, True, False, False,
           "llama3.2:3b", "nomic-embed-text",
           "Runs on your machine, nothing leaves it. Install from ollama.com, then `ollama pull llama3.2:3b`."),
    Preset("lmstudio", "LM Studio (local)", True, True, False, False,
           "", "",
           "A local server from lmstudio.ai. Load a model there, then use its name."),
    Preset("openai", "OpenAI (paid)", False, False, True, False,
           "gpt-4o-mini", "text-embedding-3-small",
           "Strong, cheap-ish, costs per call. Key from platform.openai.com."),
    Preset("anthropic", "Anthropic Claude (paid)", False, False, True, False,
           "claude-haiku-4-5-20251001", "",
           "Strong, costs per call. Key from console.anthropic.com."),
]

_BY_KEY = {p.key: p for p in PRESETS}


def preset(key: str) -> Preset | None:
    return _BY_KEY.get(key)


def compose_env(
    provider: str,
    *,
    account: str = "",
    api_key: str = "",
    model: str = "",
    embed_model: str = "",
) -> dict[str, str]:
    """The env vars for a chosen provider. Pure - no I/O, no prompting.

    The main slot (`VERIVANN_LLM`) reads everything. If the provider is local, it is
    ALSO written as the privacy slot (`VERIVANN_LOCAL_LLM`) - otherwise sensitive
    material (your files, IBANs, diagnoses) would fall to the heuristic instead of
    being read by the very local model you just configured.
    """
    p = preset(provider)
    if p is None:
        return {}

    chosen_model = model or p.default_model
    env: dict[str, str] = {"VERIVANN_LLM": provider}
    if chosen_model:
        env["VERIVANN_LLM_MODEL"] = chosen_model
    if p.needs_account and account:
        env["VERIVANN_CF_ACCOUNT_ID"] = account
    if p.needs_key and api_key:
        env["VERIVANN_LLM_API_KEY"] = api_key

    chosen_embed = embed_model or p.default_embed
    if chosen_embed:
        env["VERIVANN_EMBED_MODEL"] = chosen_embed

    if p.local:
        # Nothing this provider sees ever leaves the machine - so it is also the safe
        # home for sensitive material, and the privacy default is strict.
        env["VERIVANN_LOCAL_LLM"] = provider
        if chosen_model:
            env["VERIVANN_LOCAL_LLM_MODEL"] = chosen_model
        env["VERIVANN_PRIVACY"] = "strict"
    return env


@dataclass(frozen=True)
class Probe:
    ok: bool
    model: str
    detail: str  # the model's reply on success, a human reason on failure


def verify_connection(llm) -> Probe:
    """One tiny model call, to prove the config actually reaches a model.

    A trusted, fixed prompt with no untrusted material (so the canary is off). Every
    failure - wrong key, wrong model name, server down, rate limit - comes back as
    `ok=False` with a short human reason. It never raises: the whole point is to turn
    a silent misconfiguration into an answer the newcomer can act on immediately.
    """
    from .analysis.llm import call

    if not llm.enabled:
        return Probe(False, llm.model or "", "no model configured")
    try:
        reply, model = call(
            llm,
            "You are a connection test. Reply with the single word: OK.",
            "ping",
            guard=False,
        )
    except Exception as exc:  # noqa: BLE001 - report, never crash the wizard
        return Probe(False, llm.model or "", _friendly_error(exc))
    return Probe(True, model, reply.strip()[:60] or "(connected; empty reply)")


def _friendly_error(exc: Exception) -> str:
    """Map whatever went wrong to one plain sentence. call() wraps the typed httpx
    error inside AllModelsFailed, so we read the message text rather than the type."""
    msg = str(exc)
    low = msg.lower()
    if any(s in msg for s in ("401", "403")) or "unauthor" in low or "forbidden" in low:
        return "the API key was rejected - check the key and try again"
    if "404" in msg or "not found" in low or "not_found" in low:
        return "that model or endpoint was not found - check the model name"
    if "429" in msg or "rate" in low or "quota" in low:
        return "rate-limited right now - the connection works, try again shortly"
    if any(s in low for s in ("connect", "refused", "resolve", "timed out", "timeout", "unreachable")):
        return "could not reach the server - check the URL, or that it is running"
    if "no model configured" in low:
        return "no model configured"
    return (msg[:140] or exc.__class__.__name__)


def welcome_text() -> tuple[str, str]:
    """A real, short piece for the newcomer's first note - so the inbox is never empty
    and the whole pipeline (extract → analyze → note) proves itself end to end."""
    title = "Welcome to Verivann"
    text = (
        "Verivann turns anything you read, watch, or listen to into a short, honest note "
        "you actually own. It never posts, never phones home with your data, and never "
        "commits a note to your knowledge base on its own - every note is a proposal until "
        "you accept it. It also does what a bookmark never could: it flags who profits from "
        "a source, catches instructions hidden inside the material that try to hijack the "
        "analysis, and keeps a running record of what each source has later turned out to be "
        "right or wrong about. This note was made by that same pipeline, just now, from this "
        "very paragraph - proof that your model connection works."
    )
    return title, text


def write_env(path: Path, values: dict[str, str]) -> Path:
    """Merge `values` into a `.env`, preserving any lines the user already had.

    Existing keys are updated in place; new ones are appended. Comments and unrelated
    lines are untouched. Never prints a secret.
    """
    lines: list[str] = []
    if path.is_file():
        lines = path.read_text(encoding="utf-8").splitlines()

    remaining = dict(values)
    out: list[str] = []
    for line in lines:
        stripped = line.strip()
        if stripped and not stripped.startswith("#") and "=" in stripped:
            key = stripped.split("=", 1)[0].strip()
            if key in remaining:
                out.append(f"{key}={remaining.pop(key)}")
                continue
        out.append(line)

    if remaining:
        if out and out[-1].strip():
            out.append("")
        out.append("# written by `verivann setup`")
        out.extend(f"{k}={v}" for k, v in remaining.items())

    path.write_text("\n".join(out) + "\n", encoding="utf-8")
    return path
