"""Tests for place retrieval: parsing, filtering, provenance and immutability."""

from __future__ import annotations

from typing import Any

from fastapi.testclient import TestClient

from assistant.adapters.team_records import AnalogRecord, normalise_analog
from assistant.api import create_app
from assistant.places.contracts import (
    BoundingBox,
    CandidateSearchFilters,
    NumericRange,
    PlaceSearchRequest,
)
from assistant.places.service import PlaceSearchService
from assistant.retrieval.query_parser import parse_place_query
from assistant.service import AssistantService


def _analog(raw: dict[str, Any]) -> AnalogRecord:
    return normalise_analog(raw)


def _base(**overrides: Any) -> dict[str, Any]:
    record = {
        "id": "earth_atacama",
        "name": "Atacama Hyper-Arid Core (Yungay)",
        "country": "Chile",
        "elevation": "1,050 m (NASADEM)",
        "image": "https://example.invalid/a.jpg",
        "primary_planet_analog": "Mars",
        "target_match_id": "mars_jezero",
        "nasa_datasets_used": ["NASADEM", "MOD11A2"],
        "similarity_score": 93,
        "data_coverage": 100,
        "data_confidence": 96,
        "morphology": "HYPER-ARID NITROGEN-ENRICHED PERCHLORATE REGOLITH",
        "scientific_breakdown": {
            "why_analog": "Lowest mean annual precipitation; desiccated saline soils.",
            "breakdown_limits": "Atmospheric pressure differs.",
            "field_test_utility": "Rover drill testing.",
        },
        "metrics": {
            "roughness": 62,
            "relief": 58,
            "slope": 35,
            "aridity": 99,
            "thermal": 84,
            "rockiness": 72,
            "volcanic": 60,
            "access": 70,
        },
        "location": {"type": "Point", "coordinates": [-70.02, -24.08]},
    }
    record.update(overrides)
    return record


ATACAMA = _analog(_base())

MCMURDO = _analog(
    _base(
        id="earth_mcmurdo",
        name="McMurdo Dry Valleys",
        country="Antarctica",
        primary_planet_analog="Moon / Mars Polar",
        target_match_id="moon_south_pole",
        similarity_score=96,
        morphology="CRYOGENIC HYPER-ARID POLAR DESERT",
        scientific_breakdown={
            "why_analog": "Cold desert with dry permafrost.",
            "breakdown_limits": "Seasonal daylight differs.",
            "field_test_utility": "Cryogenic drill testing.",
        },
        metrics={
            "roughness": 86,
            "relief": 84,
            "slope": 72,
            "aridity": 98,
            "thermal": 96,
            "rockiness": 78,
            "volcanic": 35,
            "access": 98,
        },
        location={"type": "Point", "coordinates": [160.75, -77.85]},
    )
)

LADAKH_RAW = _base(
    id="earth_ladakh",
    name="Ladakh Cold Desert",
    country="India",
    primary_planet_analog="Mars",
    target_match_id="mars_jezero",
    similarity_score=0,
    morphology="COLD ARID HIGH-ALTITUDE DESERT",
    scientific_breakdown={
        "why_analog": "Cold arid terrain with thin soils.",
        "breakdown_limits": "Lower radiation than Mars.",
        "field_test_utility": "Mobility testing.",
    },
    coordinates={"lat": 34.15, "lon": 77.58},
)
LADAKH_RAW.pop("location")
LADAKH_RAW["metrics"] = {
    "relief": 70,
    "slope": 40,
    "aridity": 90,
    "thermal": 30,
    "rockiness": 65,
    "volcanic": 10,
    "access": 55,
}
LADAKH = _analog(LADAKH_RAW)

MAUNA_LOA = _analog(
    _base(
        id="earth_mauna_loa",
        name="Mauna Loa Basaltic Shield",
        country="United States",
        primary_planet_analog="Moon",
        target_match_id="moon_tranquillitatis",
        similarity_score=91,
        morphology="BASALTIC SHIELD VOLCANO",
        scientific_breakdown={
            "why_analog": "Basaltic lava terrain.",
            "breakdown_limits": "Gravity differs.",
            "field_test_utility": "Robotic mobility testing.",
        },
        metrics={
            "roughness": 70,
            "relief": 90,
            "slope": 25,
            "aridity": 40,
            "thermal": 55,
            "rockiness": 80,
            "volcanic": 100,
            "access": 60,
        },
        location={"type": "Point", "coordinates": [-155.47, 19.48]},
    )
)


