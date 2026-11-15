"""Groq hosted-inference adapter (OpenAI-compatible chat completions).

The adapter is optional and server-side only. It reads the API key from the
environment, sends it only in the request header, and never logs, returns or
serialises it. Model output is *not* trusted: it goes through exactly the same
structured parsing and evidence validation as the local Ollama provider.

Docs: https://console.groq.com/docs/quickstart
      https://console.groq.com/docs/structured-outputs
"""

from __future__ import annotations

import httpx

from assistant.config import Settings
from assistant.llm.types import ModelResponse, ModelUnavailable

DEFAULT_BASE_URL = "https://api.groq.com/openai/v1"
_SCHEMA_NAME = "assistant_model_draft"
_MAX_DETAIL_CHARS = 400


class GroqClient:
    provider_name = "groq"

    def __init__(self, settings: Settings):
        self.settings = settings
        self.base_url = (settings.groq_base_url or DEFAULT_BASE_URL).strip().rstrip("/")
        self.model = settings.groq_model
        self.timeout_s = settings.groq_timeout_s
        key = settings.groq_api_key
        self._api_key = key.get_secret_value().strip() if key is not None else ""

    # ------------------------------------------------------------------
    # Credentials
    # ------------------------------------------------------------------
    @property
    def configured(self) -> bool:
        """True when a key is present. Presence is not proof of reachability."""
        return bool(self._api_key)

    def _redact(self, text: str) -> str:
        if self._api_key and self._api_key in text:
            return text.replace(self._api_key, "[redacted]")
        return text

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

    def __repr__(self) -> str:  # pragma: no cover - defensive, no key exposed
        return f"GroqClient(model={self.model!r}, configured={self.configured})"

    # ------------------------------------------------------------------
    # Health
    # ------------------------------------------------------------------
    def health(self) -> dict:
        """Report configuration and *actual* reachability.

        A configured key alone never sets ``available``. Availability requires a
        successful authenticated ``GET /models``. The API key is never included.
        """
        payload: dict = {
            "provider": "groq",
            "mode": "hosted_groq",
            "configured": self.configured,
            "available": False,
            "reachable": False,
            "authenticated": False,
            "base_url": self.base_url,
            "configured_model": self.model,
            "configured_model_present": None,
            "installed_models": [],
            "timeout_s": self.timeout_s,
            "error": None,
        }
        if not self.configured:
            payload["error"] = "GROQ_API_KEY is not configured"
            return payload
        try:
            response = httpx.get(
                f"{self.base_url}/models",
                headers=self._headers(),
                timeout=self.settings.groq_health_timeout_s,
            )
        except httpx.TimeoutException:
            payload["error"] = f"Groq health check timed out at {self.base_url}"
            return payload
        except httpx.HTTPError as exc:
            payload["error"] = self._redact(
                f"Groq is not reachable at {self.base_url}: {type(exc).__name__}"
            )
            return payload

        payload["reachable"] = True
        if response.status_code in (401, 403):
            payload["error"] = f"Groq rejected the API key (HTTP {response.status_code})"
            return payload
        if response.status_code >= 400:
            payload["error"] = f"Groq model listing failed (HTTP {response.status_code})"
            return payload

        payload["authenticated"] = True
        payload["available"] = True
        try:
            data = response.json()
        except ValueError:
            data = {}
        models = [
            item.get("id", "")
            for item in data.get("data", [])
            if isinstance(item, dict) and item.get("id")
        ]
        payload["installed_models"] = models
        payload["configured_model_present"] = self.model in models if models else None
        return payload

    # ------------------------------------------------------------------
    # Generation
    # ------------------------------------------------------------------
    def _response_format(self, json_schema: dict) -> dict:
        return {
            "type": "json_schema",
            "json_schema": {
                "name": _SCHEMA_NAME,
                "strict": self.settings.groq_strict_schema,
                "schema": json_schema,
            },
        }

    def _detail(self, response: httpx.Response) -> str:
        try:
            text = response.text
        except Exception:  # noqa: BLE001 - diagnostics must never raise
            text = ""
        return self._redact(text.strip()[:_MAX_DETAIL_CHARS])

    def _send(self, payload: dict) -> httpx.Response:
        try:
            return httpx.post(
                f"{self.base_url}/chat/completions",
                headers=self._headers(),
                json=payload,
                timeout=self.timeout_s,
            )
        except httpx.TimeoutException as exc:
            raise ModelUnavailable(
                f"Groq request timed out after {self.timeout_s:g}s at {self.base_url}"
            ) from exc
        except httpx.HTTPError as exc:
            raise ModelUnavailable(
                self._redact(
                    f"Groq is unreachable at {self.base_url}: {type(exc).__name__}"
                )
            ) from exc

    def _interpret(self, response: httpx.Response) -> dict:
        if response.status_code in (401, 403):
            raise ModelUnavailable(
                "Groq rejected the API key "
                f"(HTTP {response.status_code}); check GROQ_API_KEY."
            )
        if response.status_code == 404:
            raise ModelUnavailable(
                f"Groq model '{self.model}' is not available (HTTP 404); "
                "check GROQ_MODEL."
            )
        if response.status_code == 429:
            retry_after = response.headers.get("retry-after")
            hint = f" Retry after {retry_after} s." if retry_after else ""
            raise ModelUnavailable(f"Groq rate limit exceeded (HTTP 429).{hint}")
        if response.status_code == 400:
            raise ModelUnavailable(
                f"Groq rejected the request (HTTP 400): {self._detail(response)}"
            )
        if response.status_code >= 400:
            raise ModelUnavailable(
                f"Groq request failed (HTTP {response.status_code}): "
                f"{self._detail(response)}"
            )
        try:
            data = response.json()
        except ValueError as exc:
            raise ModelUnavailable("Groq returned a non-JSON response") from exc
        if not isinstance(data, dict):
            raise ModelUnavailable("Groq returned a malformed response envelope")
        return data

    def _post(self, payload: dict) -> dict:
        response = self._send(payload)
        if response.status_code == 400:
            lowered = self._detail(response).lower()
            if "response_format" in lowered or "json_schema" in lowered:
                # The selected model may only support JSON object mode. Retry
                # once; the schema is still enforced by server-side validation.
                retry = dict(payload)
                retry["response_format"] = {"type": "json_object"}
                return self._interpret(self._send(retry))
        return self._interpret(response)

    @staticmethod
    def _content(data: dict) -> str:
        choices = data.get("choices")
        if not isinstance(choices, list) or not choices:
            raise ModelUnavailable("Groq returned a malformed response: no choices")
        first = choices[0]
        message = first.get("message") if isinstance(first, dict) else None
        if not isinstance(message, dict):
            raise ModelUnavailable("Groq returned a malformed response: no message")
        content = message.get("content")
        if not isinstance(content, str) or not content.strip():
            raise ModelUnavailable("Groq returned an empty response")
        return content

    def generate(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        json_schema: dict,
    ) -> ModelResponse:
        if not self.configured:
            raise ModelUnavailable(
                "GROQ_API_KEY is not configured; hosted Groq inference is unavailable."
            )
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "temperature": self.settings.groq_temperature,
            "max_completion_tokens": self.settings.groq_max_completion_tokens,
            "response_format": self._response_format(json_schema),
        }
        data = self._post(payload)
        content = self._content(data)
        usage = data.get("usage")
        usage = usage if isinstance(usage, dict) else {}
        choices = data.get("choices") or [{}]
        return ModelResponse(
            content=content,
            model=data.get("model") or self.model,
            provider="groq",
            done_reason=choices[0].get("finish_reason"),
            prompt_eval_count=usage.get("prompt_tokens"),
            eval_count=usage.get("completion_tokens"),
            total_tokens=usage.get("total_tokens"),
        )
