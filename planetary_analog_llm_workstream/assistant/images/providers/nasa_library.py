"""NASA Image and Video Library provider.

Endpoints (documented by NASA):
``GET https://images-api.nasa.gov/search``
``GET https://images-api.nasa.gov/asset/{nasa_id}``
``GET https://images-api.nasa.gov/metadata/{nasa_id}``

The library does not supply structured instrument, mission, coordinates or
per-item licence fields in its search response. Those fields stay ``None`` and a
provenance note says so. Only values present in the provider record are used.
"""

from __future__ import annotations

from typing import Any

from assistant.images.contracts import ImageRecord, ImageSource, RejectedAsset
from assistant.images.providers.base import HttpProvider, ProviderOutcome
from assistant.images.validation import UnsafeAssetURL, validate_provider_url

IMAGE_EXTENSIONS = (".jpg", ".jpeg", ".png", ".gif", ".webp", ".tif", ".tiff")


class NasaImageLibraryProvider(HttpProvider):
    provider = "nasa_image_library"

    def __init__(self, *, base_url: str = "https://images-api.nasa.gov", **kwargs: Any):
        super().__init__(**kwargs)
        self.base_url = base_url.rstrip("/")

    def search(
        self,
        query: str,
        *,
        planet: str,
        limit: int,
        related_candidate_id: str | None = None,
        related_target_id: str | None = None,
        image_type: str = "photograph",
    ) -> ProviderOutcome:
        outcome = ProviderOutcome()
        payload = self._get_json(
            f"{self.base_url}/search",
            params={"q": query, "media_type": "image", "page_size": limit},
        )
        if not isinstance(payload, dict):
            outcome.limitations.append(
                "NASA Image Library returned an unexpected JSON shape."
            )
            return outcome

        collection = payload.get("collection")
        items = collection.get("items") if isinstance(collection, dict) else None
        if not isinstance(items, list):
            outcome.limitations.append(
                "NASA Image Library returned no recognisable item collection."
            )
            return outcome

        for item in items:
            if len(outcome.records) >= limit:
                break
            if not isinstance(item, dict):
                continue
            data_list = item.get("data")
            data = data_list[0] if isinstance(data_list, list) and data_list else {}
            if not isinstance(data, dict):
                continue
            nasa_id = data.get("nasa_id")
            if not isinstance(nasa_id, str) or not nasa_id:
                continue

            preview = self._extract_preview(item)
            asset = self._extract_asset(nasa_id, outcome)
            if preview is None and asset is None:
                outcome.rejected_assets.append(
                    RejectedAsset(
                        provider=self.provider,
                        url=None,
                        reason=f"no validated image asset for NASA ID {nasa_id}",
                    )
                )
                continue

            date_created = data.get("date_created")
            date_text = date_created if isinstance(date_created, str) else None
            attribution = _first_text(data.get("secondary_creator"), data.get("center"))
            outcome.records.append(
                ImageRecord(
                    image_id=f"nasa_image_library:{nasa_id}",
                    provider=self.provider,
                    provider_record_id=nasa_id,
                    title=_first_text(data.get("title")),
                    description=_first_text(data.get("description")),
                    planet=planet,  # type: ignore[arg-type]
                    image_type=image_type,  # type: ignore[arg-type]
                    thumbnail_url=preview,
                    asset_url=asset or preview,
                    source_record_url=f"https://images.nasa.gov/details-{nasa_id}",
                    date=date_text,
                    date_type="creation" if date_text else None,
                    attribution=(
                        f"{attribution} (via NASA Image and Video Library)"
                        if attribution
                        else "NASA (via NASA Image and Video Library)"
                    ),
                    licence=None,
                    related_candidate_id=related_candidate_id,
                    related_target_id=related_target_id,
                    relevance_explanation=(
                        f"Returned by the NASA Image Library for the query '{query}'. "
                        "This is keyword relevance only; visual resemblance was not "
                        "assessed and is not geological evidence."
                    ),
                    provenance_notes=[
                        "date is the provider's record creation date, not necessarily "
                        "the acquisition date.",
                        "mission, instrument, coordinates and per-item licence are not "
                        "supplied by the provider search record and remain unavailable.",
                    ],
                )
            )

        outcome.sources.append(
            ImageSource(
                provider=self.provider,
                collection_url=f"{self.base_url}/search",
                query=query,
                retrieved_count=len(outcome.records),
                attribution="NASA Image and Video Library",
            )
        )
        return outcome

    def _extract_preview(self, item: dict[str, Any]) -> str | None:
        links = item.get("links")
        if not isinstance(links, list):
            return None
        for link in links:
            if not isinstance(link, dict):
                continue
            href = link.get("href")
            if not isinstance(href, str):
                continue
            try:
                return validate_provider_url(href, self.provider)
            except UnsafeAssetURL:
                continue
        return None

    def _extract_asset(self, nasa_id: str, outcome: ProviderOutcome) -> str | None:
        try:
            payload = self._get_json(
                f"{self.base_url}/asset/{nasa_id}", allow_list=True
            )
        except Exception as exc:  # provider failure is a limitation, not a crash
            outcome.limitations.append(
                f"NASA Image Library asset lookup failed for {nasa_id}: {exc}"
            )
            return None

        entries = payload if isinstance(payload, list) else payload.get("collection", {})
        hrefs = entries if isinstance(entries, list) else entries.get("items", [])
        if not isinstance(hrefs, list):
            return None

        validated: list[str] = []
        for entry in hrefs:
            href = entry.get("href") if isinstance(entry, dict) else entry
            if not isinstance(href, str):
                continue
            if not href.lower().endswith(IMAGE_EXTENSIONS):
                continue
            try:
                validated.append(validate_provider_url(href, self.provider))
            except UnsafeAssetURL as exc:
                outcome.rejected_assets.append(
                    RejectedAsset(
                        provider=self.provider,
                        url=href,
                        reason=str(exc),
                    )
                )
        if not validated:
            return None
        # The asset list mixes the full-resolution file with derivative
        # thumbnails/small/medium variants. Prefer the first non-derivative
        # original; fall back to the first validated image if none qualifies.
        for url in validated:
            if not _is_derivative(url):
                return url
        return validated[0]


DERIVATIVE_MARKERS = ("~thumb", "~small", "~medium", "~large", "~orig_thumb")


def _is_derivative(url: str) -> bool:
    path = url.rsplit("?", 1)[0].lower()
    return any(marker in path for marker in DERIVATIVE_MARKERS) or "thumb" in path.rsplit("/", 1)[-1]


def _first_text(*values: Any) -> str | None:
    for value in values:
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None