class FakeAdapter:
    backend_name = "fake_team_backend"
    data_provenance_mode = "platform"

    def __init__(self, analogs: list[AnalogRecord], targets=None):
        self.analogs = analogs
        self.targets = targets or {}

    def list_analogs(self, limit: int | None = None) -> list[AnalogRecord]:
        return self.analogs if limit is None else self.analogs[:limit]

    def find_target(self, target_id_or_name: str):
        needle = target_id_or_name.casefold()
        for target_id, name in self.targets.items():
            if target_id.casefold() == needle or name.casefold() == needle:
                return type(
                    "Target", (), {"target_id": target_id, "name": name}
                )()
        matches = [
            (target_id, name)
            for target_id, name in self.targets.items()
            if needle in name.casefold()
        ]
        if len(matches) == 1:
            target_id, name = matches[0]
            return type("Target", (), {"target_id": target_id, "name": name})()
        return None


def make_service(analogs=None, targets=None) -> PlaceSearchService:
    return PlaceSearchService(
        FakeAdapter(
            analogs if analogs is not None else [ATACAMA, MCMURDO, LADAKH, MAUNA_LOA],
            targets
            if targets is not None
            else {
                "mars_jezero": "Jezero Crater Paleo-Lake Delta",
                "moon_south_pole": "Lunar South Pole",
            },
        )
    )


# ---------------------------------------------------------------------------
# Parser
# ---------------------------------------------------------------------------
def test_parser_extracts_terrain_terms_and_planet_without_inventing_thresholds() -> None:
    parsed = parse_place_query("Find arid environments with volcanic terrain similar to Mars.")

    assert "arid" in parsed.filters.text_terms
    assert "volcanic" in parsed.filters.text_terms
    assert parsed.filters.primary_planet_analogs == ["Mars"]
    assert parsed.filters.metrics == {}
    assert parsed.planetary_reference == "Mars"


def test_parser_only_creates_numeric_ranges_from_explicit_numbers() -> None:
    parsed = parse_place_query("Find candidates with roughness above 70 and slope between 10 and 20")

    assert parsed.filters.metrics["roughness"].minimum == 70
    assert parsed.filters.metrics["slope"].minimum == 10
    assert parsed.filters.metrics["slope"].maximum == 20

    vague = parse_place_query("Find rough terrain with low local relief")
    assert vague.filters.metrics == {}


def test_parser_reports_unsupported_fields_instead_of_guessing() -> None:
    parsed = parse_place_query(
        "Find locations with sparse vegetation, mineralogy, and elevation above 3000 m"
    )

    fields = {item.field for item in parsed.unavailable_fields}
    assert {"vegetation", "mineralogy", "elevation_numeric"} <= fields
    # Elevation is text in the team schema, so no numeric elevation filter exists.
    assert "elevation_numeric" not in parsed.filters.metrics


def test_parser_resolves_known_target_keywords() -> None:
    parsed = parse_place_query("Find Earth candidates comparable to Jezero Crater")
    assert parsed.target_reference == "mars_jezero"
    assert "mars_jezero" in parsed.filters.target_ids


# ---------------------------------------------------------------------------
# Search
# ---------------------------------------------------------------------------
def test_search_matches_arid_volcanic_mars_candidates() -> None:
    response = make_service().search(
        PlaceSearchRequest(question="Find arid volcanic terrain similar to Mars")
    )

    ids = [result.candidate_id for result in response.results]
    assert ids == ["earth_atacama", "earth_mcmurdo", "earth_ladakh"]
    assert response.data_provenance_mode == "platform"
    assert response.ordering == "backend_order_preserved"
    assert any(
        "unverified heuristic values" in item for item in response.limitations
    )


def test_search_preserves_supplied_scores_exactly_and_does_not_rank() -> None:
    response = make_service().search(
        PlaceSearchRequest(question="Show Earth candidates", max_results=10)
    )

    assert [r.candidate_id for r in response.results] == [
        "earth_atacama",
        "earth_mcmurdo",
        "earth_ladakh",
        "earth_mauna_loa",
    ]
    atacama = response.results[0]
    ladakh = response.results[2]
    assert atacama.similarity_score == 93
    assert ladakh.similarity_score == 0
    assert ladakh.similarity_score is not None
    assert atacama.data_coverage == 100
    assert atacama.data_confidence == 96
    assert atacama.score_provenance and "unverified" in atacama.score_provenance


