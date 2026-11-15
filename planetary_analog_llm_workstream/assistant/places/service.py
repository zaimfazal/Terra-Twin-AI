"""Place (candidate) retrieval over the team's read-only Analog records.

No ranking, no score recalculation, no invented thresholds. Filters are applied
only to documented fields; a missing field excludes a candidate from that
filter and is reported as missing data, never as a negative scientific match.
"""

from __future__ import annotations

from math import asin, cos, radians, sin, sqrt
from typing import Any, Iterable

from assistant.adapters.team_records import AnalogRecord
from assistant.places.contracts import (
    CandidateSearchFilters,
    MatchExplanation,
    PlaceSearchRequest,
    PlaceSearchResponse,
    PlaceSearchResult,
    UnavailableField,
)
from assistant.retrieval.query_parser import TEXT_SYNONYM_GROUPS, parse_place_query

# Qualitative terrain groups that also have a documented 0-100 platform index.
# They are used only as a transparent fallback when the supplied text does not
# mention the term. The index is heuristic, never a verified classification.
TERRAIN_INDEX_GROUPS: dict[str, str] = {
    "arid": "aridity",
    "volcanic": "volcanic",
    "rough": "roughness",
}


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    radius = 6371.0088
    dlat = radians(lat2 - lat1)
    dlon = radians(lon2 - lon1)
    a = (
        sin(dlat / 2) ** 2
        + cos(radians(lat1)) * cos(radians(lat2)) * sin(dlon / 2) ** 2
    )
    return 2 * radius * asin(sqrt(a))


def _haystack(analog: AnalogRecord) -> str:
    parts: list[str] = [
        analog.analog_id,
        analog.name or "",
        analog.country or "",
        analog.morphology or "",
        analog.primary_planet_analog or "",
        analog.target_match_id or "",
        *analog.scientific_breakdown.values(),
        *analog.nasa_datasets_used,
    ]
    return " ".join(parts).casefold()


def _term_needles(term: str) -> tuple[str, ...]:
    return TEXT_SYNONYM_GROUPS.get(term, (term,))


def _merge_filters(
    parsed: CandidateSearchFilters, explicit: CandidateSearchFilters | None
) -> CandidateSearchFilters:
    if explicit is None:
        return parsed

    merged = CandidateSearchFilters(
        text_terms=sorted(set(parsed.text_terms) | set(explicit.text_terms)),
        countries=sorted(set(parsed.countries) | set(explicit.countries)),
        primary_planet_analogs=sorted(
            set(parsed.primary_planet_analogs) | set(explicit.primary_planet_analogs)
        ),
        target_ids=sorted(set(parsed.target_ids) | set(explicit.target_ids)),
        dataset_terms=sorted(set(parsed.dataset_terms) | set(explicit.dataset_terms)),
        metrics={**parsed.metrics, **explicit.metrics},
    )
    merged.bounding_box = explicit.bounding_box or parsed.bounding_box
    merged.radius = explicit.radius or parsed.radius
    return merged


