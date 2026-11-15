"""Ollama local-model adapter.

Only HTTP is used. No hosted inference, API key or paid service is involved.
The adapter exposes health and a single structured generation call. It never
gives the model database or tool access.
"""

from __future__ import annotations

import httpx

from assistant.config import Settings
from assistant.llm.types import ModelResponse, ModelUnavailable

__all__ = [
    "ModelResponse",
    "ModelUnavailable",
    "OllamaClient",
    "ollama_health_payload",
]


class OllamaClient:
    provider_name = "ollama"

    def __init__(self, settings: Settings):
        self.settings = settings
        self.base_url = settings.ollama_base_url.rstrip("/")
        self.model = settings.ollama_model
        self.fallback_model = settings.ollama_fallback_model

    def _installed_models(self) -> tuple[list[str], str | None]:
        try:
            response = httpx.get(
                f"{self.base_url}/api/tags",
                timeout=self.settings.ollama_health_timeout_s,
            )
            response.raise_for_status()
            data = response.json()
            return [m.get("name", "") for m in data.get("models", [])], None
        except Exception as exc:  # noqa: BLE001 - health must not raise
            return [], str(exc)

    @staticmethod
    def _matches(installed: list[str], model: str) -> bool:
        if model in installed:
            return True
        # Ollama may display "name:latest" for an untagged pull.
        return f"{model}:latest" in installed

    def health(self) -> dict:
        installed, error = self._installed_models()
        available = error is None
        configured_present = self._matches(installed, self.model) if available else False
        fallback_present = (
            self._matches(installed, self.fallback_model) if available else False
        )
        return {
            "provider": "ollama",
            "available": available,
            "base_url": self.base_url,
            "configured_model": self.model,
            "configured_model_present": configured_present,
            "fallback_model": self.fallback_model,
            "fallback_model_present": fallback_present,
            "installed_models": installed,
            "error": error,
        }

    def _candidate_models(self) -> list[tuple[str, bool]]:
        installed, error = self._installed_models()
        if error is not None:
            raise ModelUnavailable(f"Ollama is not reachable at {self.base_url}: {error}")
        result: list[tuple[str, bool]] = []
        if self._matches(installed, self.model):
            result.append((self.model, False))
        if (
            self.fallback_model
            and self.fallback_model != self.model
            and self._matches(installed, self.fallback_model)
        ):
            result.append((self.fallback_model, True))
        if not result:
            raise ModelUnavailable(
                f"Neither configured model '{self.model}' nor fallback "
                f"'{self.fallback_model}' is installed in Ollama."
            )
        return result

    def generate(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        json_schema: dict,
    ) -> ModelResponse:
        models = self._candidate_models()
        last_error: Exception | None = None
        for model, used_fallback in models:
            payload = {
                "model": model,
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                "stream": False,
                "format": json_schema,
                "options": {
                    "temperature": self.settings.ollama_temperature,
                    "num_ctx": self.settings.ollama_num_ctx,
                    "num_predict": self.settings.ollama_num_predict,
                    "seed": 42,
                },
            }
            if model.lower().startswith("qwen3") and "thinking" not in model.lower():
                payload["think"] = False
            try:
                response = httpx.post(
                    f"{self.base_url}/api/chat",
                    json=payload,
                    timeout=self.settings.ollama_timeout_s,
                )
                if response.status_code == 400:
                    detail = response.text[:500].strip()
                    if "context" in detail.lower():
                        raise ModelUnavailable(
                            "prompt exceeds the configured Ollama context "
                            f"window ({self.settings.ollama_num_ctx} tokens): {detail}"
                        )
                    # Older Ollama versions do not accept a JSON schema in
                    # `format`; fall back to plain JSON mode.
                    payload["format"] = "json"
                    response = httpx.post(
                        f"{self.base_url}/api/chat",
                        json=payload,
                        timeout=self.settings.ollama_timeout_s,
                    )
                    if response.status_code >= 400:
                        raise ModelUnavailable(
                            f"Ollama rejected the request (HTTP "
                            f"{response.status_code}): {response.text[:500].strip()}"
                        )
                    if detail:
                        last_error = RuntimeError(
                            "Ollama rejected structured output; retried JSON "
                            f"mode: {detail}"
                        )
                response.raise_for_status()
                data = response.json()
                message = data.get("message", {})
                content = message.get("content") or ""
                if not content.strip():
                    thinking = message.get("thinking") or ""
                    if thinking:
                        raise ModelUnavailable(
                            "model returned reasoning-only output with no JSON content"
                        )
                    raise ModelUnavailable("model returned empty content")
                return ModelResponse(
                    content=content,
                    model=model,
                    used_fallback_model=used_fallback,
                    done_reason=data.get("done_reason"),
                    prompt_eval_count=data.get("prompt_eval_count"),
                    eval_count=data.get("eval_count"),
                )
            except Exception as exc:  # noqa: BLE001 - try fallback model
                last_error = exc
                continue
        raise ModelUnavailable(f"local generation failed: {last_error}")


def ollama_health_payload(client: OllamaClient) -> dict:
    """Public health payload without leaking filesystem or environment secrets."""
    health = client.health()
    return {
        "available": health["available"],
        "base_url": health["base_url"],
        "configured_model": health["configured_model"],
        "configured_model_present": health["configured_model_present"],
        "fallback_model": health["fallback_model"],
        "fallback_model_present": health["fallback_model_present"],
        "installed_models": health["installed_models"],
        "error": health["error"],
        "mode": "local_ollama",
    }
