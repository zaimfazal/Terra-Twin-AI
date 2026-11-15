"""Inference-provider selection.

Ollama remains the default local provider. Groq is optional and selected only
when ``ASSISTANT_LLM_PROVIDER=groq``. Callers depend on the shared
``generate``/``health`` interface, never on a specific backend.
"""

from __future__ import annotations

from assistant.config import Settings
from assistant.llm.ollama import OllamaClient


def build_llm_client(settings: Settings):
    """Return the configured provider client.

    Imported lazily so the hosted adapter is never required for local use.
    """
    if settings.llm_provider == "groq":
        from assistant.llm.groq import GroqClient

        return GroqClient(settings)
    return OllamaClient(settings)


def provider_health_payload(client) -> dict:
    """Provider-agnostic health payload.

    Only fields the client reports are returned; the payload never contains
    credentials, and a configured credential alone is not reported as
    available (each client decides that from an actual probe).
    """
    health = dict(client.health())
    provider = health.get("provider") or getattr(client, "provider_name", "ollama")
    health["provider"] = provider
    health.setdefault("mode", "local_ollama" if provider == "ollama" else provider)
    return health