class PlaceSearchService:
    """Applies typed filters to records supplied by a read-only adapter."""

    def __init__(self, adapter: Any):
        self.adapter = adapter

    @property
    def provenance_mode(self) -> str:
        return getattr(self.adapter, "data_provenance_mode", "platform")

    @property
    def backend_name(self) -> str:
        return getattr(self.adapter, "backend_name", type(self.adapter).__name__)

    def search(self, request: PlaceSearchRequest) -> PlaceSearchResponse:
        parsed = parse_place_query(request.question or "")
        filters = _merge_filters(parsed.filters, request.filters)

        unavailable: list[UnavailableField] = list(parsed.unavailable_fields)
        limitations: list[str] = []
        missing_information: list[str] = []

        target_id = None
        target_name = None
        requested_target = request.target or parsed.target_reference
        if requested_target:
            resolved = self._resolve_target(requested_target)
            if resolved is None:
                limitations.append(
                    f"The planetary target '{requested_target}' could not be resolved "
                    "from the team backend, so no target filter was applied."
                )
            else:
                target_id, target_name = resolved
                if target_id not in filters.target_ids:
                    filters.target_ids.append(target_id)

        planetary_reference = request.planetary_reference or parsed.planetary_reference
        if (
            planetary_reference in {"Mars", "Moon"}
            and planetary_reference not in filters.primary_planet_analogs
        ):
            filters.primary_planet_analogs.append(planetary_reference)

        analogs = list(self.adapter.list_analogs())
        if not analogs:
            limitations.append(
                "The team backend returned no Analog candidate records."
            )

        matched: list[tuple[AnalogRecord, list[MatchExplanation]]] = []
        excluded_missing: dict[str, int] = {}

        for analog in analogs:
            explanations, missing_reason = self._evaluate(analog, filters)
            if missing_reason is not None:
                excluded_missing[missing_reason] = (
                    excluded_missing.get(missing_reason, 0) + 1
                )
                continue
            if explanations is None:
                continue
            matched.append((analog, explanations))

        total_matched = len(matched)
        page = matched[request.offset : request.offset + request.max_results]

        results = [
            self._to_result(analog, explanations)
            for analog, explanations in page
        ]

        for field, count in sorted(excluded_missing.items()):
            missing_information.append(
                f"{count} candidate(s) were excluded because '{field}' was missing "
                "in the supplied record. Missing data is not evidence of dissimilarity."
            )

        if not results:
            if analogs:
                limitations.append(
                    "No candidate record satisfied every requested filter. Nothing "
                    "was fabricated to fill the response."
                )
            else:
                limitations.append(
                    "No candidate records were available to search."
                )

        limitations.extend(parsed.notes)
        if any(
            explanation.matched_value.startswith("heuristic index")
            for result in results
            for explanation in result.match_explanations
        ):
            limitations.append(
                "Some qualitative terrain terms matched the platform's 0-100 "
                "heuristic indices where the supplied text did not mention the term. "
                "Those indices are unverified heuristic values, not geological "
                "classifications."
            )
        limitations.append(
            "Platform scores, coverage and confidence are returned exactly as "
            "supplied. They are heuristic platform values, not verified "
            "measurements, and this service does not rank or recompute them."
        )

        return PlaceSearchResponse(
            question=request.question,
            interpreted_filters=filters,
            planetary_reference=request.planetary_reference or parsed.planetary_reference,
            resolved_target_id=target_id,
            resolved_target_name=target_name,
            results=results,
            total_matched=total_matched,
            returned=len(results),
            limit=request.max_results,
            offset=request.offset,
            data_provenance_mode=self.provenance_mode,
            backend=self.backend_name,
            unavailable_fields=unavailable,
            missing_information=missing_information,
            limitations=limitations,
        )

    # ------------------------------------------------------------------
    def _resolve_target(self, requested: str) -> tuple[str, str] | None:
        finder = getattr(self.adapter, "find_target", None)
        if finder is None:
            getter = getattr(self.adapter, "get_target", None)
            target = getter(requested) if getter else None
            if target is None:
                return None
            return target.target_id, target.name
        target = finder(requested)
        if target is None:
            return None
        return target.target_id, target.name or target.target_id

    def _evaluate(
        self, analog: AnalogRecord, filters: CandidateSearchFilters
    ) -> tuple[list[MatchExplanation] | None, str | None]:
        """Return (explanations, missing_reason) or (None, None) on no match."""

        explanations: list[MatchExplanation] = []
        haystack = _haystack(analog)

        for term in filters.text_terms:
            needles = _term_needles(term)
            hit = next((needle for needle in needles if needle.casefold() in haystack), None)
            if hit is not None:
                explanations.append(
                    MatchExplanation(
                        field="text",
                        kind="text",
                        requested=term,
                        matched_value=hit,
                    )
                )
                continue
            metric = TERRAIN_INDEX_GROUPS.get(term)
            value = analog.metrics.get(metric) if metric else None
            if metric is not None and value is not None and value > 0:
                explanations.append(
                    MatchExplanation(
                        field=f"metrics.{metric}",
                        kind="text",
                        requested=term,
                        matched_value=f"heuristic index {value:g} (unverified)",
                    )
                )
                continue
            return None, None

        for country in filters.countries:
            if analog.country is None:
                return None, "country"
            if analog.country.casefold() != country.casefold():
                return None, None
            explanations.append(
                MatchExplanation(
                    field="country",
                    kind="categorical",
                    requested=country,
                    matched_value=analog.country,
                )
            )

        for planet in filters.primary_planet_analogs:
            if analog.primary_planet_analog is None:
                return None, "primary_planet_analog"
            if planet.casefold() not in analog.primary_planet_analog.casefold():
                return None, None
            explanations.append(
                MatchExplanation(
                    field="primary_planet_analog",
                    kind="categorical",
                    requested=planet,
                    matched_value=analog.primary_planet_analog,
                )
            )

        for target_id in filters.target_ids:
            if analog.target_match_id is None:
                return None, "target_match_id"
            if analog.target_match_id.casefold() != target_id.casefold():
                return None, None
            explanations.append(
                MatchExplanation(
                    field="target_match_id",
                    kind="categorical",
                    requested=target_id,
                    matched_value=analog.target_match_id,
                )
            )

        for dataset in filters.dataset_terms:
            joined = " ".join(analog.nasa_datasets_used)
            if not joined:
                return None, "nasa_datasets_used"
            if dataset.casefold() not in joined.casefold():
                return None, None
            explanations.append(
                MatchExplanation(
                    field="nasa_datasets_used",
                    kind="text",
                    requested=dataset,
                    matched_value=joined,
                )
            )

        for metric, numeric_range in filters.metrics.items():
            value = analog.metrics.get(metric)
            if value is None:
                return None, f"metrics.{metric}"
            if numeric_range.minimum is not None and value < numeric_range.minimum:
                return None, None
            if numeric_range.maximum is not None and value > numeric_range.maximum:
                return None, None
            explanations.append(
                MatchExplanation(
                    field=f"metrics.{metric}",
                    kind="numeric_range",
                    requested=_describe_range(numeric_range),
                    matched_value=str(value),
                )
            )

        if filters.bounding_box is not None:
            box = filters.bounding_box
            if analog.latitude is None or analog.longitude is None:
                return None, "location.coordinates"
            if not (
                box.min_latitude <= analog.latitude <= box.max_latitude
                and box.min_longitude <= analog.longitude <= box.max_longitude
            ):
                return None, None
            explanations.append(
                MatchExplanation(
                    field="location.coordinates",
                    kind="geographic",
                    requested=(
                        f"bbox({box.min_latitude},{box.min_longitude},"
                        f"{box.max_latitude},{box.max_longitude})"
                    ),
                    matched_value=f"{analog.latitude},{analog.longitude}",
                )
            )

        if filters.radius is not None:
            radius = filters.radius
            if analog.latitude is None or analog.longitude is None:
                return None, "location.coordinates"
            distance = haversine_km(
                radius.latitude, radius.longitude, analog.latitude, analog.longitude
            )
            if distance > radius.radius_km:
                return None, None
            explanations.append(
                MatchExplanation(
                    field="location.coordinates",
                    kind="geographic",
                    requested=f"within {radius.radius_km} km",
                    matched_value=f"{distance:.1f} km",
                )
            )

        return explanations, None

    @staticmethod
    def _to_result(
        analog: AnalogRecord, explanations: Iterable[MatchExplanation]
    ) -> PlaceSearchResult:
        return PlaceSearchResult(
            candidate_id=analog.analog_id,
            name=analog.name,
            country=analog.country,
            primary_planet_analog=analog.primary_planet_analog,
            target_match_id=analog.target_match_id,
            latitude=analog.latitude,
            longitude=analog.longitude,
            elevation_text=analog.elevation_text,
            morphology=analog.morphology,
            metrics=dict(analog.metrics),
            metric_provenance=analog.metric_provenance,
            similarity_score=analog.similarity_score,
            data_coverage=analog.data_coverage,
            data_confidence=analog.data_confidence,
            score_provenance=analog.score_provenance,
            match_explanations=list(explanations),
            missing_fields=list(analog.missing_fields),
            source_reference=f"/api/analog/{analog.analog_id}",
            is_fixture=analog.is_fixture,
        )


def _describe_range(numeric_range) -> str:
    if numeric_range.minimum is not None and numeric_range.maximum is not None:
        return f"{numeric_range.minimum}..{numeric_range.maximum}"
    if numeric_range.minimum is not None:
        return f">= {numeric_range.minimum}"
    if numeric_range.maximum is not None:
        return f"<= {numeric_range.maximum}"
    return "any"
