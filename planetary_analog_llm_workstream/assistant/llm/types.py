"""Shared inference-provider types.

Both the local Ollama adapter and the optional hosted Groq adapter return the
same ``ModelResponse`` and raise the same ``ModelUnavailable``. The generation
pipeline therefore validates provider output identically and can fall back for
any provider failure.
"""

from __future__ import annotations

from dataclasses import dataclass


class ModelUnavailable(RuntimeError):
    """Raised when a provider cannot return a usable response."""


@dataclass
class ModelResponse:
    content: str
    model: str
    used_fallback_model: bool = False
    done_reason: str | None = None
    prompt_eval_count: int | None = None
    eval_count: int | None = None
    # Hosted providers report an explicit provider name and total token count.
    # Both stay ``None`` for providers that do not supply them.
    provider: str | None = None
    total_tokens: int | None = None
