"""Runtime configuration.

Everything that could be private - real domains, staging location, the LLM
provider/model/key - comes from the environment or an (uncommitted) private
config. Neutral defaults keep the public core runnable and free on its own:
with no LLM configured, analysis falls back to the offline heuristic.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path

from .analysis.lenses import DEFAULT_LENS
from .registry import DEFAULT_PUBLIC_DOMAINS

# provider -> (default base_url, default api_key)
#
# Nearly everyone speaks the OpenAI wire format now, so a preset is just a base
# URL. These exist because "work out the right base_url yourself" is a terrible
# first experience - and because the FREE tiers are the point: a person should be
# able to run this properly without paying anyone a cent.
_PROVIDER_DEFAULTS = {
    "openai": ("https://api.openai.com/v1", ""),
    "anthropic": ("https://api.anthropic.com", ""),
    # Local - nothing ever leaves the machine.
    "ollama": ("http://localhost:11434/v1", "ollama"),
    "lmstudio": ("http://localhost:1234/v1", "lmstudio"),
    # Hosted, all with a free tier.
    "cloudflare": ("", ""),  # needs the account id - see _preset_base()
    "groq": ("https://api.groq.com/openai/v1", ""),
    "openrouter": ("https://openrouter.ai/api/v1", ""),
    "gemini": ("https://generativelanguage.googleapis.com/v1beta/openai/", ""),
    "together": ("https://api.together.xyz/v1", ""),
    "deepseek": ("https://api.deepseek.com/v1", ""),
    "mistral": ("https://api.mistral.ai/v1", ""),
}

LOCAL_PROVIDERS = ("ollama", "lmstudio")


@dataclass
class LLMConfig:
    provider: str = ""  # a key of _PROVIDER_DEFAULTS  (empty = disabled)
    model: str = ""
    base_url: str = ""
    api_key: str = ""
    # More models to try, in order, on THIS endpoint. Free tiers rate-limit
    # constantly; a second model on the same provider is the cheapest recovery there is.
    models: list[str] = field(default_factory=list)
    # A different provider to fall back to when this one is exhausted entirely.
    fallback: LLMConfig | None = None

    @property
    def enabled(self) -> bool:
        return bool(self.provider and (self.model or self.models))

    def candidates(self) -> list[tuple[LLMConfig, str]]:
        """(slot, model) pairs to try in order: this slot's models, then the fallback's."""
        out: list[tuple[LLMConfig, str]] = []
        for model in ([self.model] if self.model else []) + list(self.models):
            if model and not any(m == model and s is self for s, m in out):
                out.append((self, model))
        if self.fallback and self.fallback.enabled:
            out.extend(self.fallback.candidates())
        return out


@dataclass
class EmbedConfig:
    """The embedding slot - separate from the chat slot on purpose.

    Local embeddings are cheap and private (Ollama: `nomic-embed-text`), so many
    people will want meaning-search locally even while using a hosted model for
    analysis. Anthropic has no embeddings endpoint; point base_url at whatever does.
    """

    model: str = ""
    base_url: str = ""
    api_key: str = ""


@dataclass
class Config:
    staging_dir: Path = field(default_factory=lambda: Path("data/staging"))
    domains: list[str] = field(default_factory=lambda: list(DEFAULT_PUBLIC_DOMAINS))
    public_demo: bool = True
    llm: LLMConfig = field(default_factory=LLMConfig)
    # The slot that never leaves the machine. Sensitive material (anything off your
    # own disk, anything carrying an IBAN or a diagnosis) is routed here - see
    # privacy.py. Without it, sensitive material is not uploaded; it is simply not
    # read by a model at all.
    local_llm: LLMConfig = field(default_factory=LLMConfig)
    embed: EmbedConfig = field(default_factory=EmbedConfig)
    lens: str = DEFAULT_LENS  # default reading intent; per-run overridable
    price_per_mtok: float = 0.0  # € per million tokens; 0 = unknown, and we say so

    @classmethod
    def load(cls) -> Config:
        staging = os.environ.get("VERIVANN_STAGING", "data/staging")
        domains = list(DEFAULT_PUBLIC_DOMAINS)
        public_demo = True

        # A private config file (path via env) may inject the real domains.
        private_path = os.environ.get("VERIVANN_PRIVATE_CONFIG")
        if private_path and Path(private_path).is_file():
            try:
                data = json.loads(Path(private_path).read_text(encoding="utf-8"))
                if isinstance(data.get("domains"), list) and data["domains"]:
                    domains = [str(d) for d in data["domains"]]
                    public_demo = bool(data.get("public_demo", False))
            except (ValueError, OSError):
                pass

        llm = _load_llm()
        try:
            price = float(os.environ.get("VERIVANN_PRICE_PER_MTOK", "0") or 0)
        except ValueError:
            price = 0.0
        return cls(
            staging_dir=Path(staging),
            domains=domains,
            public_demo=public_demo,
            llm=llm,
            local_llm=_load_llm("VERIVANN_LOCAL_LLM"),
            embed=_load_embed(llm),
            lens=os.environ.get("VERIVANN_LENS", DEFAULT_LENS).strip().lower() or DEFAULT_LENS,
            price_per_mtok=price,
        )


def _preset_base(provider: str, default: str) -> str:
    """Cloudflare's endpoint carries the account id - everyone else's is a constant."""
    if provider == "cloudflare":
        account = os.environ.get("VERIVANN_CF_ACCOUNT_ID", "").strip()
        return f"https://api.cloudflare.com/client/v4/accounts/{account}/ai/v1" if account else ""
    return default


def _load_llm(prefix: str = "VERIVANN_LLM") -> LLMConfig:
    provider = os.environ.get(prefix, "").strip().lower()
    if not provider:
        return LLMConfig()  # disabled -> heuristic
    d_base, d_key = _PROVIDER_DEFAULTS.get(provider, ("", ""))
    models = [m.strip() for m in os.environ.get(f"{prefix}_MODELS", "").split(",") if m.strip()]
    fallback = _load_llm(f"{prefix}_FALLBACK") if os.environ.get(f"{prefix}_FALLBACK") else None
    return LLMConfig(
        provider=provider,
        model=os.environ.get(f"{prefix}_MODEL", ""),
        base_url=os.environ.get(f"{prefix}_BASE_URL", _preset_base(provider, d_base)),
        api_key=os.environ.get(f"{prefix}_API_KEY", d_key),
        models=models,
        fallback=fallback,
    )


def _load_embed(llm: LLMConfig) -> EmbedConfig:
    """Defaults to the chat provider's endpoint - but only if that provider has one."""
    model = os.environ.get("VERIVANN_EMBED_MODEL", "").strip()
    if not model:
        return EmbedConfig()  # disabled -> keyword search only
    fallback_base = "" if llm.provider == "anthropic" else llm.base_url
    return EmbedConfig(
        model=model,
        base_url=os.environ.get("VERIVANN_EMBED_BASE_URL", fallback_base),
        api_key=os.environ.get("VERIVANN_EMBED_API_KEY", llm.api_key),
    )
