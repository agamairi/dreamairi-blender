"""Provider factory."""
from __future__ import annotations

from typing import Optional

from .base import Provider
from .gemini_provider import GeminiProvider
from .ollama_provider import OllamaProvider
from .openai_provider import OpenAIProvider
from .openrouter_provider import OpenRouterProvider
from ..security.secrets import SecretsStore


def build_provider(
    provider: str,
    base_url: str,
    model_name: str,
    secrets: SecretsStore,
) -> Provider:
    if provider == "OPENROUTER":
        return OpenRouterProvider(secrets.get_api_key(), base_url)
    if provider == "OPENAI":
        return OpenAIProvider(secrets.get_api_key(), base_url or "https://api.openai.com/v1")
    if provider == "GEMINI":
        return GeminiProvider(secrets.get_api_key(), base_url)
    if provider == "OLLAMA":
        return OllamaProvider(base_url)
    raise RuntimeError(f"Unsupported provider: {provider}")


def requires_api_key(provider: str) -> bool:
    return provider in {"OPENROUTER", "OPENAI", "GEMINI"}


def default_base_url(provider: str) -> Optional[str]:
    return {
        "OPENROUTER": "https://openrouter.ai/api/v1",
        "OPENAI": "https://api.openai.com/v1",
        "GEMINI": "https://generativelanguage.googleapis.com/v1beta",
        "OLLAMA": "http://localhost:11434",
    }.get(provider)
