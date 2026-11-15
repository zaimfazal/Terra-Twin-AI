"""Cross-planetary image retrieval orchestration.

Providers are queried only with keywords derived from stored records (candidate
name/country/morphology and target name/scientific targets) or explicit caller
keywords. Provider failures degrade to limitations. Results are grouped under
Earth, Moon and Mars, deduplicated, and never scored.
"""

from __future__ import annotations

from typing import Iterable

from assistant.contracts import DataProvenanceMode
from assistant.images.contracts import (
    ImageRecord,
    ImageSearchRequest,
    ImageSearchResponse,
    MissingPreview,
    RejectedAsset,
)
from assistant.images.providers.base import (
    ProviderError,
    ProviderOutcome,
    RateLimited,
)
from assistant.images.providers.gibs import GibsProvider
from assistant.images.providers.nasa_library import NasaImageLibraryProvider
from assistant.images.providers.pds import PdsProvider

IMAGE_TYPE_BY_PLANET = {
    "earth": "photograph",
    "moon": "photograph",
    "mars": "photograph",
}


class ImageRetrievalService:
    def __init__(
        self,
        adapter,
        *,
        nasa_library: NasaImageLibraryProvider | None = None,
        gibs: GibsProvider | None = None,
        pds: PdsProvider | None = None,
        timeout_s: float = 15.0,
    ) -> None:
        self.adapter = adapter
        self._owns_providers = (
            nasa_library is None and gibs is None and pds is None
        )
        self.nasa_library = nasa_library or NasaImageLibraryProvider(timeout_s=timeout_s)
        self.gibs = gibs or GibsProvider(timeout_s=timeout_s)
        self.pds = pds or PdsProvider(timeout_s=timeout_s)

    def close(self) -> None:
        if self._owns_providers:
            for provider in (self.nasa_library, self.gibs, self.pds):
                provider.close()

    def search(self, request: ImageSearchRequest) -> ImageSearchResponse:
        limitations: list[str] = []
        missing_previews: list[MissingPreview] = []
        rejected: list[RejectedAsset] = []
        sources = []
        providers_used: list[str] = []

        candidate = None
        if request.candidate_id:
            candidate = self.adapter.get_analog(request.candidate_id)
            if candidate is None:
                limitations.append(
                    f"Candidate '{request.candidate_id}' was not found in the team "
                    "backend; no candidate-specific imagery was retrieved."
                )

        target = None
        target_query = request.target
        if target_query is None and candidate is not None:
            target_query = candidate.target_match_id
        if target_query:
            finder = getattr(self.adapter, "find_target", None)
            if finder is not None:
                target = finder(target_query)
            if target is None:
                limitations.append(
                    f"Planetary target '{target_query}' could not be resolved from the "
                    "team backend; target metadata is unavailable."
                )

        keywords = [
            keyword.strip()
            for keyword in request.feature_keywords
            if isinstance(keyword, str) and keyword.strip()
        ]
        if not keywords and candidate is not None:
            keywords.extend(
                item
                for item in (candidate.name, candidate.country, candidate.morphology)
                if item
            )
        if target is not None:
            keywords.extend(target.scientific_targets)
            if target.name:
                keywords.append(target.name)
        keywords = _unique(keywords)

        if not keywords and candidate is None and target is None:
            limitations.append(
                "No candidate, target or feature keyword was supplied, so no image "
                "provider query could be built."
            )
            return self._response(
                {}, limitations, missing_previews, rejected, sources, providers_used
            )

        records: list[ImageRecord] = []

        for planet in request.planets:
            query = _query_for(planet, keywords)
            nasa_outcome: ProviderOutcome | None = None
            try:
                nasa_outcome = self.nasa_library.search(
                    query,
                    planet=planet,
                    limit=request.max_per_planet,
                    related_candidate_id=candidate.analog_id if candidate else None,
                    related_target_id=target.target_id if target else None,
                    image_type=IMAGE_TYPE_BY_PLANET[planet],
                )
            except RateLimited as exc:
                limitations.append(
                    _rate_limit_message("NASA Image Library", exc.retry_after)
                )
            except ProviderError as exc:
                limitations.append(f"NASA Image Library unavailable: {exc}")

            if nasa_outcome is not None:
                records.extend(nasa_outcome.records)
                missing_previews.extend(nasa_outcome.missing_previews)
                rejected.extend(nasa_outcome.rejected_assets)
                sources.extend(nasa_outcome.sources)
                if nasa_outcome.records:
                    providers_used.append("nasa_image_library")
                limitations.extend(nasa_outcome.limitations)

            if planet == "earth":
                try:
                    gibs_outcome = self.gibs.layer_image(
                        layer=None,
                        latitude=candidate.latitude if candidate else None,
                        longitude=candidate.longitude if candidate else None,
                        target_layer_date=None,
                        related_candidate_id=candidate.analog_id if candidate else None,
                        related_target_id=target.target_id if target else None,
                    )
                except ProviderError as exc:
                    limitations.append(f"GIBS unavailable: {exc}")
                else:
                    records.extend(gibs_outcome.records)
                    rejected.extend(gibs_outcome.rejected_assets)
                    sources.extend(gibs_outcome.sources)
                    limitations.extend(gibs_outcome.limitations)
                    if gibs_outcome.records:
                        providers_used.append("gibs")
                continue

            # Moon and Mars also use PDS planetary products.
            try:
                pds_outcome = self.pds.search(
                    target=planet,
                    keywords=keywords,
                    limit=request.max_per_planet,
                    related_target_id=target.target_id if target else None,
                )
            except RateLimited as exc:
                limitations.append(_rate_limit_message("PDS", exc.retry_after))
                continue
            except ProviderError as exc:
                limitations.append(f"PDS unavailable: {exc}")
                continue
            records.extend(pds_outcome.records)
            missing_previews.extend(pds_outcome.missing_previews)
            rejected.extend(pds_outcome.rejected_assets)
            sources.extend(pds_outcome.sources)
            if pds_outcome.records:
                providers_used.append("pds")
            limitations.extend(pds_outcome.limitations)

        if request.image_types:
            wanted = set(request.image_types)
            records = [record for record in records if record.image_type in wanted]

        deduped = _dedupe(records)
        by_planet = {
            "earth": [r for r in deduped if r.planet == "earth"][: request.max_per_planet],
            "moon": [r for r in deduped if r.planet == "moon"][: request.max_per_planet],
            "mars": [r for r in deduped if r.planet == "mars"][: request.max_per_planet],
        }

        for planet in request.planets:
            if not by_planet.get(planet):
                limitations.append(
                    f"No verified {planet} image records were returned by the allowed "
                    "providers for this query."
                )

        return self._response(
            by_planet,
            limitations,
            missing_previews,
            rejected,
            sources,
            providers_used,
            target_id=target.target_id if target else None,
            candidate_id=candidate.analog_id if candidate else None,
        )

    def _response(
        self,
        grouped: dict[str, list[ImageRecord]],
        limitations: list[str],
        missing_previews: list[MissingPreview],
        rejected: list[RejectedAsset],
        sources: list,
        providers_used: Iterable[str],
        *,
        target_id: str | None = None,
        candidate_id: str | None = None,
    ) -> ImageSearchResponse:
        mode = DataProvenanceMode(
            getattr(self.adapter, "data_provenance_mode", "platform")
        )
        return ImageSearchResponse(
            earth=grouped.get("earth", []),
            moon=grouped.get("moon", []),
            mars=grouped.get("mars", []),
            sources=sources,
            missing_previews=missing_previews,
            rejected_assets=rejected,
            limitations=_unique(limitations),
            providers_used=_unique(providers_used),  # type: ignore[arg-type]
            resolved_target_id=target_id,
            resolved_candidate_id=candidate_id,
            data_provenance_mode=mode,
        )


def _query_for(planet: str, keywords: list[str]) -> str:
    label = {"earth": "Earth", "moon": "Moon", "mars": "Mars"}[planet]
    return " ".join([label, *keywords]).strip()


def _unique(values: Iterable[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if value not in seen:
            seen.add(value)
            result.append(value)
    return result


def _dedupe(records: list[ImageRecord]) -> list[ImageRecord]:
    seen_ids: set[str] = set()
    seen_urls: set[str] = set()
    result: list[ImageRecord] = []
    for record in records:
        if record.image_id in seen_ids:
            continue
        if record.asset_url:
            normalized = record.asset_url.split("?", 1)[0].lower()
            if normalized in seen_urls:
                continue
            seen_urls.add(normalized)
        seen_ids.add(record.image_id)
        result.append(record)
    return result


def _rate_limit_message(provider: str, retry_after: str | None) -> str:
    suffix = f" (retry after {retry_after})" if retry_after else ""
    return f"{provider} rate limit reached; partial results returned{suffix}."