def test_missing_metric_excludes_candidate_and_is_reported_as_missing_data() -> None:
    # Ladakh has no roughness value. A roughness filter must not treat that as 0
    # or as evidence of dissimilarity.
    response = make_service().search(
        PlaceSearchRequest(
            question="Find candidates with roughness above 60",
            max_results=10,
        )
    )

    assert [r.candidate_id for r in response.results] == [
        "earth_atacama",
        "earth_mcmurdo",
        "earth_mauna_loa",
    ]
    assert any("metrics.roughness" in item for item in response.missing_information)
    assert any("not evidence of dissimilarity" in item for item in response.missing_information)


def test_explicit_filters_merge_with_question_filters() -> None:
    response = make_service().search(
        PlaceSearchRequest(
            question="Find arid terrain",
            filters=CandidateSearchFilters(
                countries=["Chile"],
                metrics={"aridity": NumericRange(minimum=95)},
            ),
        )
    )

    assert [r.candidate_id for r in response.results] == ["earth_atacama"]
    fields = {explanation.field for explanation in response.results[0].match_explanations}
    assert {"country", "metrics.aridity", "text"} <= fields


def test_bounding_box_filter_uses_supplied_coordinates_only() -> None:
    response = make_service().search(
        PlaceSearchRequest(
            filters=CandidateSearchFilters(
                bounding_box=BoundingBox(
                    min_latitude=-30,
                    max_latitude=-10,
                    min_longitude=-80,
                    max_longitude=-60,
                )
            )
        )
    )

    assert [r.candidate_id for r in response.results] == ["earth_atacama"]
    explanation = response.results[0].match_explanations[0]
    assert explanation.kind == "geographic"
    assert explanation.matched_value == "-24.08,-70.02"


def test_empty_result_is_explicit_and_not_filled() -> None:
    response = make_service().search(
        PlaceSearchRequest(question="Find sulfate-rich hydrothermal sites on Mars")
    )

    assert response.results == []
    assert response.total_matched == 0
    assert any("Nothing was fabricated" in item for item in response.limitations)


def test_unresolved_target_does_not_silently_filter_everything() -> None:
    response = make_service().search(
        PlaceSearchRequest(
            question="Find candidates similar to a named basin",
            target="Atlantis Basin",
        )
    )

    assert response.resolved_target_id is None
    assert any("could not be resolved" in item for item in response.limitations)
    # The unresolved target is not invented and does not remove all records.
    assert len(response.results) >= 1


def test_pagination_does_not_change_backend_order() -> None:
    response = make_service().search(
        PlaceSearchRequest(question="Show Earth candidates", max_results=2, offset=1)
    )

    assert [r.candidate_id for r in response.results] == [
        "earth_mcmurdo",
        "earth_ladakh",
    ]
    assert response.total_matched == 4
    assert response.returned == 2


def test_every_result_carries_provenance_and_source_reference() -> None:
    response = make_service().search(
        PlaceSearchRequest(question="Show Mars candidates")
    )

    for result in response.results:
        assert result.metric_provenance and "unverified" in result.metric_provenance
        assert result.source_reference == f"/api/analog/{result.candidate_id}"


# ---------------------------------------------------------------------------
# API
# ---------------------------------------------------------------------------
def test_places_search_api_route(test_settings) -> None:
    service = AssistantService(
        test_settings, adapter=FakeAdapter([ATACAMA, MCMURDO, LADAKH, MAUNA_LOA])
    )
    try:
        with TestClient(create_app(service=service)) as client:
            response = client.post(
                "/api/assistant/places/search",
                json={"question": "Find arid volcanic terrain similar to Mars"},
            )
        assert response.status_code == 200
        data = response.json()
        assert data["results"][0]["candidate_id"] == "earth_atacama"
        assert data["results"][0]["similarity_score"] == 93
        assert data["data_provenance_mode"] == "platform"
    finally:
        service.store.close()


def test_places_search_api_requires_question_or_filters(test_settings) -> None:
    service = AssistantService(test_settings, adapter=FakeAdapter([ATACAMA]))
    try:
        with TestClient(create_app(service=service)) as client:
            response = client.post("/api/assistant/places/search", json={})
        assert response.status_code == 422
    finally:
        service.store.close()
