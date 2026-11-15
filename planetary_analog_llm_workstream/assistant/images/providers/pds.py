"""NASA Planetary Data System (PDS) planetary image/product provider.

The PDS Geosciences Node ODE REST service is used as the documented product
search interface for Moon and Mars products (LROC, HiRISE and related surface
products). The live response shape is **not** exercised by the test suite;
parsing is deliberately defensive. An unrecognised response yields no records
plus an explicit limitation, never a fabricated product.

Products without a browse/preview image are returned through
``missing_previews`` with their verified product link where one is available.
"""

from __future__ import annotations

import hashlib
from typing import Any

from assistant.images.contracts import (
    ImageRecord,
    ImageSource,
    MissingPreview,
    RejectedAsset,
)
from assistant.images.providers.base import HttpProvider, ProviderOutcome
from assistant.images.validation import UnsafeAssetURL, validate_provider_url

PRODUCT_ID_KEYS = ("ProductId", "product_id", "ProductID", "pdsid", "PDS_ID", "id")
TITLE_KEYS = ("Title", "title", "ProductName", "product_name", "name")
BROWSE_KEYS = (
    "BrowseUrl",
    "browse_url",
    "Browse URL",
    "BrowseImageUrl",
    "browse_image_url",
    "thumbnail_url",
)
PRODUCT_URL_KEYS = (
    "ProductUrl",
    "product_url",
    "Product URL",
    "ProductLink",
    "product_link",
    "url",
)
MISSION_KEYS = ("Mission", "mission", "Spacecraft", "spacecraft")
INSTRUMENT_KEYS = ("Instrument", "instrument", "InstrumentName", "instrument_name")
DATE_KEYS = ("StartTime", "start_time", "ObservationTime", "observation_time", "date")


class PdsProvider(HttpProvider):
    provider = "pds"

    def __init__(
        self,
        *,
        base_url: str = "https://oderest.rsl.wustl.edu/live2/",
        **kwargs: Any,
    ):
        super().__init__(**kwargs)
        self.base_url = base_url

    def search(
        self,
        *,
        target: str,
        keywords: list[str] | None,
        limit: int,
        related_target_id: str | None = None,
    ) -> ProviderOutcome:
        outcome = ProviderOutcome()
        if target not in {"moon", "mars"}:
            outcome.limitations.append(
                "PDS planetary products are retrieved only for Moon and Mars; Earth "
                "uses NASA Image Library and GIBS."
            )
            return outcome

        params: dict[str, Any] = {
            "query": "products",
            "target": target,
            "results": limit,
            "output": "JSON",
        }
        payload = self._get_json(self.base_url, params=params)
        if not isinstance(payload, dict):
            outcome.limitations.append(
                "The PDS search response shape was not recognised; no records were "
                "returned. PDS parsing must be verified against the live service."
            )
            return outcome
        products = _extract_products(payload)
        if products is None:
            outcome.limitations.append(
                "The PDS search response shape was not recognised; no records were "
                "returned. PDS parsing must be verified against the live service."
            )
            return outcome

        for item in products:
            if len(outcome.records) + len(outcome.missing_previews) >= limit:
                break
            if not isinstance(item, dict):
                continue

            product_id = _pick(item, PRODUCT_ID_KEYS)
            title = _pick(item, TITLE_KEYS)
            browse_raw = _pick(item, BROWSE_KEYS)
            product_raw = _pick(item, PRODUCT_URL_KEYS)

            browse = _validated(browse_raw, self.provider, outcome)
            product_url = _validated(product_raw, self.provider, outcome)

            if browse is None:
                outcome.missing_previews.append(
                    MissingPreview(
                        provider=self.provider,
                        provider_record_id=product_id,
                        title=title,
                        product_url=product_url,
                        reason=(
                            "No browse/preview image was supplied for this PDS product. "
                            "The verified archive/product link is returned instead."
                        ),
                    )
                )
                continue

            outcome.records.append(
                ImageRecord(
                    image_id=(
                        f"pds:{product_id}"
                        if product_id
                        else "pds:" + hashlib.sha1(browse.encode()).hexdigest()[:16]
                    ),
                    provider=self.provider,
                    provider_record_id=product_id,
                    title=title,
                    description=_pick(item, ("Description", "description")),
                    planet=target,  # type: ignore[arg-type]
                    location_name=_pick(item, ("Location", "location", "Site", "site")),
                    mission=_pick(item, MISSION_KEYS),
                    instrument=_pick(item, INSTRUMENT_KEYS),
                    date=_pick(item, DATE_KEYS),
                    date_type="acquisition" if _pick(item, DATE_KEYS) else None,
                    image_type="browse_image",
                    thumbnail_url=browse,
                    asset_url=browse,
                    source_record_url=product_url or browse,
                    attribution="NASA Planetary Data System (PDS)",
                    licence=None,
                    related_target_id=related_target_id,
                    relevance_explanation=(
                        "Planetary product returned by the PDS search for the selected "
                        "target. Visual resemblance is not assessed and does not "
                        "establish geological equivalence."
                    ),
                    provenance_notes=[
                        "Fields not supplied by the PDS record remain unavailable.",
                        "Browse images are previews; the archive product is the "
                        "authoritative data product.",
                    ],
                )
            )

        outcome.sources.append(
            ImageSource(
                provider=self.provider,
                collection_url=self.base_url,
                query=", ".join(keywords or []) or target,
                retrieved_count=len(outcome.records),
                attribution="NASA Planetary Data System (PDS)",
            )
        )
        return outcome


def _pick(item: dict[str, Any], keys: tuple[str, ...]) -> str | None:
    for key in keys:
        value = item.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def _validated(url: str | None, provider: str, outcome: ProviderOutcome) -> str | None:
    if not url:
        return None
    try:
        return validate_provider_url(url, provider)
    except UnsafeAssetURL as exc:
        outcome.rejected_assets.append(
            RejectedAsset(provider=provider, url=url, reason=str(exc))
        )
        return None


def _extract_products(payload: dict[str, Any]) -> list[Any] | None:
    for key in ("Products", "products", "Data", "data", "results", "Results"):
        value = payload.get(key)
        if isinstance(value, list):
            return value
        if isinstance(value, dict):
            for nested_key in ("Product", "products", "Items", "items"):
                nested = value.get(nested_key)
                if isinstance(nested, list):
                    return nested
    return None
