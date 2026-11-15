"""NASA GIBS Earth-observation imagery (Earth only).

GIBS is used only for Earth visualization. It is never used as a Moon or Mars
source. The provider returns a validated WMS GetMap configuration; it does not
claim that the imagery is a scientific measurement or that it proves analogy.
"""

from __future__ import annotations

import re
from datetime import date as date_cls
from typing import Any
from urllib.parse import urlencode

from assistant.images.contracts import ImageRecord, ImageSource, RejectedAsset
from assistant.images.providers.base import HttpProvider, ProviderOutcome
from assistant.images.validation import UnsafeAssetURL, validate_provider_url

# Documented GIBS layers used by this workstream. Unknown layers are refused
# rather than passed through to the service.
SUPPORTED_LAYERS: dict[str, str] = {
    "MODIS_Terra_CorrectedReflectance_TrueColor": "MODIS Terra corrected reflectance (true colour)",
    "VIIRS_SNPP_CorrectedReflectance_TrueColor": "VIIRS SNPP corrected reflectance (true colour)",
    "MODIS_Terra_Land_Surface_Temp_Day": "MODIS Terra daytime land-surface temperature",
    "MODIS_Terra_SurfaceReflectance_Bands143": "MODIS Terra surface reflectance (bands 1-4-3)",
}

DATE_PATTERN = re.compile(r"^\d{4}-\d{2}-\d{2}$")


class GibsProvider(HttpProvider):
    provider = "gibs"

    def __init__(
        self,
        *,
        base_url: str = "https://gibs.earthdata.nasa.gov/wms/epsg4326/best/wms.cgi",
        **kwargs: Any,
    ):
        super().__init__(**kwargs)
        self.base_url = base_url

    def layer_image(
        self,
        *,
        layer: str | None,
        latitude: float | None,
        longitude: float | None,
        target_layer_date: str | None,
        related_candidate_id: str | None = None,
        related_target_id: str | None = None,
        half_span_degrees: float = 2.0,
    ) -> ProviderOutcome:
        outcome = ProviderOutcome()

        if latitude is None or longitude is None:
            outcome.limitations.append(
                "GIBS Earth imagery was skipped because no candidate coordinates were "
                "supplied. Coordinates are never invented."
            )
            return outcome

        chosen_layer = layer or "MODIS_Terra_CorrectedReflectance_TrueColor"
        if chosen_layer not in SUPPORTED_LAYERS:
            outcome.limitations.append(
                f"GIBS layer '{chosen_layer}' is not in the supported layer list; no "
                "imagery request was made."
            )
            outcome.rejected_assets.append(
                RejectedAsset(
                    provider=self.provider,
                    url=None,
                    reason=f"unsupported GIBS layer: {chosen_layer}",
                )
            )
            return outcome

        layer_date: str | None = None
        if target_layer_date:
            if not DATE_PATTERN.match(target_layer_date):
                outcome.limitations.append(
                    f"GIBS date '{target_layer_date}' is not YYYY-MM-DD; no imagery "
                    "request was made."
                )
                return outcome
            try:
                date_cls.fromisoformat(target_layer_date)
            except ValueError:
                outcome.limitations.append(
                    f"GIBS date '{target_layer_date}' is not a valid calendar date; no "
                    "imagery request was made."
                )
                return outcome
            layer_date = target_layer_date

        bbox = (
            max(-180.0, longitude - half_span_degrees),
            max(-90.0, latitude - half_span_degrees),
            min(180.0, longitude + half_span_degrees),
            min(90.0, latitude + half_span_degrees),
        )
        params: dict[str, Any] = {
            "SERVICE": "WMS",
            "REQUEST": "GetMap",
            "VERSION": "1.1.1",
            "LAYERS": chosen_layer,
            "STYLES": "",
            "SRS": "EPSG:4326",
            "BBOX": ",".join(f"{value:.4f}" for value in bbox),
            "WIDTH": 1024,
            "HEIGHT": 1024,
            "FORMAT": "image/png",
        }
        if layer_date:
            params["TIME"] = layer_date

        url = f"{self.base_url}?{urlencode(params)}"
        try:
            safe_url = validate_provider_url(url, self.provider)
        except UnsafeAssetURL as exc:  # pragma: no cover - configuration guard
            outcome.limitations.append(f"GIBS URL failed validation: {exc}")
            return outcome

        outcome.records.append(
            ImageRecord(
                image_id=f"gibs:{chosen_layer}:{latitude:.4f}:{longitude:.4f}:{layer_date or 'default'}",
                provider=self.provider,
                provider_record_id=chosen_layer,
                title=(
                    f"GIBS {SUPPORTED_LAYERS[chosen_layer]} near "
                    f"{latitude:.4f}, {longitude:.4f}"
                ),
                description=(
                    "WMS GetMap configuration for a GIBS Earth-observation layer "
                    "centred on the supplied candidate coordinates."
                ),
                planet="earth",
                latitude=latitude,
                longitude=longitude,
                date=layer_date,
                date_type="unknown" if layer_date else None,
                image_type="visualization",
                thumbnail_url=safe_url,
                asset_url=safe_url,
                source_record_url="https://nasa-gibs.github.io/gibs-api-docs/",
                attribution="NASA EOSDIS Global Imagery Browse Services (GIBS)",
                licence=None,
                related_candidate_id=related_candidate_id,
                related_target_id=related_target_id,
                relevance_explanation=(
                    "Earth observation visualization for the candidate coordinates. "
                    "It supports environmental context only; visual appearance does "
                    "not establish geological equivalence."
                ),
                provenance_notes=[
                    f"GIBS layer: {chosen_layer}",
                    (
                        "date is the requested layer date, not a verified acquisition "
                        "timestamp."
                        if layer_date
                        else "No date was supplied; the GIBS service default date applies."
                    ),
                    (
                        "The WMS URL is host/scheme validated but not fetched by the "
                        "assistant, so its HTTP status and content-type are unverified "
                        "until the browser requests it."
                    ),
                ],
            )
        )
        outcome.sources.append(
            ImageSource(
                provider=self.provider,
                collection_url=self.base_url,
                query=chosen_layer,
                retrieved_count=1,
                attribution="NASA EOSDIS GIBS",
            )
        )
        return outcome
