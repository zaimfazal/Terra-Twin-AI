"""Shared HTTP behaviour for NASA image providers."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import httpx

from assistant.images.contracts import (
    ImageRecord,
    ImageSource,
    MissingPreview,
    RejectedAsset,
)
from assistant.images.validation import validate_provider_url


class ProviderError(RuntimeError):
    """A provider could not answer; the orchestrator records a limitation."""


class RateLimited(ProviderError):
    def __init__(self, message: str, retry_after: str | None = None):
        super().__init__(message)
        self.retry_after = retry_after


@dataclass
class ProviderOutcome:
    records: list[ImageRecord] = field(default_factory=list)
    sources: list[ImageSource] = field(default_factory=list)
    missing_previews: list[MissingPreview] = field(default_factory=list)
    rejected_assets: list[RejectedAsset] = field(default_factory=list)
    limitations: list[str] = field(default_factory=list)

    def merge(self, other: ProviderOutcome) -> None:
        self.records.extend(other.records)
        self.sources.extend(other.sources)
        self.missing_previews.extend(other.missing_previews)
        self.rejected_assets.extend(other.rejected_assets)
        self.limitations.extend(other.limitations)


class HttpProvider:
    provider: str = ""

    def __init__(
        self,
        *,
        client: httpx.Client | None = None,
        transport: httpx.BaseTransport | None = None,
        timeout_s: float = 15.0,
    ) -> None:
        self.timeout_s = timeout_s
        self._owns_client = client is None
        self._client = client or httpx.Client(
            timeout=httpx.Timeout(timeout_s, connect=min(5.0, timeout_s)),
            headers={"Accept": "application/json, image/*;q=0.8"},
            follow_redirects=False,
            transport=transport,
        )

    def close(self) -> None:
        if self._owns_client:
            self._client.close()

    def _get_json(
        self,
        url: str,
        params: dict[str, Any] | None = None,
        *,
        allow_list: bool = False,
    ) -> dict[str, Any] | list[Any]:
        safe_url = validate_provider_url(url, self.provider)
        try:
            response = self._client.get(safe_url, params=params)
        except httpx.TimeoutException as exc:
            raise ProviderError(
                f"{self.provider} timed out after {self.timeout_s}s"
            ) from exc
        except httpx.TransportError as exc:
            raise ProviderError(f"{self.provider} unreachable: {exc}") from exc

        if response.status_code == 429:
            raise RateLimited(
                f"{self.provider} rate limit reached (HTTP 429)",
                retry_after=response.headers.get("retry-after"),
            )
        if response.status_code >= 300 and response.status_code < 400:
            raise ProviderError(f"{self.provider} returned a redirect; not followed")
        if response.status_code < 200 or response.status_code >= 300:
            raise ProviderError(
                f"{self.provider} returned HTTP {response.status_code}"
            )
        try:
            payload = response.json()
        except ValueError as exc:
            raise ProviderError(f"{self.provider} returned non-JSON content") from exc
        if isinstance(payload, dict):
            return payload
        if allow_list and isinstance(payload, list):
            return payload
        raise ProviderError(f"{self.provider} returned an unexpected JSON shape")
