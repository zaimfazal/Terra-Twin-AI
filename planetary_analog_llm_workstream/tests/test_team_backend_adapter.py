"""Mocked tests for the read-only team backend adapter.

No live backend or MongoDB is used. Every response is constructed in-process
from the audited team response shapes in ``docs/llm/TEAM_INTEGRATION.md``.
"""

from __future__ import annotations

import json
from typing import Any

import httpx
import pytest

from assistant.adapters.base import AdapterUnavailable
from assistant.adapters.team_backend import TeamBackendAdapter

ANALOG_MONGO = {
    "id": "earth_atacama",
    "name": "Atacama Hyper-Arid Core (Yungay)",
    "country": "Chile",
    "elevation": "1,050 m (NASADEM)",
    "image": "https://example.invalid/atacama.jpg",
    "primary_planet_analog": "Mars",
    "target_match_id": "mars_jezero",
    "nasa_datasets_used": ["NASADEM", "MOD11A2"],
    "similarity_score": 93,
    "data_coverage": 100,
    "data_confidence": 96,
    "morphology": "HYPER-ARID REGOLITH",
    "scientific_breakdown": {
        "why_analog": "Very dry.",
        "breakdown_limits": "Pressure differs.",
        "field_test_utility": "Drill testing.",
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

ANALOG_CATALOG = {
    "id": "earth_ladakh",
    "name": "Ladakh Cold Desert",
    "country": "India",
    "elevation": "3,500 m",
    "image": "https://example.invalid/ladakh.jpg",
    "primary_planet_analog": "Mars",
    "target_match_id": "mars_jezero",
    "nasa_datasets_used": ["NASADEM"],
    "similarity_score": 0,
    "data_coverage": 100,
    "data_confidence": 95,
    "morphology": "COLD ARID",
    "scientific_breakdown": {
        "why_analog": "Cold and dry.",
        "breakdown_limits": "Lower radiation.",
        "field_test_utility": "Mobility testing.",
    },
    "metrics": {
        "relief": 70,
        "slope": 40,
        "aridity": 90,
        "thermal": 30,
        "rockiness": 65,
        "volcanic": 10,
        "access": 55,
    },
    "coordinates": {"lat": 34.15, "lon": 77.58},
}

TARGET = {
    "id": "mars_jezero",
    "name": "Jezero Crater Paleo-Lake Delta",
    "planet": "Mars",
    "coordinates": {"lat": 18.38, "lon": 77.58},
    "elevation": "-2,600 m",
    "mission_profile": "robotic_landing",
    "nasa_primary_source": "NASA MRO HiRISE",
    "image": "https://example.invalid/jezero.jpg",
    "description": "Paleo-lake delta in Jezero Crater.",
    "scientific_targets": ["Deltaic sediments"],
    "criteria_signature": {
        "roughness": 85,
        "relief": 100,
        "slope": 52,
        "aridity": 99,
        "thermal": 82,
        "rockiness": 88,
        "volcanic": 100,
        "access": 99,
    },
}

DATASET = {
    "key": "nasadem",
    "id": "NASADEM_HGT",
    "name": "NASADEM Merged Global DEM",
    "provider": "NASA LP DAAC",
    "instrument": "SRTM",
    "spatial_resolution": "30 m",
    "coverage": "Global",
    "parameters": ["Elevation"],
    "url": "https://lpdaac.usgs.gov/products/nasadem_hgtv001/",
    "doi": "10.5067/MEaSUREs/NASADEM/NASADEM_HGT.001",
}


class Recorder:
    def __init__(self, routes: dict[tuple[str, str], Any]):
        self.routes = routes
        self.calls: list[dict[str, Any]] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.calls.append(
            {
                "method": request.method,
                "path": request.url.path,
                "params": dict(request.url.params),
                "body": request.content,
            }
        )
        handler = self.routes.get((request.method, request.url.path))
        if handler is None:
            return httpx.Response(404, json={"error": "NotFound"})
        if isinstance(handler, Exception):
            raise handler
        if isinstance(handler, list):
            # A sequence of responses/exceptions consumed in order.
            item = handler.pop(0)
            if isinstance(item, Exception):
                raise item
            return item
        if callable(handler):
            return handler(request)
        return httpx.Response(200, json=handler)


def make_adapter(routes: dict[tuple[str, str], Any], **kwargs: Any) -> tuple[TeamBackendAdapter, Recorder]:
    recorder = Recorder(routes)
    adapter = TeamBackendAdapter(
        "http://backend.test",
        transport=httpx.MockTransport(recorder),
        **kwargs,
    )
    return adapter, recorder


def test_list_analogs_normalises_both_coordinate_shapes_and_preserves_scores() -> None:
    adapter, _ = make_adapter(
        {("GET", "/api/analog"): {"count": 2, "analogs": [ANALOG_MONGO, ANALOG_CATALOG]}}
    )

    analogs = adapter.list_analogs()
    adapter.close()

    atacama, ladakh = analogs
    assert (atacama.latitude, atacama.longitude) == (-24.08, -70.02)
    assert atacama.coordinate_source == "geojson_location"
    assert (ladakh.latitude, ladakh.longitude) == (34.15, 77.58)
    assert ladakh.coordinate_source == "catalog_coordinates"

    # Scores are echoed exactly: 93 stays 93, a supplied 0 stays 0 (not null).
    assert atacama.similarity_score == 93
    assert isinstance(atacama.similarity_score, int)
    assert atacama.data_coverage == 100
    assert atacama.data_confidence == 96
    assert ladakh.similarity_score == 0
    assert ladakh.similarity_score is not None


def test_missing_metric_is_not_converted_to_zero() -> None:
    adapter, _ = make_adapter({("GET", "/api/analog"): {"analogs": [ANALOG_CATALOG]}})

    analog = adapter.list_analogs()[0]
    adapter.close()

    assert "roughness" not in analog.metrics
    assert "metrics.roughness" in analog.missing_fields
    assert analog.metrics["aridity"] == 90


def test_get_analog_returns_none_on_404() -> None:
    adapter, _ = make_adapter({})

    assert adapter.get_analog("earth_missing") is None
    adapter.close()


def test_list_targets_normalises_planet_and_preserves_signature() -> None:
    adapter, _ = make_adapter({("GET", "/api/targets"): {"count": 1, "targets": [TARGET]}})

    targets = adapter.list_targets()
    adapter.close()

    assert len(targets) == 1
    target = targets[0]
    assert target.target_id == "mars_jezero"
    assert target.planet == "Mars"
    assert target.criteria_signature["relief"] == 100
    assert target.to_target_record().name == "Jezero Crater Paleo-Lake Delta"
    # Coordinates are available to image retrieval without inventing values.
    assert (target.latitude, target.longitude) == (18.38, 77.58)


def test_find_target_by_unique_name_fragment_and_none_when_ambiguous() -> None:
    other = {
        **TARGET,
        "id": "mars_gale",
        "name": "Gale Crater & Mount Sharp",
        "description": "Aeolis Mons layered deposits.",
    }
    adapter, _ = make_adapter(
        {("GET", "/api/targets"): {"targets": [TARGET, other]}}
    )

    assert adapter.find_target("jezero") is not None
    assert adapter.find_target("mars_jezero").target_id == "mars_jezero"
    assert adapter.find_target("crater") is None
    adapter.close()


def test_datasets_convert_to_dataset_provenance() -> None:
    adapter, _ = make_adapter(
        {("GET", "/api/nasa-datasets"): {"count": 1, "datasets": [DATASET]}}
    )

    provenance = adapter.get_dataset_sources(["nasadem"])
    adapter.close()

    assert len(provenance) == 1
    assert provenance[0].dataset_name == "NASADEM Merged Global DEM"
    assert provenance[0].doi == DATASET["doi"]


def test_get_retries_once_after_timeout_then_succeeds() -> None:
    ok = httpx.Response(200, json={"analogs": [ANALOG_MONGO]})
    adapter, recorder = make_adapter(
        {("GET", "/api/analog"): [httpx.ConnectTimeout("boom"), ok]},
        max_retries=1,
    )

    analogs = adapter.list_analogs()
    adapter.close()

    assert len(analogs) == 1
    assert len(recorder.calls) == 2


def test_unreachable_backend_raises_adapter_unavailable() -> None:
    adapter, _ = make_adapter(
        {("GET", "/api/analog"): httpx.ConnectError("refused")},
        max_retries=1,
    )

    with pytest.raises(AdapterUnavailable):
        adapter.list_analogs()
    adapter.close()


def test_non_readonly_post_is_refused_without_network() -> None:
    adapter, recorder = make_adapter({})

    with pytest.raises(AdapterUnavailable):
        adapter._request_json("POST", "/api/analog/search", json_body={})
    with pytest.raises(AdapterUnavailable):
        adapter._request_json("DELETE", "/api/analog/earth_atacama")
    adapter.close()

    assert recorder.calls == []


def test_invalid_base_urls_are_rejected() -> None:
    for bad in ("localhost:8000", "ftp://backend.test", "http://user:pw@backend.test"):
        with pytest.raises(AdapterUnavailable):
            TeamBackendAdapter(bad)


def test_reports_and_evidence_are_not_synthesised() -> None:
    adapter, _ = make_adapter({})

    assert adapter.get_report("REPORT-001") is None
    assert adapter.get_reports_for_candidate("earth_atacama") == []
    assert adapter.get_evidence_for_candidate("earth_atacama") == []
    assert adapter.get_evidence(["EV-1"]) == []
    assert adapter.get_contradictions("earth_atacama") == []
    adapter.close()


def test_health_reports_unreachable_without_raising() -> None:
    adapter, _ = make_adapter({("GET", "/api/health"): httpx.ConnectError("refused")})

    health = adapter.health()
    adapter.close()

    assert health["reachable"] is False
    assert health["backend"] == "terratwin_express"
    assert "error" in health


def test_settings_uses_unprefixed_backend_url(monkeypatch) -> None:
    from assistant.config import Settings

    monkeypatch.setenv("TERRATWIN_BACKEND_URL", "http://team-backend.internal:8000")
    settings = Settings(_env_file=None)

    assert settings.team_backend_url == "http://team-backend.internal:8000"
    assert settings.team_backend_timeout_s == 10.0


def test_nearby_and_polygon_use_documented_read_only_paths() -> None:
    routes = {
        ("GET", "/api/analog/nearby"): {
            "source": "MongoDB 2dsphere $near spatial query",
            "count": 1,
            "results": [ANALOG_MONGO],
        },
        ("POST", "/api/analog/within-polygon"): {
            "source": "MongoDB $geoWithin polygon spatial query",
            "count": 1,
            "results": [ANALOG_MONGO],
        },
    }
    adapter, recorder = make_adapter(routes)

    nearby = adapter.list_analogs_near(-24.0, -70.0, 500)
    inside = adapter.analogs_within_polygon(
        [[-71.0, -25.0], [-69.0, -25.0], [-69.0, -23.0], [-71.0, -23.0]]
    )
    adapter.close()

    assert len(nearby) == 1 and len(inside) == 1
    assert recorder.calls[0]["path"] == "/api/analog/nearby"
    assert recorder.calls[0]["params"]["maxDistanceKm"] == "500"
    assert recorder.calls[1]["method"] == "POST"
    assert recorder.calls[1]["path"] == "/api/analog/within-polygon"
    body = json.loads(recorder.calls[1]["body"])
    assert body["polygon_coordinates"][0] == [-71.0, -25.0]
